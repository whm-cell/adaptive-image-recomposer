#!/usr/bin/env python3
"""CLI entrypoint for the Adaptive Image Recomposer Skill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from recomposer_core import (
    RecomposerError,
    build_qa_report,
    build_route_decision,
    build_selection_record,
    compile_direction_board,
    create_manifest_draft,
    load_catalog,
    load_json,
    validate_manifest,
    write_compiled_artifacts,
    write_json,
)


SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = SKILL_ROOT / "references" / "strategies" / "catalog.json"


def _print_json(value: Dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _catalog(path: Optional[str]) -> Dict[str, Any]:
    return load_catalog(Path(path).expanduser().resolve() if path else DEFAULT_CATALOG)


def cmd_inspect(args: argparse.Namespace) -> int:
    manifest = create_manifest_draft(Path(args.image), ocr=args.ocr)
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
    _print_json(report)
    return 0 if report["valid"] else 1


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
            "status": "render_contract_compiled",
            "outputs": {key: str(value) for key, value in outputs.items()},
            "next": "Read the selected strategy leaf, review the contract, render, then run qa.",
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
            "status": "ready_for_render",
            "route": str(route_path),
            "renderer": route["renderer"],
            "selected_strategy_id": selection["selected_strategy_id"],
            "outputs": {key: str(value) for key, value in outputs.items()},
            "note": "Compilation continued only because an independent human selection record was supplied.",
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
    result_image = Path(args.result_image) if args.result_image else None
    report = build_qa_report(
        manifest,
        route,
        layout,
        result_image=result_image,
        observed_text=observed_text,
        observed_text_source=observed_text_source,
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
            "failures": report["failures"],
            "manual_checks": report["manual_checks"],
        }
    )
    return 1 if report["status"] == "fail" else 0


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
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Create a machine metadata and OCR draft")
    inspect_parser.add_argument("image", help="Input raster image")
    inspect_parser.add_argument("--out", required=True, help="Draft manifest JSON output")
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
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "top_k") and args.top_k is not None and not 1 <= args.top_k <= 12:
        parser.error("--top-k must be from 1 to 12")
    try:
        return int(args.func(args))
    except RecomposerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
