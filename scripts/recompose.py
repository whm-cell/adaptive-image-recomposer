#!/usr/bin/env python3
"""CLI entrypoint for the Adaptive Image Recomposer Skill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from recomposer_core import (
    SKILL_PROTOCOL_VERSION,
    RecomposerError,
    build_qa_report,
    build_render_authorization,
    build_route_decision,
    build_selection_record,
    compile_direction_board,
    create_manifest_draft,
    load_catalog,
    load_json,
    record_render_attempt,
    sha256_file,
    validate_manifest,
    write_compiled_artifacts,
    write_json,
)


SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = SKILL_ROOT / "references" / "strategies" / "catalog.json"
MACHINE_MODE = False
CURRENT_COMMAND = "unknown"


def _artifact_records(value: Dict[str, Any]) -> list[Dict[str, Any]]:
    candidates: list[tuple[str, str]] = []
    for key in (
        "output",
        "direction_board",
        "route",
        "result_image",
        "render_boundary",
        "authorization",
        "render_ledger",
    ):
        path = value.get(key)
        if isinstance(path, str):
            candidates.append((key, path))
    outputs = value.get("outputs")
    if isinstance(outputs, dict):
        candidates.extend(
            (str(name), path)
            for name, path in outputs.items()
            if isinstance(path, str)
        )
    records: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for name, raw_path in candidates:
        path = Path(raw_path)
        if raw_path in seen or not path.is_file():
            continue
        seen.add(raw_path)
        records.append(
            {
                "name": name,
                "path": str(path),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    return records


def _machine_response(
    *,
    command: str,
    business_status: str,
    result: Optional[Dict[str, Any]],
    error: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return {
        "protocol_version": SKILL_PROTOCOL_VERSION,
        "command": command,
        "business_status": business_status,
        "result": result,
        "artifacts": _artifact_records(result) if result is not None else [],
        "error": error,
    }


def _print_json(value: Dict[str, Any]) -> None:
    if MACHINE_MODE:
        response = _machine_response(
            command=CURRENT_COMMAND,
            business_status=str(value.get("status", "completed")),
            result=value,
        )
        print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
        return
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _catalog(path: Optional[str]) -> Dict[str, Any]:
    return load_catalog(Path(path).expanduser().resolve() if path else DEFAULT_CATALOG)


def cmd_inspect(args: argparse.Namespace) -> int:
    manifest = create_manifest_draft(Path(args.image), ocr=args.ocr, job_id=args.job_id)
    output = Path(args.out).expanduser().resolve()
    write_json(manifest, output)
    _print_json(
        {
            "status": "draft_created",
            "output": str(output),
            "job_id": manifest["job_id"],
            "next": "View the image, complete semantic fields, remove resolved uncertainties, then run validate.",
        }
    )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    manifest = load_json(Path(args.manifest).expanduser().resolve())
    report = validate_manifest(manifest)
    _print_json(
        {
            "status": "validated" if report["valid"] else "validation_failed",
            **report,
        }
    )
    return 0 if MACHINE_MODE or report["valid"] else 1


def cmd_route(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = load_json(manifest_path)
    route = build_route_decision(manifest, _catalog(args.catalog), top_k=args.top_k)
    output = Path(args.out).expanduser().resolve()
    write_json(route, output)
    board_path = output.with_name("direction-board.md")
    board_path.write_text(compile_direction_board(route), encoding="utf-8")
    _print_json(
        {
            "status": "awaiting_human_selection",
            "output": str(output),
            "direction_board": str(board_path),
            "renderer": route["renderer"],
            "direction_mode": route["direction_mode"],
            "diversity_summary": route["diversity_summary"],
            "recommendations": route["recommendations"],
            "candidates": [candidate["id"] for candidate in route["candidates"]],
            "next": "A human compares the direction board, then records one choice with the select command.",
        }
    )
    return 0


def cmd_select(args: argparse.Namespace) -> int:
    route = load_json(Path(args.route).expanduser().resolve())
    selection = build_selection_record(
        route,
        args.strategy,
        selected_by="human",
        rationale=args.rationale or "",
    )
    output = Path(args.out).expanduser().resolve()
    write_json(selection, output)
    _print_json(
        {
            "status": "direction_selected",
            "output": str(output),
            "selected_strategy_id": selection["selected_strategy_id"],
            "recommendation_profile": selection["recommendation_profile"],
            "next": "Compile this selection record with the manifest and its matching route.",
        }
    )
    return 0


def cmd_compile(args: argparse.Namespace) -> int:
    manifest = load_json(Path(args.manifest).expanduser().resolve())
    route = load_json(Path(args.route).expanduser().resolve())
    selection = load_json(Path(args.selection).expanduser().resolve())
    outputs = write_compiled_artifacts(
        manifest,
        route,
        selection,
        _catalog(args.catalog),
        Path(args.out_dir).expanduser().resolve(),
    )
    _print_json(
        {
            "status": "awaiting_render_authorization",
            "outputs": {key: str(value) for key, value in outputs.items()},
            "note": "Compilation made no image-provider call and spent no image-generation attempt.",
            "next": "Review the contract, then record one explicit human authorization with authorize-render before invoking any image provider.",
        }
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = load_json(manifest_path)
    catalog = _catalog(args.catalog)
    route = build_route_decision(manifest, catalog, top_k=args.top_k)
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    route_path = out_dir / "route-decision.json"
    board_path = out_dir / "direction-board.md"
    write_json(route, route_path)
    board_path.write_text(compile_direction_board(route), encoding="utf-8")
    if not args.selection:
        _print_json(
            {
                "status": "awaiting_human_selection",
                "route": str(route_path),
                "direction_board": str(board_path),
                "renderer": route["renderer"],
                "recommendations": route["recommendations"],
                "note": "Run intentionally stopped at the human checkpoint; no strategy was auto-selected and no render contract was compiled.",
            }
        )
        return 0
    selection = load_json(Path(args.selection).expanduser().resolve())
    outputs = write_compiled_artifacts(manifest, route, selection, catalog, out_dir)
    _print_json(
        {
            "status": "awaiting_render_authorization",
            "route": str(route_path),
            "renderer": route["renderer"],
            "selected_strategy_id": selection["selected_strategy_id"],
            "outputs": {key: str(value) for key, value in outputs.items()},
            "note": "Compilation continued because a human direction selection was supplied, but direction selection does not authorize an image-provider call.",
        }
    )
    return 0


def cmd_authorize_render(args: argparse.Namespace) -> int:
    boundary = load_json(Path(args.boundary).expanduser().resolve())
    ledger_path = Path(args.ledger).expanduser().resolve()
    ledger = load_json(ledger_path) if ledger_path.is_file() else None
    authorization, updated_ledger = build_render_authorization(
        boundary,
        attempt_kind=args.attempt_kind,
        rationale=args.rationale,
        ledger=ledger,
    )
    output = Path(args.out).expanduser().resolve()
    write_json(authorization, output)
    write_json(updated_ledger, ledger_path)
    _print_json(
        {
            "status": "one_render_call_authorized",
            "authorization": str(output),
            "render_ledger": str(ledger_path),
            "authorization_id": authorization["authorization_id"],
            "attempt_kind": authorization["attempt_kind"],
            "maximum_external_calls": 1,
            "automatic_retry": False,
            "note": "This command only records permission. It did not invoke, cancel, bill, or guarantee an image-provider request.",
            "next": "Invoke exactly one external image request with the bound contract, then close this authorization with record-render.",
        }
    )
    return 0


def cmd_record_render(args: argparse.Namespace) -> int:
    boundary = load_json(Path(args.boundary).expanduser().resolve())
    authorization = load_json(Path(args.authorization).expanduser().resolve())
    ledger_path = Path(args.ledger).expanduser().resolve()
    ledger = load_json(ledger_path)
    result_image = (
        Path(args.result_image).expanduser().resolve() if args.result_image else None
    )
    updated_ledger = record_render_attempt(
        boundary,
        authorization,
        ledger,
        provider_status=args.provider_status,
        result_image=result_image,
        provider_message=args.provider_message or "",
    )
    write_json(updated_ledger, ledger_path)
    latest = updated_ledger["attempts"][-1]
    if args.provider_status == "returned":
        status = "artifact_returned_display_required"
        next_action = (
            "Display result_image to the human immediately, even if subsequent QA fails; "
            "then run qa and label the artifact pass, conditional, or fail."
        )
    elif args.provider_status == "provider_failure":
        status = "provider_failure_reauthorization_required"
        next_action = (
            "Report that no artifact was returned and provider billing is outside this Skill. "
            "Do not retry without a new explicit human authorization."
        )
    else:
        status = "authorization_closed_before_call"
        next_action = "Obtain a new explicit human authorization before any future provider call."
    _print_json(
        {
            "status": status,
            "render_ledger": str(ledger_path),
            "authorization_id": authorization["authorization_id"],
            "provider_status": args.provider_status,
            "result_image": str(result_image) if result_image else None,
            "presentation_required": args.provider_status == "returned",
            "qa_may_suppress_artifact": False,
            "automatic_retry_started": latest["retry_automatically_started"],
            "next": next_action,
        }
    )
    return 0


def cmd_qa(args: argparse.Namespace) -> int:
    manifest = load_json(Path(args.manifest).expanduser().resolve())
    route = load_json(Path(args.route).expanduser().resolve())
    layout = load_json(Path(args.plan).expanduser().resolve())
    observed_text = None
    observed_text_source = None
    if args.ocr_text:
        ocr_path = Path(args.ocr_text).expanduser().resolve()
        try:
            observed_text = ocr_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise RecomposerError(f"OCR text file does not exist: {ocr_path}") from exc
        observed_text_source = "provided_text_file"
    observations = None
    if args.observations_json:
        observations = load_json(Path(args.observations_json).expanduser().resolve())
    result_image = (
        Path(args.result_image).expanduser().resolve() if args.result_image else None
    )
    report = build_qa_report(
        manifest,
        route,
        layout,
        result_image=result_image,
        observed_text=observed_text,
        observed_text_source=observed_text_source,
        observations=observations,
        protected_pixels_verified=args.protected_pixels_verified,
        visual_review_passed=args.visual_review_passed,
        integration_review_passed=args.integration_review_passed,
    )
    output = Path(args.out).expanduser().resolve()
    write_json(report, output)
    _print_json(
        {
            "status": report["status"],
            "output": str(output),
            "result_image": str(result_image) if result_image else None,
            "presentation_required": result_image is not None,
            "qa_may_suppress_artifact": False,
            "failures": report["failures"],
            "manual_checks": report["manual_checks"],
        }
    )
    return 0 if MACHINE_MODE or report["status"] != "fail" else 1


def cmd_strategies(args: argparse.Namespace) -> int:
    catalog = _catalog(args.catalog)
    _print_json(
        {
            "catalog_version": catalog["catalog_version"],
            "direction_families": catalog["families"],
            "visual_systems": catalog["visual_systems"],
            "asset_preparation_modes": catalog["asset_preparation_modes"],
            "embedding_grammars": catalog["embedding_grammars"],
            "strategies": [
                {
                    "id": item["id"],
                    "title": item["title"],
                    "direction_family": item["direction_family"],
                    "topology_family": item["topology_family"],
                    "supports": item["supports"],
                    "text_density": item["text_density"],
                    "renderers": item["renderers"],
                    "aspects": item["aspects"],
                    "reference": f"references/strategies/{item['leaf']}",
                }
                for item in catalog["strategies"]
            ],
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect, route, compile, and validate joint or audited image reconstruction jobs."
    )
    parser.add_argument(
        "--machine",
        action="store_true",
        help="Emit exactly one compact JSON protocol response on stdout",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Create a machine metadata and OCR draft")
    inspect_parser.add_argument("image", help="Input raster image")
    inspect_parser.add_argument("--out", required=True, help="Draft manifest JSON output")
    inspect_parser.add_argument(
        "--job-id",
        help="Optional caller-owned task identifier written into the draft manifest",
    )
    inspect_parser.add_argument(
        "--ocr",
        default="auto",
        help="OCR mode: auto, off, or a Tesseract language expression such as chi_sim+eng",
    )
    inspect_parser.set_defaults(func=cmd_inspect)

    validate_parser = subparsers.add_parser("validate", help="Validate a completed source manifest")
    validate_parser.add_argument("manifest", help="Completed source manifest JSON")
    validate_parser.set_defaults(func=cmd_validate)

    route_parser = subparsers.add_parser(
        "route", help="Build compatible, family-diverse reconstruction concept lanes"
    )
    route_parser.add_argument("manifest", help="Completed source manifest JSON")
    route_parser.add_argument("--out", required=True, help="Route decision JSON output")
    route_parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Override manifest intent.direction_count (default 6, maximum 12)",
    )
    route_parser.add_argument("--catalog", help="Optional strategy catalog override")
    route_parser.set_defaults(func=cmd_route)

    select_parser = subparsers.add_parser(
        "select", help="Record one explicit human choice from a validated direction board"
    )
    select_parser.add_argument("route", help="Route decision JSON")
    select_parser.add_argument("--strategy", required=True, help="Chosen shortlist strategy id")
    select_parser.add_argument("--out", required=True, help="Selection record JSON output")
    select_parser.add_argument("--rationale", help="Optional human decision rationale")
    select_parser.set_defaults(func=cmd_select)

    compile_parser = subparsers.add_parser(
        "compile",
        help="Compile a human-selected joint reconstruction and production contract",
    )
    compile_parser.add_argument("manifest", help="Completed source manifest JSON")
    compile_parser.add_argument("route", help="Route decision JSON")
    compile_parser.add_argument(
        "--selection", required=True, help="Independent selection record created by select"
    )
    compile_parser.add_argument("--out-dir", required=True, help="Artifact output directory")
    compile_parser.add_argument("--catalog", help="Optional strategy catalog override")
    compile_parser.set_defaults(func=cmd_compile)

    run_parser = subparsers.add_parser(
        "run", help="Route and stop for human selection, or continue with a prior selection record"
    )
    run_parser.add_argument("manifest", help="Completed source manifest JSON")
    run_parser.add_argument("--out-dir", required=True, help="Artifact output directory")
    run_parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Override manifest intent.direction_count (default 6, maximum 12)",
    )
    run_parser.add_argument(
        "--selection",
        help="Optional prior human selection record; without it run stops at the human checkpoint",
    )
    run_parser.add_argument("--catalog", help="Optional strategy catalog override")
    run_parser.set_defaults(func=cmd_run)

    authorize_parser = subparsers.add_parser(
        "authorize-render",
        help="Record one explicit human authorization without invoking an image provider",
    )
    authorize_parser.add_argument("boundary", help="Compiled render-boundary.json")
    authorize_parser.add_argument(
        "--attempt-kind",
        required=True,
        choices=("initial", "targeted_repair", "provider_retry"),
        help="Initial request, repair of a returned artifact, or retry after provider failure",
    )
    authorize_parser.add_argument(
        "--rationale",
        required=True,
        help="Explicit human instruction or reason authorizing exactly one external call",
    )
    authorize_parser.add_argument(
        "--ledger",
        required=True,
        help="Render ledger JSON; created on first authorization and updated in place",
    )
    authorize_parser.add_argument(
        "--out", required=True, help="One-use render authorization JSON output"
    )
    authorize_parser.set_defaults(func=cmd_authorize_render)

    record_parser = subparsers.add_parser(
        "record-render",
        help="Close one authorization and record a returned artifact or provider failure",
    )
    record_parser.add_argument("boundary", help="Compiled render-boundary.json")
    record_parser.add_argument(
        "--authorization", required=True, help="One-use render authorization JSON"
    )
    record_parser.add_argument(
        "--ledger", required=True, help="Existing render ledger JSON updated in place"
    )
    record_parser.add_argument(
        "--provider-status",
        required=True,
        choices=("returned", "provider_failure", "cancelled_before_call"),
    )
    record_parser.add_argument(
        "--result-image",
        help="Returned image path; required only with --provider-status returned",
    )
    record_parser.add_argument(
        "--provider-message", help="Optional provider failure or status detail"
    )
    record_parser.set_defaults(func=cmd_record_render)

    qa_parser = subparsers.add_parser("qa", help="Build a machine plus manual QA report")
    qa_parser.add_argument("manifest", help="Completed source manifest JSON")
    qa_parser.add_argument("--route", required=True, help="Route decision JSON")
    qa_parser.add_argument(
        "--plan",
        dest="plan",
        required=True,
        help="Canonical reconstruction plan JSON",
    )
    qa_parser.add_argument("--result-image", help="Rendered result image")
    qa_parser.add_argument("--ocr-text", help="Independent UTF-8 OCR or extracted result text")
    qa_parser.add_argument(
        "--observations-json",
        help="Structured result observations containing stable text_id, object_id, and group_id bindings",
    )
    qa_parser.add_argument("--out", required=True, help="QA report JSON output")
    qa_parser.add_argument(
        "--protected-pixels-verified",
        action="store_true",
        help="Assert that protected pixels were checked against source or layers",
    )
    qa_parser.add_argument(
        "--visual-review-passed",
        action="store_true",
        help="Assert that the named manual visual checks were completed",
    )
    qa_parser.add_argument(
        "--integration-review-passed",
        action="store_true",
        help="Assert that seamless embedding and anti-paste checks were completed",
    )
    qa_parser.set_defaults(func=cmd_qa)

    strategies_parser = subparsers.add_parser("strategies", help="List strategy catalog capabilities")
    strategies_parser.add_argument("--catalog", help="Optional strategy catalog override")
    strategies_parser.set_defaults(func=cmd_strategies)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    global CURRENT_COMMAND, MACHINE_MODE

    raw_args = list(argv) if argv is not None else sys.argv[1:]
    MACHINE_MODE = "--machine" in raw_args
    parser = build_parser()
    try:
        args = parser.parse_args(raw_args)
    except SystemExit as exc:
        if not MACHINE_MODE:
            raise
        command = next(
            (item for item in raw_args if item != "--machine" and not item.startswith("-")),
            "unknown",
        )
        response = _machine_response(
            command=command,
            business_status="error",
            result=None,
            error={"code": "invalid_arguments", "message": "CLI argument parsing failed"},
        )
        print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
        return 0 if exc.code == 0 else 2
    CURRENT_COMMAND = args.command
    if hasattr(args, "top_k") and args.top_k is not None and not 1 <= args.top_k <= 12:
        if MACHINE_MODE:
            response = _machine_response(
                command=CURRENT_COMMAND,
                business_status="error",
                result=None,
                error={"code": "invalid_arguments", "message": "--top-k must be from 1 to 12"},
            )
            print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
            return 2
        parser.error("--top-k must be from 1 to 12")
    try:
        return int(args.func(args))
    except RecomposerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if MACHINE_MODE:
            response = _machine_response(
                command=CURRENT_COMMAND,
                business_status="rejected",
                result=None,
                error={"code": "skill_rejected", "message": str(exc)},
            )
            print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
        return 2
    except Exception as exc:
        print(f"unexpected error: {exc}", file=sys.stderr)
        if MACHINE_MODE:
            response = _machine_response(
                command=CURRENT_COMMAND,
                business_status="error",
                result=None,
                error={"code": "unexpected_failure", "message": str(exc)},
            )
            print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
