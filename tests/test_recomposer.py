#!/usr/bin/env python3

from __future__ import annotations

import copy
import base64
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from recomposer_core import (  # noqa: E402
    RecomposerError,
    assess_strategy_capacity,
    build_asset_preparation_plan,
    build_qa_report,
    build_render_authorization,
    build_route_decision,
    build_selection_record,
    compare_required_text,
    compare_structured_observations,
    compile_direction_board,
    create_manifest_draft,
    load_catalog,
    load_json,
    load_skill_pack,
    record_render_attempt,
    skill_pack_ref,
    validate_manifest,
    write_compiled_artifacts,
)


FIXTURE = ROOT / "tests" / "fixtures" / "multi-product-comparison.json"
CATALOG = ROOT / "references" / "strategies" / "catalog.json"


class RecomposerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_json(FIXTURE)
        self.catalog = load_catalog(CATALOG)

    def _selection(self, route, index=0):
        return build_selection_record(
            route,
            route["candidates"][index]["id"],
            rationale="Human selected this lane after comparing the direction board.",
        )

    def _complete_observations(self, manifest):
        group_by_ref = {
            ref: group["id"]
            for group in manifest["content"].get("groups", [])
            for ref in group["member_refs"]
        }
        allowed = set(
            manifest["content"]["contract"]["allowed_visible_text_ids"]
        )
        return {
            "text_regions": [
                {
                    "text_id": block["id"],
                    "text": block["text"],
                    "group_id": group_by_ref.get(block["id"]),
                    "confidence": 0.99,
                }
                for block in manifest["content"]["text_blocks"]
                if block["id"] in allowed
            ],
            "object_regions": [
                {
                    "object_id": item["id"],
                    "group_id": group_by_ref.get(item["id"]),
                    "confidence": 0.99,
                }
                for item in manifest["content"]["objects"]
            ],
        }

    def _creative_portrait_manifest(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["intent"]["outcome_contract"] = "creative_reconstruction"
        manifest["intent"]["target_aspect"] = "portrait"
        manifest["render"]["iteration_mode"] = "edit_latest_result"
        manifest["preservation"]["protected_regions"] = []
        bindings = [
            ("product-mythsky", "mythsky"),
            ("product-le", "le"),
            ("product-yot", "yot"),
            ("product-bissun", "bissun"),
            ("product-ke-en", "keen"),
            ("product-smal", "smal"),
            ("product-kwi", "kwi"),
            ("product-kang", "kang"),
            ("product-gao", "gao"),
        ]
        for item in manifest["content"]["objects"]:
            item["preserve"] = "semantic"
        manifest["content"]["groups"] = [
            {
                "id": f"comparison-node-{sequence}",
                "role": "comparison_item",
                "sequence": sequence,
                "member_refs": [
                    object_id,
                    f"{prefix}-name",
                    f"{prefix}-dose",
                    f"{prefix}-combo",
                ],
            }
            for sequence, (object_id, prefix) in enumerate(bindings, start=1)
        ]
        return manifest

    def _style_reference_manifest(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["source"]["role"] = "style_reference"
        manifest["intent"]["outcome_contract"] = "creative_reconstruction"
        manifest["intent"]["output_usage"] = (
            "创作一张全新抽象海报，只参考原图的构图节奏和配色，不保留原图事实内容"
        )
        manifest["intent"]["exact_text_required"] = False
        manifest["content"] = {
            "type": "illustration_freeform",
            "item_count": 0,
            "text_density": "low",
            "objects": [],
            "text_blocks": [],
            "groups": [],
            "contract": {
                "mode": "open_world",
                "unknown_policy": "block",
                "forbid_undeclared_text": True,
                "allowed_visible_text_ids": [],
                "required_item_count": 0,
                "group_schemas": [],
            },
        }
        manifest["preservation"] = {
            "must_preserve_text_ids": [],
            "protected_regions": [],
            "forbidden_inference": [
                "原图品牌",
                "原图产品",
                "原图人物身份",
                "原图文字和数字",
                "原图功效表述",
            ],
            "source_features_to_avoid": ["原图事实内容"],
        }
        manifest["uncertainties"] = []
        manifest["render"]["preferred_mode"] = "auto"
        return manifest

    def test_fixture_is_valid(self) -> None:
        report = validate_manifest(self.manifest)
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["stats"]["object_count"], 9)
        self.assertEqual(report["stats"]["required_text_count"], 31)

    def test_skill_pack_verifies_all_controlled_files(self) -> None:
        pack = load_skill_pack(ROOT)
        reference = skill_pack_ref(pack)
        self.assertEqual(reference["id"], "adaptive-image-recomposer")
        self.assertEqual(reference["protocol_version"], "2")
        self.assertEqual(reference["schema_version"], "0.2")
        self.assertEqual(reference["catalog_version"], "0.4")
        self.assertEqual(reference["policy_version"], "0.3")
        controlled = [item["path"] for item in pack["files"]]
        self.assertIn("SKILL.md", controlled)
        self.assertIn("references/render-call-policy.md", controlled)
        self.assertIn("scripts/recompose.py", controlled)
        self.assertFalse(any("__pycache__" in path or path.endswith(".pyc") for path in controlled))

    def test_machine_protocol_has_one_json_response(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "recompose.py"),
                "--machine",
                "validate",
                str(FIXTURE),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        response = json.loads(result.stdout)
        self.assertEqual(response["protocol_version"], "2")
        self.assertEqual(response["command"], "validate")
        self.assertEqual(response["business_status"], "validated")
        self.assertTrue(response["result"]["valid"])
        self.assertIsNone(response["error"])

    def test_inspect_accepts_caller_owned_job_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "tiny.png"
            image.write_bytes(
                base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                )
            )
            output = Path(temp_dir) / "manifest.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "recompose.py"),
                    "--machine",
                    "inspect",
                    str(image),
                    "--out",
                    str(output),
                    "--ocr",
                    "off",
                    "--job-id",
                    "company-image-test-job",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(manifest["job_id"], "company-image-test-job")

    def test_machine_validation_failure_is_a_business_result(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["uncertainties"].append(
            {
                "id": "unreadable-value",
                "field": "content.text_blocks",
                "reason": "required value is unreadable",
                "severity": "blocking",
                "resolution": "request source",
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "invalid.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "recompose.py"),
                    "--machine",
                    "validate",
                    str(manifest_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response["business_status"], "validation_failed")
        self.assertFalse(response["result"]["valid"])

    def test_catalog_is_broad_and_has_no_sample_specific_route(self) -> None:
        strategy_ids = [item["id"] for item in self.catalog["strategies"]]
        self.assertEqual(len(self.catalog["families"]), 8)
        self.assertEqual(len(strategy_ids), 32)
        self.assertEqual(len(self.catalog["visual_systems"]), 12)
        self.assertEqual(len(self.catalog["asset_preparation_modes"]), 4)
        self.assertEqual(len(self.catalog["embedding_grammars"]["product"]), 5)
        self.assertEqual(len(self.catalog["embedding_grammars"]["text"]), 6)
        self.assertNotIn("portrait-serpentine-comparison", strategy_ids)
        self.assertNotIn("editorial-s-curve", strategy_ids)
        self.assertEqual(
            [strategy_id for strategy_id in strategy_ids if "serpentine" in strategy_id],
            ["serpentine-flow"],
        )

    def test_high_density_product_comparison_routes_diverse_hybrid_lanes(self) -> None:
        route = build_route_decision(self.manifest, self.catalog)
        self.assertEqual(route["skill_ref"], skill_pack_ref())
        self.assertEqual(len(route["manifest_digest"]), 64)
        self.assertEqual(route["catalog_ref"]["version"], "0.4")
        self.assertEqual(route["fidelity_tier"], "F2")
        self.assertEqual(route["renderer"], "hybrid")
        self.assertEqual(route["direction_mode"], "diverge_then_select")
        self.assertEqual(len(route["candidates"]), 6)
        self.assertGreaterEqual(route["diversity_summary"]["direction_family_count"], 6)
        self.assertEqual(route["diversity_summary"]["topology_count"], 6)
        self.assertGreaterEqual(route["diversity_summary"]["visual_family_count"], 5)
        self.assertEqual(route["workflow_state"], "AWAITING_HUMAN_SELECTION")
        self.assertNotIn("selected_strategy_id", route)
        self.assertIn("best_overall", route["recommendations"])
        self.assertIn("boldest_change", route["recommendations"])
        self.assertIn("safest_production", route["recommendations"])
        for candidate in route["candidates"]:
            self.assertIn("embedding_plan", candidate)
            self.assertIn("wireframe", candidate)
            self.assertIn("decision_scores", candidate)
        self.assertNotIn(
            "portrait-serpentine-comparison",
            [candidate["id"] for candidate in route["candidates"]],
        )

    def test_direction_count_can_cover_all_seed_families(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["intent"]["direction_count"] = 8
        route = build_route_decision(manifest, self.catalog)
        self.assertEqual(len(route["candidates"]), 8)
        self.assertEqual(route["diversity_summary"]["direction_family_count"], 8)
        self.assertEqual(route["diversity_summary"]["topology_count"], 8)

    def test_compile_produces_hybrid_contract(self) -> None:
        route = build_route_decision(self.manifest, self.catalog)
        selection = self._selection(route)
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = write_compiled_artifacts(
                self.manifest, route, selection, self.catalog, Path(temp_dir)
            )
            prompt = outputs["prompt"].read_text(encoding="utf-8")
            board = outputs["direction_board"].read_text(encoding="utf-8")
            production = json.loads(outputs["production_layers"].read_text(encoding="utf-8"))
            layout = json.loads(outputs["plan"].read_text(encoding="utf-8"))
            asset_plan = json.loads(outputs["asset_plan"].read_text(encoding="utf-8"))
            boundary = json.loads(
                outputs["render_boundary"].read_text(encoding="utf-8")
            )
            self.assertIn("layout-conditioned hybrid joint composition", prompt)
            self.assertIn("not an empty-background-first workflow", prompt)
            self.assertNotIn("hybrid backdrop generation", prompt)
            self.assertNotIn("reserve clean zones", prompt)
            self.assertNotIn("overlay-spec.json", prompt)
            self.assertIn("Concept isolation:", prompt)
            self.assertIn("Visual system:", prompt)
            self.assertIn("Embedding grammar:", prompt)
            self.assertEqual(board.count("## 方向 "), 6)
            for candidate in route["candidates"]:
                self.assertIn(candidate["presentation"]["title"], board)
                self.assertNotIn(candidate["id"], board)
            for candidate in route["candidates"][1:]:
                self.assertNotIn(candidate["id"], prompt)
            self.assertEqual(len(production["text_blocks"]), 31)
            self.assertEqual(len(production["prepared_assets"]), 9)
            self.assertEqual(asset_plan["summary"]["requires_preparation_count"], 9)
            self.assertEqual(asset_plan["summary"]["seamless_embedding_gate"], "prepare_then_compose")
            self.assertIn("direction_family", layout["strategy"])
            self.assertIn("id", layout["visual_system"])
            self.assertEqual(layout["composition_mode"], "layout-conditioned-hybrid")
            self.assertNotIn("background_only_overlay_fallback", layout)
            self.assertFalse(layout["degraded_asset_fallback"]["active"])
            self.assertEqual(layout["iteration_policy"]["automatic_retries"], 0)
            self.assertTrue(
                layout["iteration_policy"][
                    "each_external_call_requires_new_human_authorization"
                ]
            )
            self.assertEqual(
                boundary["workflow_state"], "AWAITING_RENDER_AUTHORIZATION"
            )
            self.assertFalse(boundary["external_call_started"])
            self.assertEqual(
                boundary["authorization_policy"]["automatic_retries"], 0
            )
            self.assertFalse(
                boundary["returned_artifact_policy"]["qa_may_suppress_artifact"]
            )
            self.assertIn("topology", layout["transformation_contract"]["changed_axes"])
            self.assertIn("reading_path", layout["transformation_contract"]["changed_axes"])
            self.assertNotIn("layout", outputs)
            self.assertNotIn("overlay", outputs)
            self.assertFalse((Path(temp_dir) / "layout-spec.json").exists())
            self.assertFalse((Path(temp_dir) / "overlay-spec.json").exists())

    def test_compile_can_select_any_validated_lane_without_blending(self) -> None:
        route = build_route_decision(self.manifest, self.catalog)
        selected_id = route["candidates"][-1]["id"]
        selection = build_selection_record(route, selected_id)
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = write_compiled_artifacts(
                self.manifest,
                route,
                selection,
                self.catalog,
                Path(temp_dir),
            )
            prompt = outputs["prompt"].read_text(encoding="utf-8")
            layout = json.loads(outputs["plan"].read_text(encoding="utf-8"))
            self.assertEqual(layout["strategy"]["id"], selected_id)
            self.assertIn("Concept isolation:", prompt)
            for candidate in route["candidates"]:
                if candidate["id"] != selected_id:
                    self.assertNotIn(candidate["id"], prompt)

    def test_closed_world_creative_comparison_routes_diverse_hybrid_lanes(self) -> None:
        manifest = self._creative_portrait_manifest()
        validation = validate_manifest(manifest)
        self.assertTrue(validation["valid"], validation["errors"])
        route = build_route_decision(manifest, self.catalog)
        self.assertEqual(route["fidelity_tier"], "F2")
        self.assertEqual(route["outcome_contract"], "creative_reconstruction")
        self.assertEqual(route["renderer"], "hybrid")
        self.assertEqual(len(route["candidates"]), 6)
        self.assertGreaterEqual(
            route["diversity_summary"]["direction_family_count"], 6
        )
        self.assertEqual(route["diversity_summary"]["topology_count"], 6)
        self.assertNotIn(
            "portrait-serpentine-comparison",
            [candidate["id"] for candidate in route["candidates"]],
        )

    def test_closed_world_compile_is_joint_scene_and_group_bound(self) -> None:
        manifest = self._creative_portrait_manifest()
        route = build_route_decision(manifest, self.catalog)
        selection = self._selection(route)
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = write_compiled_artifacts(
                manifest, route, selection, self.catalog, Path(temp_dir)
            )
            prompt = outputs["prompt"].read_text(encoding="utf-8")
            plan = json.loads(outputs["plan"].read_text(encoding="utf-8"))
            graph = json.loads(outputs["content_graph"].read_text(encoding="utf-8"))
            production = json.loads(outputs["production_layers"].read_text(encoding="utf-8"))
            retry = outputs["retry"].read_text(encoding="utf-8")
            board = outputs["direction_board"].read_text(encoding="utf-8")
            self.assertIn("layout-conditioned hybrid joint composition", prompt)
            self.assertIn("not an empty-background-first workflow", prompt)
            self.assertIn("Concept isolation:", prompt)
            self.assertIn("Node 1 [comparison-node-1]", prompt)
            self.assertNotIn("# Deterministic handoff", prompt)
            self.assertEqual(plan["coordinate_status"], "joint_scene_layout_engine_resolved")
            self.assertEqual(len(graph["groups"]), 9)
            self.assertEqual(len(production["group_bindings"]), 9)
            self.assertEqual(board.count("## 方向 "), 6)
            self.assertIn("fresh explicit human authorization", retry)
            self.assertIn("at most two human-authorized follow-up calls", retry)

    def test_style_reference_compiles_one_clean_non_factual_handoff(self) -> None:
        manifest = self._style_reference_manifest()
        validation = validate_manifest(manifest)
        self.assertTrue(validation["valid"], validation["errors"])
        route = build_route_decision(manifest, self.catalog)
        selection = self._selection(route)
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = write_compiled_artifacts(
                manifest, route, selection, self.catalog, Path(temp_dir)
            )
            prompt = outputs["prompt"].read_text(encoding="utf-8")
            graph = json.loads(outputs["content_graph"].read_text(encoding="utf-8"))
            plan = json.loads(outputs["plan"].read_text(encoding="utf-8"))
            production = json.loads(
                outputs["production_layers"].read_text(encoding="utf-8")
            )
            asset_plan = json.loads(outputs["asset_plan"].read_text(encoding="utf-8"))
            retry = outputs["retry"].read_text(encoding="utf-8")
            board = outputs["direction_board"].read_text(encoding="utf-8")
            selected = route["candidates"][0]

            self.assertEqual(route["outcome_contract"], "creative_reconstruction")
            self.assertTrue(all(value == 0 for value in route["content_load"].values()))
            self.assertTrue(
                all("presentation" in candidate for candidate in route["candidates"])
            )
            self.assertEqual(board.count("## 方向 "), 6)
            for candidate in route["candidates"]:
                self.assertIn(candidate["presentation"]["title"], board)
                self.assertNotIn(candidate["id"], board)
            self.assertNotIn("Reconstruction direction board", board)
            self.assertNotIn("Why it fits", board)
            self.assertNotIn("Kinetic Type Islands", board)
            self.assertNotIn("Retro Riso", board)
            self.assertNotIn("exact copy", board)
            self.assertIn("仅用于参考非事实性的构图节奏", prompt)
            self.assertIn("不得复制或重建原图中的品牌", prompt)
            self.assertIn(selected["presentation"]["title"], prompt)
            self.assertNotIn(selected["id"], prompt)
            self.assertNotIn(selected["direction_family"], prompt)
            self.assertNotIn(selected["topology_family"], prompt)
            self.assertNotIn("factual content reference", prompt)
            self.assertNotIn("Preserve verified information", prompt)
            self.assertNotIn("exact copy", prompt)
            self.assertEqual(graph["nodes"], {"objects": [], "text_blocks": []})
            self.assertEqual(graph["groups"], [])
            self.assertEqual(
                plan["model_authority"],
                "new_content_generation_with_non_factual_visual_reference",
            )
            self.assertEqual(production["text_blocks"], [])
            self.assertEqual(production["prepared_assets"], [])
            self.assertEqual(production["group_bindings"], [])
            self.assertEqual(asset_plan["items"], [])
            self.assertEqual(asset_plan["summary"]["object_count"], 0)
            self.assertIn("不得自动重试", retry)

    def test_style_reference_rejects_factual_source_content(self) -> None:
        manifest = self._style_reference_manifest()
        manifest["content"] = copy.deepcopy(self.manifest["content"])
        report = validate_manifest(manifest)
        self.assertFalse(report["valid"])
        self.assertTrue(
            any(
                "style_reference cannot carry source objects" in error
                for error in report["errors"]
            ),
            report["errors"],
        )

    def test_one_use_render_authorization_preserves_returned_artifact(self) -> None:
        route = build_route_decision(self.manifest, self.catalog)
        selection = self._selection(route)
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = write_compiled_artifacts(
                self.manifest, route, selection, self.catalog, Path(temp_dir)
            )
            boundary = load_json(outputs["render_boundary"])
            authorization, ledger = build_render_authorization(
                boundary,
                attempt_kind="initial",
                rationale="Human explicitly approved one initial image request.",
            )
            self.assertEqual(authorization["maximum_external_calls"], 1)
            self.assertFalse(authorization["automatic_retry"])
            self.assertEqual(ledger["workflow_state"], "RENDER_CALL_AUTHORIZED")
            with self.assertRaisesRegex(RecomposerError, "unused render authorization"):
                build_render_authorization(
                    boundary,
                    attempt_kind="initial",
                    rationale="This cannot replace an active authorization.",
                    ledger=ledger,
                )

            result_image = Path(temp_dir) / "returned.png"
            result_image.write_bytes(
                base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                )
            )
            ledger = record_render_attempt(
                boundary,
                authorization,
                ledger,
                provider_status="returned",
                result_image=result_image,
            )
            attempt = ledger["attempts"][0]
            self.assertEqual(
                ledger["workflow_state"], "ARTIFACT_RETURNED_DISPLAY_REQUIRED"
            )
            self.assertTrue(attempt["authorization_consumed"])
            self.assertFalse(attempt["retry_automatically_started"])
            self.assertEqual(
                attempt["result_artifact"]["presentation_status"],
                "pending_human_display",
            )
            self.assertFalse(attempt["result_artifact"]["qa_may_suppress_artifact"])
            with self.assertRaisesRegex(RecomposerError, "already consumed"):
                record_render_attempt(
                    boundary,
                    authorization,
                    ledger,
                    provider_status="returned",
                    result_image=result_image,
                )

            repair_authorization, repaired_ledger = build_render_authorization(
                boundary,
                attempt_kind="targeted_repair",
                rationale="Human inspected the returned image and approved one repair call.",
                ledger=ledger,
            )
            self.assertEqual(repair_authorization["attempt_kind"], "targeted_repair")
            self.assertEqual(len(repaired_ledger["attempts"]), 2)

    def test_provider_failure_never_starts_an_automatic_retry(self) -> None:
        route = build_route_decision(self.manifest, self.catalog)
        selection = self._selection(route)
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = write_compiled_artifacts(
                self.manifest, route, selection, self.catalog, Path(temp_dir)
            )
            boundary = load_json(outputs["render_boundary"])
            authorization, ledger = build_render_authorization(
                boundary,
                attempt_kind="initial",
                rationale="Human explicitly approved one initial image request.",
            )
            ledger = record_render_attempt(
                boundary,
                authorization,
                ledger,
                provider_status="provider_failure",
                provider_message="The provider returned no artifact.",
            )
            attempt = ledger["attempts"][0]
            self.assertEqual(
                ledger["workflow_state"],
                "PROVIDER_FAILURE_REAUTHORIZATION_REQUIRED",
            )
            self.assertIsNone(attempt["result_artifact"])
            self.assertEqual(attempt["provider_billing_status"], "outside_skill_unknown")
            self.assertFalse(attempt["retry_automatically_started"])
            with self.assertRaisesRegex(RecomposerError, "use an explicitly authorized"):
                build_render_authorization(
                    boundary,
                    attempt_kind="initial",
                    rationale="An initial call cannot be silently repeated.",
                    ledger=ledger,
                )
            with self.assertRaisesRegex(RecomposerError, "previously returned artifact"):
                build_render_authorization(
                    boundary,
                    attempt_kind="targeted_repair",
                    rationale="There is no returned image to repair.",
                    ledger=ledger,
                )
            retry_authorization, retried_ledger = build_render_authorization(
                boundary,
                attempt_kind="provider_retry",
                rationale="Human saw the provider failure and approved one retry.",
                ledger=ledger,
            )
            self.assertEqual(retry_authorization["attempt_kind"], "provider_retry")
            self.assertEqual(len(retried_ledger["attempts"]), 2)

    def test_render_cli_surfaces_returned_image_before_qa(self) -> None:
        route = build_route_decision(self.manifest, self.catalog)
        selection = self._selection(route)
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            outputs = write_compiled_artifacts(
                self.manifest, route, selection, self.catalog, temp_path
            )
            authorization_path = temp_path / "render-authorization.json"
            ledger_path = temp_path / "render-ledger.json"
            authorize = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "recompose.py"),
                    "--machine",
                    "authorize-render",
                    str(outputs["render_boundary"]),
                    "--attempt-kind",
                    "initial",
                    "--rationale",
                    "Human explicitly approved exactly one render call.",
                    "--ledger",
                    str(ledger_path),
                    "--out",
                    str(authorization_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(authorize.returncode, 0, authorize.stderr)
            authorize_response = json.loads(authorize.stdout)
            self.assertEqual(
                authorize_response["business_status"], "one_render_call_authorized"
            )
            self.assertFalse(authorize_response["result"]["automatic_retry"])

            result_image = temp_path / "returned.png"
            result_image.write_bytes(
                base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                )
            )
            record = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "recompose.py"),
                    "--machine",
                    "record-render",
                    str(outputs["render_boundary"]),
                    "--authorization",
                    str(authorization_path),
                    "--ledger",
                    str(ledger_path),
                    "--provider-status",
                    "returned",
                    "--result-image",
                    str(result_image),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(record.returncode, 0, record.stderr)
            response = json.loads(record.stdout)
            self.assertEqual(
                response["business_status"],
                "artifact_returned_display_required",
            )
            artifacts = {item["name"]: item for item in response["artifacts"]}
            self.assertEqual(
                artifacts["result_image"]["path"], str(result_image.resolve())
            )
            self.assertTrue(response["result"]["presentation_required"])
            self.assertFalse(response["result"]["qa_may_suppress_artifact"])

    def test_creative_contract_rejects_pixel_locks(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["intent"]["outcome_contract"] = "creative_reconstruction"
        report = validate_manifest(manifest)
        self.assertFalse(report["valid"])
        self.assertTrue(
            any("creative_reconstruction" in error for error in report["errors"])
        )

    def test_content_group_members_cannot_migrate_between_items(self) -> None:
        manifest = self._creative_portrait_manifest()
        manifest["content"]["groups"][1]["member_refs"].append("mythsky-dose")
        report = validate_manifest(manifest)
        self.assertFalse(report["valid"])
        self.assertTrue(
            any("belongs to multiple groups" in error for error in report["errors"])
        )

    def test_f3_evidence_rejects_explicit_model_led_renderer(self) -> None:
        manifest = self._creative_portrait_manifest()
        manifest["content"]["type"] = "evidence_comparison"
        manifest["render"]["preferred_mode"] = "model-led"
        with self.assertRaises(RecomposerError):
            build_route_decision(manifest, self.catalog)

    def test_blocking_uncertainty_stops_route(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["uncertainties"].append(
            {
                "id": "missing-price",
                "field": "content.text_blocks",
                "reason": "required value is unreadable",
                "severity": "blocking",
                "resolution": "request source",
            }
        )
        with self.assertRaises(RecomposerError):
            build_route_decision(manifest, self.catalog)

    def test_evidence_comparison_routes_locked_composite(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["content"]["type"] = "evidence_comparison"
        manifest["content"]["text_density"] = "medium"
        manifest["intent"]["target_aspect"] = "portrait"
        manifest["preservation"]["protected_regions"][0]["reason"] = "before/after skin evidence"
        route = build_route_decision(manifest, self.catalog)
        self.assertEqual(route["fidelity_tier"], "F3")
        self.assertEqual(route["renderer"], "locked-composite")

    def test_freeform_routes_generative(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["content"] = {
            "type": "illustration_freeform",
            "item_count": 1,
            "text_density": "low",
            "objects": [
                {
                    "id": "shape-1",
                    "type": "illustration",
                    "label": "abstract botanical form",
                    "preserve": "semantic",
                    "evidence": "visual",
                    "verified": True,
                }
            ],
            "text_blocks": [],
            "groups": [],
            "contract": {
                "mode": "open_world",
                "unknown_policy": "block",
                "forbid_undeclared_text": False,
                "allowed_visible_text_ids": [],
                "required_item_count": 1,
                "group_schemas": [],
            },
        }
        manifest["intent"]["exact_text_required"] = False
        manifest["intent"]["target_aspect"] = "square"
        manifest["preservation"]["must_preserve_text_ids"] = []
        manifest["preservation"]["protected_regions"] = []
        route = build_route_decision(manifest, self.catalog)
        self.assertEqual(route["fidelity_tier"], "F0")
        self.assertEqual(route["renderer"], "generative")

    def test_exact_text_comparison_keeps_masked_characters(self) -> None:
        expected = "\n".join(
            block["text"] for block in self.manifest["content"]["text_blocks"]
        )
        report = compare_required_text(self.manifest, expected)
        self.assertTrue(report["pass"])
        missing_report = compare_required_text(self.manifest, expected.replace("可*恩", "可恩"))
        self.assertFalse(missing_report["pass"])
        self.assertTrue(
            any("keen-name" in item["ids"] for item in missing_report["missing"])
        )

    def test_inspect_creates_untrusted_draft(self) -> None:
        png = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "tiny.png"
            image_path.write_bytes(png)
            draft = create_manifest_draft(image_path, ocr="off")
            report = validate_manifest(draft)
            self.assertFalse(report["valid"])
            self.assertTrue(
                any("Blocking uncertainty" in error for error in report["errors"])
            )

    def test_qa_requires_manual_protected_pixel_review(self) -> None:
        route = build_route_decision(self.manifest, self.catalog)
        selection = self._selection(route)
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = write_compiled_artifacts(
                self.manifest, route, selection, self.catalog, Path(temp_dir)
            )
            layout = load_json(outputs["plan"])
            observed = "\n".join(
                block["text"] for block in self.manifest["content"]["text_blocks"]
            )
            report = build_qa_report(
                self.manifest,
                route,
                layout,
                observed_text=observed,
                observed_text_source="provided_text_file",
            )
            self.assertEqual(report["status"], "conditional_pass")
            self.assertFalse(report["protected_pixels_verified"])
            self.assertIsNone(report["integration_check"]["pass"])
            self.assertTrue(
                any("rectangular backgrounds" in item for item in report["manual_checks"])
            )

    def test_compile_requires_matching_human_selection_record(self) -> None:
        route = build_route_decision(self.manifest, self.catalog)
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RecomposerError, "human selection record"):
                write_compiled_artifacts(
                    self.manifest,
                    route,
                    None,
                    self.catalog,
                    Path(temp_dir),
                )
        selection = self._selection(route)
        automated_selection = copy.deepcopy(selection)
        automated_selection["selected_by"] = "auto_opt_in"
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RecomposerError, "selected_by"):
                write_compiled_artifacts(
                    self.manifest,
                    route,
                    automated_selection,
                    self.catalog,
                    Path(temp_dir),
                )
        stale_route = copy.deepcopy(route)
        stale_route["candidates"][0]["embedding_plan"]["text_mode"] = "material-surface"
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RecomposerError, "fingerprint"):
                write_compiled_artifacts(
                    self.manifest,
                    stale_route,
                    selection,
                    self.catalog,
                    Path(temp_dir),
                )
        stale_manifest = copy.deepcopy(self.manifest)
        stale_manifest["source"]["filename"] = "changed-source.png"
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RecomposerError, "manifest digest"):
                write_compiled_artifacts(
                    stale_manifest,
                    route,
                    selection,
                    self.catalog,
                    Path(temp_dir),
                )

    def test_direction_board_is_a_real_human_decision_surface(self) -> None:
        route = build_route_decision(self.manifest, self.catalog)
        board = compile_direction_board(route)
        self.assertIn("# 重构方向", board)
        self.assertIn("请选择一个方向继续", board)
        self.assertIn("最推荐", board)
        self.assertIn("变化最大", board)
        self.assertIn("稳妥易执行", board)
        self.assertEqual(board.count("## 方向"), 6)
        self.assertEqual(board.count("- 方案说明："), 6)
        self.assertEqual(board.count("- 内容边界："), 6)
        self.assertNotIn("candidate_id", board)
        self.assertNotIn("Decision scores", board)

    def test_asset_preparation_plan_forbids_fake_transparency(self) -> None:
        plan = build_asset_preparation_plan(self.manifest, "hybrid")
        self.assertEqual(plan["summary"]["object_count"], 9)
        self.assertEqual(plan["summary"]["requires_preparation_count"], 9)
        for item in plan["items"]:
            self.assertEqual(item["preparation_mode_id"], "segment-protected-edge-band")
            self.assertEqual(item["rectangular_background_policy"], "forbidden")
            self.assertIn("alpha_mask", item["operations"])

    def test_completed_reviews_can_pass_integrated_qa(self) -> None:
        route = build_route_decision(self.manifest, self.catalog)
        selection = self._selection(route)
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = write_compiled_artifacts(
                self.manifest, route, selection, self.catalog, Path(temp_dir)
            )
            observed = "\n".join(
                block["text"] for block in self.manifest["content"]["text_blocks"]
            )
            report = build_qa_report(
                self.manifest,
                route,
                load_json(outputs["plan"]),
                observed_text=observed,
                observed_text_source="provided_text_file",
                observations=self._complete_observations(self.manifest),
                protected_pixels_verified=True,
                visual_review_passed=True,
                integration_review_passed=True,
            )
            self.assertEqual(report["status"], "pass")
            self.assertTrue(report["integration_check"]["pass"])

    def test_closed_world_text_rejects_invented_and_duplicate_regions(self) -> None:
        expected_lines = [
            block["text"] for block in self.manifest["content"]["text_blocks"]
        ]
        invented = compare_required_text(
            self.manifest, "\n".join(expected_lines + ["AI推荐加餐"])
        )
        self.assertFalse(invented["pass"])
        self.assertEqual(invented["undeclared"][0]["text"], "AI推荐加餐")

        duplicated = compare_required_text(
            self.manifest, "\n".join(expected_lines + ["Mythsky"])
        )
        self.assertFalse(duplicated["pass"])
        self.assertTrue(duplicated["duplicate_overages"])

    def test_structured_qa_rejects_missing_product_and_wrong_association(self) -> None:
        observations = self._complete_observations(self.manifest)
        observations["object_regions"] = observations["object_regions"][1:]
        observations["text_regions"][3]["group_id"] = "comparison-node-2"
        report = compare_structured_observations(self.manifest, observations)
        self.assertFalse(report["pass"])
        self.assertFalse(report["object_count_check"]["pass"])
        self.assertFalse(report["association_check"]["pass"])
        self.assertEqual(
            report["object_count_check"]["item_count_mismatch"],
            {"expected": 9, "observed": 8},
        )

    def test_visual_approval_cannot_override_content_failure(self) -> None:
        route = build_route_decision(self.manifest, self.catalog)
        selection = self._selection(route)
        observations = self._complete_observations(self.manifest)
        observations["text_regions"].append(
            {
                "text_id": "invented-benefit",
                "text": "更易吸收",
                "group_id": None,
                "confidence": 0.99,
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = write_compiled_artifacts(
                self.manifest, route, selection, self.catalog, Path(temp_dir)
            )
            report = build_qa_report(
                self.manifest,
                route,
                load_json(outputs["plan"]),
                observations=observations,
                protected_pixels_verified=True,
                visual_review_passed=True,
                integration_review_passed=True,
            )
        self.assertEqual(report["status"], "fail")
        self.assertFalse(report["exact_text_check"]["pass"])

    def test_capacity_gate_rejects_direction_that_cannot_hold_content(self) -> None:
        strategy = copy.deepcopy(self.catalog["strategies"][0])
        strategy["capacity"] = {
            "max_required_text_nodes": 2,
            "max_required_text_chars": 10,
            "max_group_text_chars": 5,
            "max_group_count": 1,
        }
        capacity = assess_strategy_capacity(strategy, self.manifest)
        self.assertFalse(capacity["pass"])
        self.assertTrue(capacity["hard_rejections"])
        self.assertTrue(
            any("exceeds limit" in reason for reason in capacity["hard_rejections"])
        )

    def test_closed_contract_rejects_missing_whitelist_and_group_members(self) -> None:
        missing_whitelist = copy.deepcopy(self.manifest)
        missing_whitelist["content"]["contract"]["allowed_visible_text_ids"].remove(
            "mythsky-dose"
        )
        report = validate_manifest(missing_whitelist)
        self.assertFalse(report["valid"])
        self.assertTrue(any("whitelist" in error for error in report["errors"]))

        missing_group_member = copy.deepcopy(self.manifest)
        missing_group_member["content"]["groups"][0]["member_refs"].remove(
            "mythsky-dose"
        )
        report = validate_manifest(missing_group_member)
        self.assertFalse(report["valid"])
        self.assertTrue(any("text composition" in error for error in report["errors"]))

    def test_multi_product_contract_rejects_extra_or_ungrouped_products(self) -> None:
        extra_product = copy.deepcopy(self.manifest)
        extra_product["content"]["objects"].append(
            {
                "id": "product-extra",
                "type": "product",
                "label": "undeclared comparison item",
                "preserve": "semantic",
                "evidence": "visual",
                "verified": True,
            }
        )
        report = validate_manifest(extra_product)
        self.assertFalse(report["valid"])
        self.assertTrue(
            any("product cardinality" in error for error in report["errors"])
        )
        self.assertTrue(
            any("product-extra" in error for error in report["errors"])
        )

        ungrouped_product = copy.deepcopy(self.manifest)
        ungrouped_product["content"]["groups"][0]["member_refs"].remove(
            "product-mythsky"
        )
        report = validate_manifest(ungrouped_product)
        self.assertFalse(report["valid"])
        self.assertTrue(
            any("product-mythsky" in error for error in report["errors"])
        )


if __name__ == "__main__":
    unittest.main()
