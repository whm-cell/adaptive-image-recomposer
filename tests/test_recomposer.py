#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from recomposer_core import (  # noqa: E402
    RecomposerError,
    build_qa_report,
    build_route_decision,
    compare_required_text,
    create_manifest_draft,
    load_catalog,
    load_json,
    validate_manifest,
    write_compiled_artifacts,
)


FIXTURE = ROOT / "tests" / "fixtures" / "multi-product-comparison.json"
CATALOG = ROOT / "references" / "strategies" / "catalog.json"


class RecomposerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_json(FIXTURE)
        self.catalog = load_catalog(CATALOG)

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

    def test_fixture_is_valid(self) -> None:
        report = validate_manifest(self.manifest)
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["stats"]["object_count"], 9)
        self.assertEqual(report["stats"]["required_text_count"], 31)

    def test_catalog_is_broad_and_has_no_sample_specific_route(self) -> None:
        strategy_ids = [item["id"] for item in self.catalog["strategies"]]
        self.assertEqual(len(self.catalog["families"]), 8)
        self.assertEqual(len(strategy_ids), 32)
        self.assertEqual(len(self.catalog["visual_systems"]), 12)
        self.assertNotIn("portrait-serpentine-comparison", strategy_ids)
        self.assertNotIn("editorial-s-curve", strategy_ids)
        self.assertEqual(
            [strategy_id for strategy_id in strategy_ids if "serpentine" in strategy_id],
            ["serpentine-flow"],
        )

    def test_high_density_product_comparison_routes_diverse_hybrid_lanes(self) -> None:
        route = build_route_decision(self.manifest, self.catalog)
        self.assertEqual(route["fidelity_tier"], "F2")
        self.assertEqual(route["renderer"], "hybrid")
        self.assertEqual(route["direction_mode"], "diverge_then_select")
        self.assertEqual(len(route["candidates"]), 6)
        self.assertGreaterEqual(route["diversity_summary"]["direction_family_count"], 6)
        self.assertEqual(route["diversity_summary"]["topology_count"], 6)
        self.assertGreaterEqual(route["diversity_summary"]["visual_family_count"], 5)
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
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = write_compiled_artifacts(
                self.manifest, route, self.catalog, Path(temp_dir)
            )
            prompt = outputs["prompt"].read_text(encoding="utf-8")
            board = outputs["direction_board"].read_text(encoding="utf-8")
            overlay = json.loads(outputs["overlay"].read_text(encoding="utf-8"))
            layout = json.loads(outputs["layout"].read_text(encoding="utf-8"))
            self.assertIn("render no readable text", prompt)
            self.assertIn("Concept isolation:", prompt)
            self.assertIn("Visual system:", prompt)
            self.assertEqual(board.count("## Lane "), 6)
            for candidate in route["candidates"]:
                self.assertIn(candidate["id"], board)
            for candidate in route["candidates"][1:]:
                self.assertNotIn(candidate["id"], prompt)
            self.assertEqual(len(overlay["text_blocks"]), 31)
            self.assertIn("direction_family", layout["strategy"])
            self.assertIn("id", layout["visual_system"])
            self.assertIn("topology", layout["transformation_contract"]["changed_axes"])
            self.assertIn("reading_path", layout["transformation_contract"]["changed_axes"])

    def test_compile_can_select_any_validated_lane_without_blending(self) -> None:
        route = build_route_decision(self.manifest, self.catalog)
        selected_id = route["candidates"][-1]["id"]
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = write_compiled_artifacts(
                self.manifest,
                route,
                self.catalog,
                Path(temp_dir),
                strategy_id=selected_id,
            )
            prompt = outputs["prompt"].read_text(encoding="utf-8")
            layout = json.loads(outputs["layout"].read_text(encoding="utf-8"))
            self.assertEqual(layout["strategy"]["id"], selected_id)
            self.assertIn("Concept isolation:", prompt)
            for candidate in route["candidates"]:
                if candidate["id"] != selected_id:
                    self.assertNotIn(candidate["id"], prompt)

    def test_creative_portrait_comparison_routes_diverse_model_led_lanes(self) -> None:
        manifest = self._creative_portrait_manifest()
        validation = validate_manifest(manifest)
        self.assertTrue(validation["valid"], validation["errors"])
        route = build_route_decision(manifest, self.catalog)
        self.assertEqual(route["fidelity_tier"], "F2")
        self.assertEqual(route["outcome_contract"], "creative_reconstruction")
        self.assertEqual(route["renderer"], "model-led")
        self.assertEqual(len(route["candidates"]), 6)
        self.assertGreaterEqual(
            route["diversity_summary"]["direction_family_count"], 6
        )
        self.assertEqual(route["diversity_summary"]["topology_count"], 6)
        self.assertNotIn(
            "portrait-serpentine-comparison",
            [candidate["id"] for candidate in route["candidates"]],
        )

    def test_model_led_compile_is_whole_canvas_and_group_bound(self) -> None:
        manifest = self._creative_portrait_manifest()
        route = build_route_decision(manifest, self.catalog)
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = write_compiled_artifacts(
                manifest, route, self.catalog, Path(temp_dir)
            )
            prompt = outputs["prompt"].read_text(encoding="utf-8")
            plan = json.loads(outputs["plan"].read_text(encoding="utf-8"))
            graph = json.loads(outputs["content_graph"].read_text(encoding="utf-8"))
            overlay = json.loads(outputs["overlay"].read_text(encoding="utf-8"))
            retry = outputs["retry"].read_text(encoding="utf-8")
            board = outputs["direction_board"].read_text(encoding="utf-8")
            self.assertIn("model-led whole-canvas joint reconstruction", prompt)
            self.assertIn("not a background-only pass", prompt)
            self.assertIn("Concept isolation:", prompt)
            self.assertIn("Node 1 [comparison-node-1]", prompt)
            self.assertNotIn("# Deterministic handoff", prompt)
            self.assertEqual(
                plan["coordinate_status"], "model_resolved_at_render_time"
            )
            self.assertEqual(len(graph["groups"]), 9)
            self.assertEqual(len(overlay["group_bindings"]), 9)
            self.assertEqual(board.count("## Lane "), 6)
            self.assertIn("Stop after two targeted model repairs", retry)

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
            "item_count": 3,
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
        self.assertIn("keen-name", [item["id"] for item in missing_report["missing"]])

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
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = write_compiled_artifacts(
                self.manifest, route, self.catalog, Path(temp_dir)
            )
            layout = load_json(outputs["layout"])
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


if __name__ == "__main__":
    unittest.main()
