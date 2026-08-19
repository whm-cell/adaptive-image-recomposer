#!/usr/bin/env python3
"""Deterministic helpers for the Adaptive Image Recomposer Skill."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import mimetypes
import re
import shutil
import struct
import subprocess
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SCHEMA_VERSION = "0.1"
CATALOG_VERSION = "0.3"
CONTENT_TYPES = {
    "multi_product_comparison",
    "single_product_poster",
    "dense_infographic",
    "editorial_photo",
    "evidence_comparison",
    "screenshot_ui",
    "illustration_freeform",
    "mixed_unknown",
}
TEXT_DENSITIES = {"low", "medium", "high"}
TARGET_DELTAS = {"conservative", "moderate", "radical"}
RENDER_MODES = {
    "auto",
    "model-led",
    "generative",
    "hybrid",
    "locked-composite",
    "deterministic",
}
OUTCOME_CONTRACTS = {"creative_reconstruction", "audited_content", "pixel_fidelity"}
ITERATION_MODES = {"edit_latest_result", "regenerate_from_source"}
DIRECTION_MODES = {"diverge_then_select", "focused"}
IMAGE_ROLES = {"edit_target", "content_reference", "style_reference", "insert_asset"}
PRESERVE_MODES = {"none", "semantic", "shape", "lock_pixels"}
IMPORTANCE_LEVELS = {"required", "supporting", "decorative"}
EVIDENCE_TYPES = {"visual", "ocr", "user", "source_file"}
UNCERTAINTY_LEVELS = {"info", "warning", "blocking"}
CHANGE_AXES = {
    "aspect_ratio",
    "topology",
    "reading_path",
    "hierarchy",
    "grouping",
    "container_grammar",
    "palette_material",
    "text_image_relationship",
}
ALLOWED_REGION_TRANSFORMS = {
    "crop",
    "scale",
    "translate",
    "frame",
    "alpha_mask",
    "edge_refine",
    "color_decontaminate",
}
ASSET_SOURCE_KINDS = {
    "transparent_original",
    "clean_flat",
    "flattened_crop",
    "unavailable",
}
ASSET_ALPHA_STATES = {"valid", "opaque_background", "needs_segmentation", "unknown"}
ASSET_EDGE_STATES = {"clean", "needs_refinement", "unknown"}
ASSET_BACKGROUND_COMPLEXITIES = {"none", "simple", "complex", "unknown"}
SELECTION_ACTORS = {"human"}


class RecomposerError(RuntimeError):
    """Raised when a deterministic pipeline gate fails."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise RecomposerError(f"JSON file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RecomposerError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RecomposerError(f"Expected a JSON object in {path}")
    return data


def write_json(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jpeg_dimensions(path: Path) -> Tuple[int, int]:
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    with path.open("rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            raise RecomposerError("Not a JPEG file")
        while True:
            prefix = handle.read(1)
            if not prefix:
                break
            if prefix != b"\xff":
                continue
            marker_bytes = handle.read(1)
            while marker_bytes == b"\xff":
                marker_bytes = handle.read(1)
            if not marker_bytes:
                break
            marker = marker_bytes[0]
            if marker in {0xD8, 0xD9}:
                continue
            length_bytes = handle.read(2)
            if len(length_bytes) != 2:
                break
            segment_length = struct.unpack(">H", length_bytes)[0]
            if segment_length < 2:
                raise RecomposerError("Malformed JPEG segment")
            if marker in sof_markers:
                payload = handle.read(5)
                if len(payload) != 5:
                    break
                height, width = struct.unpack(">HH", payload[1:5])
                return width, height
            handle.seek(segment_length - 2, 1)
    raise RecomposerError("Could not find JPEG dimensions")


def _header_dimensions(path: Path) -> Tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(32)
    if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
        return struct.unpack(">II", header[16:24])
    if header[:6] in {b"GIF87a", b"GIF89a"} and len(header) >= 10:
        return struct.unpack("<HH", header[6:10])
    if header.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(path)
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        chunk = header[12:16]
        if chunk == b"VP8X" and len(header) >= 30:
            width = 1 + int.from_bytes(header[24:27], "little")
            height = 1 + int.from_bytes(header[27:30], "little")
            return width, height
        if chunk == b"VP8 " and len(header) >= 30 and header[23:26] == b"\x9d\x01\x2a":
            width, height = struct.unpack("<HH", header[26:30])
            return width & 0x3FFF, height & 0x3FFF
    raise RecomposerError("Unsupported image header")


def image_dimensions(path: Path) -> Tuple[int, int, str]:
    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as image:
            width, height = image.size
            return int(width), int(height), "pillow"
    except (ImportError, OSError):
        pass

    try:
        width, height = _header_dimensions(path)
        return width, height, "header"
    except RecomposerError:
        pass

    sips = shutil.which("sips")
    if sips:
        result = subprocess.run(
            [sips, "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        width_match = re.search(r"pixelWidth:\s*(\d+)", result.stdout)
        height_match = re.search(r"pixelHeight:\s*(\d+)", result.stdout)
        if result.returncode == 0 and width_match and height_match:
            return int(width_match.group(1)), int(height_match.group(1)), "sips"
    raise RecomposerError(f"Cannot determine image dimensions for {path}")


def classify_aspect(width: int, height: int) -> str:
    ratio = width / height
    if ratio >= 1.8:
        return "panoramic"
    if ratio >= 1.12:
        return "landscape"
    if ratio <= 0.82:
        return "portrait"
    return "square"


def parse_target_aspect(value: Any, fallback: str = "portrait") -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    normalized = value.strip().lower()
    if normalized in {"portrait", "landscape", "square", "panoramic"}:
        return normalized
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)\s*", normalized)
    if match:
        width = float(match.group(1))
        height = float(match.group(2))
        if width > 0 and height > 0:
            return classify_aspect(int(width * 1000), int(height * 1000))
    return fallback


def _available_tesseract_languages() -> List[str]:
    executable = shutil.which("tesseract")
    if not executable:
        return []
    result = subprocess.run(
        [executable, "--list-langs"], check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        return []
    lines = [line.strip() for line in result.stdout.splitlines()]
    return [line for line in lines if line and not line.lower().startswith("list of available")]


def _select_ocr_language(requested: str) -> Tuple[Optional[str], List[str]]:
    warnings: List[str] = []
    languages = _available_tesseract_languages()
    if not languages:
        return None, ["Tesseract is unavailable; OCR was not run."]
    if requested not in {"auto", "off"}:
        parts = requested.split("+")
        missing = [part for part in parts if part not in languages]
        if missing:
            return None, [f"Requested OCR language data is unavailable: {', '.join(missing)}"]
        return requested, warnings
    preferred = [language for language in ("chi_sim", "chi_tra", "eng") if language in languages]
    if not preferred:
        preferred = [languages[0]]
    if "eng" in preferred and not any(language.startswith("chi_") for language in preferred):
        warnings.append("Chinese OCR language data is unavailable; CJK text requires visual or manual verification.")
    return "+".join(preferred), warnings


def run_tesseract(path: Path, requested_language: str = "auto") -> Dict[str, Any]:
    if requested_language == "off":
        return {"engine": "off", "language": None, "text_blocks": [], "plain_text": "", "warnings": []}
    executable = shutil.which("tesseract")
    language, warnings = _select_ocr_language(requested_language)
    if not executable or not language:
        return {
            "engine": "unavailable",
            "language": language,
            "text_blocks": [],
            "plain_text": "",
            "warnings": warnings,
        }
    width, height, _ = image_dimensions(path)
    result = subprocess.run(
        [executable, str(path), "stdout", "-l", language, "tsv"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        warnings.append(f"Tesseract failed: {result.stderr.strip() or 'unknown error'}")
        return {
            "engine": "tesseract",
            "language": language,
            "text_blocks": [],
            "plain_text": "",
            "warnings": warnings,
        }

    groups: Dict[Tuple[str, str, str, str], List[Dict[str, Any]]] = {}
    reader = csv.DictReader(io.StringIO(result.stdout), delimiter="\t")
    for row in reader:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            confidence = float(row.get("conf") or -1)
            left = int(row.get("left") or 0)
            top = int(row.get("top") or 0)
            item_width = int(row.get("width") or 0)
            item_height = int(row.get("height") or 0)
        except ValueError:
            continue
        if confidence < 0:
            continue
        key = (
            row.get("page_num") or "0",
            row.get("block_num") or "0",
            row.get("par_num") or "0",
            row.get("line_num") or "0",
        )
        groups.setdefault(key, []).append(
            {
                "text": text,
                "confidence": confidence,
                "left": left,
                "top": top,
                "right": left + item_width,
                "bottom": top + item_height,
            }
        )

    blocks: List[Dict[str, Any]] = []
    for index, words in enumerate(groups.values(), start=1):
        left = min(word["left"] for word in words)
        top = min(word["top"] for word in words)
        right = max(word["right"] for word in words)
        bottom = max(word["bottom"] for word in words)
        text = " ".join(word["text"] for word in words)
        confidence = sum(word["confidence"] for word in words) / (100 * len(words))
        blocks.append(
            {
                "id": f"ocr-line-{index:03d}",
                "text": text,
                "kind": "ocr_candidate",
                "language": "unknown",
                "bbox": [
                    round(left / width, 6),
                    round(top / height, 6),
                    round(right / width, 6),
                    round(bottom / height, 6),
                ],
                "importance": "supporting",
                "lock_exact": False,
                "evidence": "ocr",
                "confidence": round(max(0.0, min(1.0, confidence)), 4),
                "verified": False,
            }
        )
    return {
        "engine": "tesseract",
        "language": language,
        "text_blocks": blocks,
        "plain_text": "\n".join(block["text"] for block in blocks),
        "warnings": warnings,
    }


def create_manifest_draft(image_path: Path, ocr: str = "auto") -> Dict[str, Any]:
    image_path = image_path.expanduser().resolve()
    if not image_path.is_file():
        raise RecomposerError(f"Input image does not exist: {image_path}")
    width, height, dimension_engine = image_dimensions(image_path)
    digest = sha256_file(image_path)
    ocr_result = run_tesseract(image_path, requested_language=ocr)
    block_count = len(ocr_result["text_blocks"])
    density = "high" if block_count >= 18 else "medium" if block_count >= 6 else "low"
    mime, _ = mimetypes.guess_type(str(image_path))
    job_stem = re.sub(r"[^a-zA-Z0-9-]+", "-", image_path.stem).strip("-").lower() or "image"
    job_id = f"{job_stem}-{digest[:8]}"
    uncertainties: List[Dict[str, Any]] = [
        {
            "id": "semantic-inspection-required",
            "field": "content, source_layout, preservation",
            "reason": "Machine inspection cannot verify semantic objects, layout intent, or protected evidence regions.",
            "severity": "blocking",
            "resolution": "View the image, complete the manifest, and remove this uncertainty.",
        }
    ]
    for index, warning in enumerate(ocr_result["warnings"], start=1):
        uncertainties.append(
            {
                "id": f"ocr-warning-{index:02d}",
                "field": "content.text_blocks",
                "reason": warning,
                "severity": "warning",
                "resolution": "Verify required text visually or from an authoritative source.",
            }
        )
    if block_count:
        uncertainties.append(
            {
                "id": "ocr-candidates-unverified",
                "field": "content.text_blocks",
                "reason": "OCR candidates are not verified source copy.",
                "severity": "warning",
                "resolution": "Correct, merge, classify, and verify required text blocks.",
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "created_at": utc_now(),
        "source": {
            "path": str(image_path),
            "role": "edit_target",
            "sha256": digest,
            "mime_type": mime or "application/octet-stream",
            "width": width,
            "height": height,
            "aspect_ratio": round(width / height, 6),
            "aspect_class": classify_aspect(width, height),
            "dimension_engine": dimension_engine,
        },
        "intent": {
            "output_usage": "unspecified",
            "target_delta": "radical",
            "target_aspect": classify_aspect(width, height),
            "exact_text_required": bool(block_count),
            "outcome_contract": "audited_content",
            "direction_mode": "diverge_then_select",
            "direction_count": 6,
        },
        "content": {
            "type": "mixed_unknown",
            "item_count": 0,
            "text_density": density,
            "objects": [],
            "text_blocks": ocr_result["text_blocks"],
            "groups": [],
        },
        "source_layout": {
            "topology": "",
            "reading_path": "",
            "grouping": "",
            "hierarchy": [],
            "containers": [],
            "palette": [],
            "motifs": [],
        },
        "preservation": {
            "must_preserve_text_ids": [],
            "protected_regions": [],
            "forbidden_inference": [],
            "source_features_to_avoid": [],
        },
        "render": {
            "preferred_mode": "auto",
            "iteration_mode": "edit_latest_result",
        },
        "inspection": {
            "ocr_engine": ocr_result["engine"],
            "ocr_language": ocr_result["language"],
            "ocr_plain_text": ocr_result["plain_text"],
        },
        "uncertainties": uncertainties,
    }


def _is_bbox(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    if not all(isinstance(number, (int, float)) and not isinstance(number, bool) for number in value):
        return False
    x1, y1, x2, y2 = (float(number) for number in value)
    return 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1


def _required_object(parent: Dict[str, Any], key: str, errors: List[str]) -> Dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        errors.append(f"{key} must be an object")
        return {}
    return value


def _required_list(parent: Dict[str, Any], key: str, errors: List[str]) -> List[Any]:
    value = parent.get(key)
    if not isinstance(value, list):
        errors.append(f"{key} must be a list")
        return []
    return value


def validate_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(manifest.get("job_id"), str) or not manifest.get("job_id", "").strip():
        errors.append("job_id must be a non-empty string")

    source = _required_object(manifest, "source", errors)
    source_role = source.get("role")
    if source_role not in IMAGE_ROLES:
        errors.append(f"source.role must be one of {sorted(IMAGE_ROLES)}")
    for key in ("width", "height"):
        if not isinstance(source.get(key), int) or source.get(key, 0) <= 0:
            errors.append(f"source.{key} must be a positive integer")
    if not isinstance(source.get("sha256"), str) or len(source.get("sha256", "")) != 64:
        warnings.append("source.sha256 is missing or not a complete SHA-256 digest")

    intent = _required_object(manifest, "intent", errors)
    outcome_contract = intent.get("outcome_contract", "audited_content")
    if outcome_contract not in OUTCOME_CONTRACTS:
        errors.append(f"intent.outcome_contract must be one of {sorted(OUTCOME_CONTRACTS)}")
    if intent.get("target_delta") not in TARGET_DELTAS:
        errors.append(f"intent.target_delta must be one of {sorted(TARGET_DELTAS)}")
    target_aspect = parse_target_aspect(intent.get("target_aspect"), "")
    if target_aspect not in {"portrait", "landscape", "square", "panoramic"}:
        errors.append("intent.target_aspect must be a named aspect or a valid W:H ratio")
    if not isinstance(intent.get("exact_text_required"), bool):
        errors.append("intent.exact_text_required must be true or false")
    if not isinstance(intent.get("output_usage"), str) or not intent.get("output_usage", "").strip():
        errors.append("intent.output_usage must be a non-empty string")
    direction_mode = intent.get("direction_mode", "diverge_then_select")
    if direction_mode not in DIRECTION_MODES:
        errors.append(f"intent.direction_mode must be one of {sorted(DIRECTION_MODES)}")
    direction_count = intent.get("direction_count", 6)
    if (
        not isinstance(direction_count, int)
        or isinstance(direction_count, bool)
        or not 1 <= direction_count <= 12
    ):
        errors.append("intent.direction_count must be an integer from 1 to 12")

    content = _required_object(manifest, "content", errors)
    if content.get("type") not in CONTENT_TYPES:
        errors.append(f"content.type must be one of {sorted(CONTENT_TYPES)}")
    if content.get("text_density") not in TEXT_DENSITIES:
        errors.append(f"content.text_density must be one of {sorted(TEXT_DENSITIES)}")
    if not isinstance(content.get("item_count"), int) or content.get("item_count", -1) < 0:
        errors.append("content.item_count must be a non-negative integer")

    objects = _required_list(content, "objects", errors)
    object_ids: set = set()
    locked_object_ids: List[str] = []
    asset_metadata_count = 0
    for index, item in enumerate(objects):
        prefix = f"content.objects[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif item_id in object_ids:
            errors.append(f"Duplicate object id: {item_id}")
        else:
            object_ids.add(item_id)
        if item.get("preserve") not in PRESERVE_MODES:
            errors.append(f"{prefix}.preserve must be one of {sorted(PRESERVE_MODES)}")
        if item.get("evidence") not in EVIDENCE_TYPES:
            errors.append(f"{prefix}.evidence must be one of {sorted(EVIDENCE_TYPES)}")
        if not isinstance(item.get("verified"), bool):
            errors.append(f"{prefix}.verified must be true or false")
        if item.get("bbox") is not None and not _is_bbox(item.get("bbox")):
            errors.append(f"{prefix}.bbox must be normalized [x1,y1,x2,y2]")
        asset = item.get("asset")
        if asset is not None:
            asset_metadata_count += 1
            if not isinstance(asset, dict):
                errors.append(f"{prefix}.asset must be an object when provided")
            else:
                if asset.get("source_kind") not in ASSET_SOURCE_KINDS:
                    errors.append(
                        f"{prefix}.asset.source_kind must be one of {sorted(ASSET_SOURCE_KINDS)}"
                    )
                if asset.get("alpha_status") not in ASSET_ALPHA_STATES:
                    errors.append(
                        f"{prefix}.asset.alpha_status must be one of {sorted(ASSET_ALPHA_STATES)}"
                    )
                if asset.get("edge_status") not in ASSET_EDGE_STATES:
                    errors.append(
                        f"{prefix}.asset.edge_status must be one of {sorted(ASSET_EDGE_STATES)}"
                    )
                if asset.get("background_complexity", "unknown") not in ASSET_BACKGROUND_COMPLEXITIES:
                    errors.append(
                        f"{prefix}.asset.background_complexity must be one of "
                        f"{sorted(ASSET_BACKGROUND_COMPLEXITIES)}"
                    )
                source_path = asset.get("source_path")
                if source_path is not None and (
                    not isinstance(source_path, str) or not source_path.strip()
                ):
                    errors.append(f"{prefix}.asset.source_path must be a non-empty string when provided")
        if item.get("preserve") == "lock_pixels" and isinstance(item_id, str):
            locked_object_ids.append(item_id)
            if asset is None:
                warnings.append(
                    f"{prefix}.asset is absent; preparation will conservatively infer a flattened crop"
                )

    text_blocks = _required_list(content, "text_blocks", errors)
    text_by_id: Dict[str, Dict[str, Any]] = {}
    for index, block in enumerate(text_blocks):
        prefix = f"content.text_blocks[{index}]"
        if not isinstance(block, dict):
            errors.append(f"{prefix} must be an object")
            continue
        block_id = block.get("id")
        if not isinstance(block_id, str) or not block_id:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif block_id in text_by_id:
            errors.append(f"Duplicate text block id: {block_id}")
        else:
            text_by_id[block_id] = block
        if not isinstance(block.get("text"), str) or not block.get("text", "").strip():
            errors.append(f"{prefix}.text must be a non-empty string")
        if block.get("importance") not in IMPORTANCE_LEVELS:
            errors.append(f"{prefix}.importance must be one of {sorted(IMPORTANCE_LEVELS)}")
        if block.get("evidence") not in EVIDENCE_TYPES:
            errors.append(f"{prefix}.evidence must be one of {sorted(EVIDENCE_TYPES)}")
        if not isinstance(block.get("verified"), bool):
            errors.append(f"{prefix}.verified must be true or false")
        if not isinstance(block.get("lock_exact"), bool):
            errors.append(f"{prefix}.lock_exact must be true or false")
        confidence = block.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            errors.append(f"{prefix}.confidence must be between 0 and 1")
        if block.get("bbox") is not None and not _is_bbox(block.get("bbox")):
            errors.append(f"{prefix}.bbox must be normalized [x1,y1,x2,y2]")

    groups_value = content.get("groups", [])
    groups: List[Any]
    if not isinstance(groups_value, list):
        errors.append("content.groups must be a list")
        groups = []
    else:
        groups = groups_value
    known_refs = object_ids | set(text_by_id)
    group_ids: set = set()
    grouped_refs: Dict[str, str] = {}
    for index, group in enumerate(groups):
        prefix = f"content.groups[{index}]"
        if not isinstance(group, dict):
            errors.append(f"{prefix} must be an object")
            continue
        group_id = group.get("id")
        if not isinstance(group_id, str) or not group_id.strip():
            errors.append(f"{prefix}.id must be a non-empty string")
        elif group_id in group_ids:
            errors.append(f"Duplicate content group id: {group_id}")
        else:
            group_ids.add(group_id)
        if not isinstance(group.get("role"), str) or not group.get("role", "").strip():
            errors.append(f"{prefix}.role must be a non-empty string")
        member_refs = group.get("member_refs")
        if not isinstance(member_refs, list) or not member_refs:
            errors.append(f"{prefix}.member_refs must be a non-empty list")
            continue
        if any(not isinstance(ref, str) or not ref for ref in member_refs):
            errors.append(f"{prefix}.member_refs must contain non-empty strings")
            continue
        if len(member_refs) != len(set(member_refs)):
            errors.append(f"{prefix}.member_refs contains duplicates")
        for ref in member_refs:
            if ref not in known_refs:
                errors.append(f"{prefix} references unknown content id: {ref}")
            elif ref in grouped_refs:
                errors.append(
                    f"Content id {ref} belongs to multiple groups: {grouped_refs[ref]} and {group_id}"
                )
            elif isinstance(group_id, str):
                grouped_refs[ref] = group_id
        sequence = group.get("sequence")
        if sequence is not None and (
            not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1
        ):
            errors.append(f"{prefix}.sequence must be a positive integer when provided")

    source_layout = _required_object(manifest, "source_layout", errors)
    for key in ("topology", "reading_path", "grouping"):
        if not isinstance(source_layout.get(key), str):
            errors.append(f"source_layout.{key} must be a string")
    for key in ("hierarchy", "containers", "palette", "motifs"):
        if not isinstance(source_layout.get(key), list):
            errors.append(f"source_layout.{key} must be a list")

    preservation = _required_object(manifest, "preservation", errors)
    must_preserve = _required_list(preservation, "must_preserve_text_ids", errors)
    if len(must_preserve) != len(set(must_preserve)):
        errors.append("preservation.must_preserve_text_ids contains duplicates")
    for block_id in must_preserve:
        if block_id not in text_by_id:
            errors.append(f"Required text id does not exist: {block_id}")
            continue
        block = text_by_id[block_id]
        if not block.get("verified"):
            errors.append(f"Required text is not verified: {block_id}")
        if not block.get("lock_exact"):
            errors.append(f"Required text must set lock_exact=true: {block_id}")
    for block_id, block in text_by_id.items():
        if block.get("importance") == "required" and block.get("lock_exact") and block_id not in must_preserve:
            warnings.append(f"Exact required text is not listed in must_preserve_text_ids: {block_id}")

    protected_regions = _required_list(preservation, "protected_regions", errors)
    protected_region_ids: set = set()
    for index, region in enumerate(protected_regions):
        prefix = f"preservation.protected_regions[{index}]"
        if not isinstance(region, dict):
            errors.append(f"{prefix} must be an object")
            continue
        region_id = region.get("id")
        if not isinstance(region_id, str) or not region_id:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif region_id in protected_region_ids:
            errors.append(f"Duplicate protected region id: {region_id}")
        else:
            protected_region_ids.add(region_id)
        if not _is_bbox(region.get("bbox")):
            errors.append(f"{prefix}.bbox must be normalized [x1,y1,x2,y2]")
        transforms = region.get("allowed_transforms")
        if not isinstance(transforms, list) or any(value not in ALLOWED_REGION_TRANSFORMS for value in transforms):
            errors.append(
                f"{prefix}.allowed_transforms must use only {sorted(ALLOWED_REGION_TRANSFORMS)}"
            )
        if not isinstance(region.get("reason"), str) or not region.get("reason", "").strip():
            errors.append(f"{prefix}.reason must be a non-empty string")
    if locked_object_ids and not protected_regions:
        warnings.append("Objects are pixel-locked but no protected_regions were defined")

    for key in ("forbidden_inference", "source_features_to_avoid"):
        values = _required_list(preservation, key, errors)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            errors.append(f"preservation.{key} must contain non-empty strings")

    render = _required_object(manifest, "render", errors)
    if render.get("preferred_mode") not in RENDER_MODES:
        errors.append(f"render.preferred_mode must be one of {sorted(RENDER_MODES)}")
    iteration_mode = render.get("iteration_mode", "edit_latest_result")
    if iteration_mode not in ITERATION_MODES:
        errors.append(f"render.iteration_mode must be one of {sorted(ITERATION_MODES)}")

    uncertainties = _required_list(manifest, "uncertainties", errors)
    for index, uncertainty in enumerate(uncertainties):
        prefix = f"uncertainties[{index}]"
        if not isinstance(uncertainty, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if uncertainty.get("severity") not in UNCERTAINTY_LEVELS:
            errors.append(f"{prefix}.severity must be one of {sorted(UNCERTAINTY_LEVELS)}")
        if uncertainty.get("severity") == "blocking":
            errors.append(
                f"Blocking uncertainty {uncertainty.get('id', index)}: {uncertainty.get('reason', 'unspecified')}"
            )

    if intent.get("target_delta") == "radical":
        if not source_layout.get("topology", "").strip():
            errors.append("Radical redesign requires source_layout.topology")
        if not source_layout.get("reading_path", "").strip():
            errors.append("Radical redesign requires source_layout.reading_path")
        if not preservation.get("source_features_to_avoid"):
            errors.append("Radical redesign requires preservation.source_features_to_avoid")

    if intent.get("exact_text_required") and text_blocks and not must_preserve:
        errors.append("exact_text_required=true but no must_preserve_text_ids are defined")

    pixel_locked = bool(locked_object_ids or protected_regions)
    preferred_mode = render.get("preferred_mode")
    if outcome_contract == "creative_reconstruction" and pixel_locked:
        errors.append(
            "creative_reconstruction cannot promise protected or lock_pixels content; "
            "use semantic preservation or choose pixel_fidelity"
        )
    if preferred_mode == "model-led" and pixel_locked:
        errors.append("model-led rendering is incompatible with protected regions or lock_pixels objects")
    if outcome_contract == "pixel_fidelity" and preferred_mode == "model-led":
        errors.append("pixel_fidelity cannot use model-led rendering")
    if (
        outcome_contract == "creative_reconstruction"
        and content.get("item_count", 0) > 1
        and not groups
    ):
        errors.append(
            "creative_reconstruction with multiple items requires content.groups to lock associations"
        )

    stats = {
        "object_count": len(objects),
        "text_block_count": len(text_blocks),
        "required_text_count": len(must_preserve),
        "content_group_count": len(groups),
        "protected_region_count": len(protected_regions),
        "asset_metadata_count": asset_metadata_count,
        "blocking_uncertainty_count": sum(
            1 for item in uncertainties if isinstance(item, dict) and item.get("severity") == "blocking"
        ),
    }
    return {"valid": not errors, "errors": errors, "warnings": warnings, "stats": stats}


def _risk_text(manifest: Dict[str, Any]) -> str:
    pieces: List[str] = []
    pieces.append(str(manifest.get("content", {}).get("type", "")))
    for item in manifest.get("content", {}).get("objects", []):
        if isinstance(item, dict):
            pieces.extend([str(item.get("type", "")), str(item.get("label", ""))])
    for region in manifest.get("preservation", {}).get("protected_regions", []):
        if isinstance(region, dict):
            pieces.append(str(region.get("reason", "")))
    return " ".join(pieces).lower()


def choose_fidelity_tier(manifest: Dict[str, Any]) -> str:
    risk = _risk_text(manifest)
    evidence_markers = {
        "evidence",
        "testimonial",
        "before/after",
        "before-after",
        "face",
        "skin",
        "identity",
        "证据",
        "见证",
        "前后对比",
        "人脸",
        "皮肤",
    }
    if manifest.get("content", {}).get("type") == "evidence_comparison" or any(
        marker in risk for marker in evidence_markers
    ):
        return "F3"
    content = manifest.get("content", {})
    intent = manifest.get("intent", {})
    if (
        content.get("text_density") == "high"
        or content.get("type") in {"dense_infographic", "screenshot_ui", "multi_product_comparison"}
        or intent.get("exact_text_required")
    ):
        return "F2"
    if manifest.get("preservation", {}).get("protected_regions") or any(
        item.get("preserve") == "lock_pixels"
        for item in content.get("objects", [])
        if isinstance(item, dict)
    ):
        return "F1"
    return "F0"


def choose_renderer(manifest: Dict[str, Any]) -> str:
    preferred = manifest.get("render", {}).get("preferred_mode", "auto")
    if preferred != "auto":
        return preferred
    tier = choose_fidelity_tier(manifest)
    content_type = manifest.get("content", {}).get("type")
    outcome_contract = manifest.get("intent", {}).get(
        "outcome_contract", "audited_content"
    )
    protected = bool(manifest.get("preservation", {}).get("protected_regions"))
    pixel_locked = protected or any(
        item.get("preserve") == "lock_pixels"
        for item in manifest.get("content", {}).get("objects", [])
        if isinstance(item, dict)
    )
    if outcome_contract == "pixel_fidelity":
        return "locked-composite"
    if outcome_contract == "creative_reconstruction" and tier != "F3" and not pixel_locked:
        return "model-led"
    if tier == "F3":
        return "locked-composite"
    if content_type in {"dense_infographic", "screenshot_ui"} and not protected:
        return "deterministic"
    if tier in {"F1", "F2"}:
        return "hybrid"
    return "generative"


def load_catalog(path: Path) -> Dict[str, Any]:
    catalog = load_json(path)
    if catalog.get("catalog_version") != CATALOG_VERSION:
        raise RecomposerError(f"Unsupported strategy catalog version in {path}")
    families = catalog.get("families")
    if not isinstance(families, list) or not families:
        raise RecomposerError(f"Strategy catalog has no direction families: {path}")
    visual_systems = catalog.get("visual_systems")
    if not isinstance(visual_systems, list) or not visual_systems:
        raise RecomposerError(f"Strategy catalog has no visual systems: {path}")
    asset_preparation_modes = catalog.get("asset_preparation_modes")
    if not isinstance(asset_preparation_modes, list) or not asset_preparation_modes:
        raise RecomposerError(f"Strategy catalog has no asset preparation modes: {path}")
    embedding_grammars = catalog.get("embedding_grammars")
    if not isinstance(embedding_grammars, dict):
        raise RecomposerError(f"Strategy catalog has no embedding grammars: {path}")
    for grammar_kind in ("product", "text"):
        values = embedding_grammars.get(grammar_kind)
        if not isinstance(values, list) or not values:
            raise RecomposerError(
                f"Strategy catalog embedding_grammars.{grammar_kind} must be a non-empty list"
            )
        ids = [item.get("id") for item in values if isinstance(item, dict)]
        if len(ids) != len(values) or any(not isinstance(item, str) or not item for item in ids):
            raise RecomposerError(
                f"Every {grammar_kind} embedding grammar requires a non-empty id"
            )
        if len(ids) != len(set(ids)):
            raise RecomposerError(f"{grammar_kind} embedding grammar ids must be unique")

    preparation_ids = [
        item.get("id") for item in asset_preparation_modes if isinstance(item, dict)
    ]
    if len(preparation_ids) != len(asset_preparation_modes) or any(
        not isinstance(item, str) or not item for item in preparation_ids
    ):
        raise RecomposerError("Every asset preparation mode requires a non-empty id")
    if len(preparation_ids) != len(set(preparation_ids)):
        raise RecomposerError("Asset preparation mode ids must be unique")

    family_ids = [item.get("id") for item in families if isinstance(item, dict)]
    if len(family_ids) != len(families) or any(not isinstance(item, str) or not item for item in family_ids):
        raise RecomposerError(f"Every direction family requires a non-empty id: {path}")
    if len(family_ids) != len(set(family_ids)):
        raise RecomposerError(f"Direction family ids must be unique: {path}")

    strategies = catalog.get("strategies")
    if strategies is None:
        strategies = []
        for family in families:
            if not isinstance(family, dict):
                continue
            defaults = family.get("defaults", {})
            kernels = family.get("kernels", [])
            if not isinstance(defaults, dict) or not isinstance(kernels, list) or not kernels:
                raise RecomposerError(
                    f"Direction family {family.get('id')} requires defaults and kernels"
                )
            for kernel in kernels:
                if not isinstance(kernel, dict):
                    raise RecomposerError(
                        f"Every kernel in direction family {family.get('id')} must be an object"
                    )
                strategy = dict(defaults)
                strategy.update(kernel)
                strategy["direction_family"] = family["id"]
                strategy.setdefault("leaf", family.get("leaf"))
                strategies.append(strategy)
        catalog["strategies"] = strategies
    if not isinstance(strategies, list) or not strategies:
        raise RecomposerError(f"Strategy catalog has no strategies: {path}")

    strategy_ids: List[str] = []
    for strategy in strategies:
        if not isinstance(strategy, dict):
            raise RecomposerError(f"Every strategy must be an object: {path}")
        strategy_id = strategy.get("id")
        if not isinstance(strategy_id, str) or not strategy_id:
            raise RecomposerError(f"Every strategy requires a non-empty id: {path}")
        strategy_ids.append(strategy_id)
        if strategy.get("direction_family") not in set(family_ids):
            raise RecomposerError(
                f"Strategy {strategy_id} references an unknown direction family"
            )
        for field in (
            "title",
            "leaf",
            "topology_family",
            "reading_path",
            "supports",
            "text_density",
            "item_range",
            "renderers",
            "aspects",
            "changed_axes",
            "prompt_hints",
        ):
            if field not in strategy:
                raise RecomposerError(f"Strategy {strategy_id} is missing {field}")
    if len(strategy_ids) != len(set(strategy_ids)):
        raise RecomposerError(f"Strategy ids must be unique: {path}")

    visual_ids = [
        item.get("id") for item in visual_systems if isinstance(item, dict)
    ]
    if len(visual_ids) != len(visual_systems) or any(
        not isinstance(item, str) or not item for item in visual_ids
    ):
        raise RecomposerError(f"Every visual system requires a non-empty id: {path}")
    if len(visual_ids) != len(set(visual_ids)):
        raise RecomposerError(f"Visual-system ids must be unique: {path}")
    return catalog


def _source_layout_text(manifest: Dict[str, Any]) -> str:
    layout = manifest.get("source_layout", {})
    values: List[str] = []
    for key in ("topology", "reading_path", "grouping"):
        values.append(str(layout.get(key, "")))
    for key in ("hierarchy", "containers", "palette", "motifs"):
        values.extend(str(item) for item in layout.get(key, []) if isinstance(item, (str, int, float)))
    values.extend(str(item) for item in manifest.get("preservation", {}).get("source_features_to_avoid", []))
    return " ".join(values).casefold()


def _strategy_compatibility(
    strategy: Dict[str, Any], manifest: Dict[str, Any], renderer: str
) -> Tuple[Optional[float], List[str], List[str]]:
    reasons: List[str] = []
    risks: List[str] = []
    content = manifest["content"]
    intent = manifest["intent"]
    content_type = content["type"]
    density = content["text_density"]
    item_count = content["item_count"]
    source_aspect = manifest.get("source", {}).get("aspect_class", "portrait")
    target_aspect = parse_target_aspect(intent.get("target_aspect"), source_aspect)
    protected = bool(manifest.get("preservation", {}).get("protected_regions"))

    if content_type not in strategy.get("supports", []):
        return None, [], [f"content type {content_type} is unsupported"]
    if density not in strategy.get("text_density", []):
        return None, [], [f"text density {density} is unsupported"]
    item_range = strategy.get("item_range", [0, 999999])
    if not isinstance(item_range, list) or len(item_range) != 2:
        return None, [], ["strategy item_range is invalid"]
    if item_count < item_range[0] or item_count > item_range[1]:
        return None, [], [f"item count {item_count} is outside {item_range[0]}-{item_range[1]}"]
    if renderer not in strategy.get("renderers", []):
        return None, [], [f"renderer {renderer} is unsupported"]
    if target_aspect not in strategy.get("aspects", []):
        return None, [], [f"target aspect {target_aspect} is unsupported"]
    if protected and not strategy.get("supports_protected_regions", False):
        return None, [], ["protected regions are unsupported"]

    changed_axes = set(strategy.get("changed_axes", []))
    if intent.get("target_delta") == "radical":
        if not {"topology", "reading_path"}.issubset(changed_axes) or len(changed_axes) < 5:
            return None, [], ["strategy does not satisfy the radicality contract"]

    score = 50.0
    score += 20.0
    reasons.append(f"supports {content_type}")
    score += 8.0
    reasons.append(f"supports {density} text density")
    score += 8.0
    reasons.append(f"supports {renderer} rendering")
    score += 8.0
    reasons.append(f"supports {target_aspect} output")
    if protected:
        score += 5.0
        reasons.append("supports protected regions")
    if intent.get("target_delta") == "radical":
        score += min(14.0, len(changed_axes) * 2.0)
        reasons.append(f"changes {len(changed_axes)} radicality axes")
    if target_aspect != source_aspect and "aspect_ratio" in changed_axes:
        score += 8.0
        reasons.append("explicitly exploits the requested aspect-ratio change")

    preferred_content_types = strategy.get("preferred_content_types", [])
    if content_type in preferred_content_types:
        score += 12.0
        reasons.append(f"specialized for {content_type}")
    preferred_aspects = strategy.get("preferred_aspects", [])
    if target_aspect in preferred_aspects:
        score += 8.0
        reasons.append(f"specialized for {target_aspect} output")
    ideal_item_range = strategy.get("ideal_item_range")
    if (
        isinstance(ideal_item_range, list)
        and len(ideal_item_range) == 2
        and ideal_item_range[0] <= item_count <= ideal_item_range[1]
    ):
        score += 10.0
        reasons.append(
            f"item count {item_count} is inside the strategy's ideal range"
        )

    source_text = _source_layout_text(manifest)
    overlap_tokens = [
        token for token in strategy.get("layout_tokens", []) if str(token).casefold() in source_text
    ]
    if overlap_tokens:
        penalty = min(30.0, 10.0 * len(overlap_tokens))
        score -= penalty
        risks.append(f"may echo source layout tokens: {', '.join(overlap_tokens)}")
    else:
        score += 5.0
        reasons.append("no direct source-layout token collision")
    return score, reasons, risks


def _visual_system_compatibility(
    system: Dict[str, Any], manifest: Dict[str, Any], renderer: str
) -> Tuple[Optional[float], List[str], List[str]]:
    content = manifest["content"]
    content_type = content["type"]
    density = content["text_density"]
    reasons: List[str] = []
    risks: List[str] = []
    if content_type not in system.get("supports", []):
        return None, [], [f"content type {content_type} is unsupported"]
    if density not in system.get("text_density", []):
        return None, [], [f"text density {density} is unsupported"]
    if renderer not in system.get("renderers", []):
        return None, [], [f"renderer {renderer} is unsupported"]

    score = 40.0
    reasons.extend(
        [
            f"supports {content_type}",
            f"supports {density} text density",
            f"supports {renderer} rendering",
        ]
    )
    if content_type in system.get("preferred_content_types", []):
        score += 12.0
        reasons.append(f"favored for {content_type}")
    source_text = _source_layout_text(manifest)
    collisions = [
        token
        for token in system.get("style_tokens", [])
        if str(token).casefold() in source_text
    ]
    if collisions:
        score -= min(18.0, 6.0 * len(collisions))
        risks.append(f"may echo source style tokens: {', '.join(collisions)}")
    else:
        score += 4.0
        reasons.append("does not directly repeat the named source style")
    return score, reasons, risks


def _diversified_shortlist(
    candidates: List[Dict[str, Any]], top_k: int
) -> List[Dict[str, Any]]:
    """Cover unused families first, then avoid repeated topology and reading paths."""
    remaining = list(candidates)
    selected: List[Dict[str, Any]] = []
    while remaining and len(selected) < max(1, top_k):
        used_families = {item["direction_family"] for item in selected}
        unused_family_candidates = [
            item
            for item in remaining
            if item["direction_family"] not in used_families
        ]
        pool = unused_family_candidates or remaining

        def adjusted(candidate: Dict[str, Any]) -> Tuple[float, float, str]:
            family_reuse = sum(
                item["direction_family"] == candidate["direction_family"]
                for item in selected
            )
            topology_reuse = sum(
                item["topology_family"] == candidate["topology_family"]
                for item in selected
            )
            reading_reuse = sum(
                item["reading_path"] == candidate["reading_path"]
                for item in selected
            )
            diversity_adjusted = (
                candidate["score"]
                - 28.0 * family_reuse
                - 14.0 * topology_reuse
                - 6.0 * reading_reuse
            )
            return diversity_adjusted, candidate["score"], candidate["id"]

        chosen = max(pool, key=adjusted)
        selected.append(chosen)
        remaining.remove(chosen)
    return selected


def _assign_visual_systems(
    shortlist: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    catalog: Dict[str, Any],
    renderer: str,
) -> None:
    compatible: List[Dict[str, Any]] = []
    for system in catalog.get("visual_systems", []):
        score, reasons, risks = _visual_system_compatibility(system, manifest, renderer)
        if score is None:
            continue
        compatible.append(
            {
                "id": system["id"],
                "title": system["title"],
                "visual_family": system["visual_family"],
                "score": score,
                "prompt_hints": system.get("prompt_hints", []),
                "negative_hints": system.get("negative_hints", []),
                "reasons": reasons,
                "risks": risks,
            }
        )
    if not compatible:
        raise RecomposerError("No compatible visual system for the selected renderer")

    used_ids: Dict[str, int] = {}
    used_families: Dict[str, int] = {}
    for candidate in shortlist:
        strategy = _find_strategy(catalog, candidate["id"])
        affinities = set(strategy.get("visual_affinities", []))

        def adjusted(system: Dict[str, Any]) -> Tuple[float, float, str]:
            affinity_bonus = 10.0 if system["id"] in affinities else 0.0
            reuse_penalty = 20.0 * used_ids.get(system["id"], 0)
            family_penalty = 10.0 * used_families.get(system["visual_family"], 0)
            return (
                system["score"] + affinity_bonus - reuse_penalty - family_penalty,
                system["score"],
                system["id"],
            )

        unused_family_systems = [
            system
            for system in compatible
            if system["visual_family"] not in used_families
        ]
        unused_id_systems = [
            system for system in compatible if system["id"] not in used_ids
        ]
        pool = unused_family_systems or unused_id_systems or compatible
        chosen = max(pool, key=adjusted)
        candidate["visual_system"] = {
            key: value for key, value in chosen.items() if key != "score"
        }
        used_ids[chosen["id"]] = used_ids.get(chosen["id"], 0) + 1
        used_families[chosen["visual_family"]] = (
            used_families.get(chosen["visual_family"], 0) + 1
        )


def _object_asset_metadata(item: Dict[str, Any]) -> Dict[str, Any]:
    asset = item.get("asset")
    if isinstance(asset, dict):
        return {
            "source_path": asset.get("source_path"),
            "source_kind": asset.get("source_kind", "unavailable"),
            "alpha_status": asset.get("alpha_status", "unknown"),
            "edge_status": asset.get("edge_status", "unknown"),
            "background_complexity": asset.get("background_complexity", "unknown"),
            "metadata_source": "manifest",
        }
    if item.get("bbox") is not None:
        return {
            "source_path": None,
            "source_kind": "flattened_crop",
            "alpha_status": "needs_segmentation",
            "edge_status": "needs_refinement",
            "background_complexity": "unknown",
            "metadata_source": "conservative_inference_from_bbox",
        }
    return {
        "source_path": None,
        "source_kind": "unavailable",
        "alpha_status": "unknown",
        "edge_status": "unknown",
        "background_complexity": "unknown",
        "metadata_source": "conservative_inference_no_asset",
    }


def build_asset_preparation_plan(
    manifest: Dict[str, Any], renderer: Optional[str] = None
) -> Dict[str, Any]:
    """Plan transparent, fidelity-aware assets before composition is compiled."""
    active_renderer = renderer or choose_renderer(manifest)
    items: List[Dict[str, Any]] = []
    for item in manifest.get("content", {}).get("objects", []):
        if not isinstance(item, dict) or not item.get("verified"):
            continue
        metadata = _object_asset_metadata(item)
        preserve = item.get("preserve", "semantic")
        source_kind = metadata["source_kind"]
        alpha_status = metadata["alpha_status"]
        if preserve != "lock_pixels" and active_renderer in {"model-led", "generative"}:
            mode = "semantic-resynthesis"
            readiness = "ready_for_semantic_render"
            operations = ["joint_model_render", "identity_audit"]
        elif source_kind == "transparent_original" and alpha_status == "valid":
            mode = "use-transparent-original"
            readiness = "ready_transparent"
            operations = ["scale", "translate", "contact_shadow", "scene_color_match"]
        elif source_kind in {"clean_flat", "flattened_crop"}:
            mode = "segment-protected-edge-band"
            readiness = "requires_preparation"
            operations = [
                "crop",
                "alpha_mask",
                "edge_refine",
                "color_decontaminate",
                "scale",
                "translate",
            ]
        else:
            mode = "framed-source-fallback"
            readiness = "blocked_for_seamless_embedding"
            operations = ["crop", "scale", "translate", "frame"]
        items.append(
            {
                "object_id": item.get("id"),
                "label": item.get("label", item.get("id")),
                "object_type": item.get("type", "object"),
                "preserve": preserve,
                "source_bbox": item.get("bbox"),
                "asset_metadata": metadata,
                "preparation_mode_id": mode,
                "readiness": readiness,
                "operations": operations,
                "protected_core_policy": (
                    "source_pixels_unchanged"
                    if preserve == "lock_pixels"
                    else "semantic_or_shape_contract_applies"
                ),
                "edge_band_policy": (
                    "alpha, edge color, and decontamination may change only in the silhouette edge band"
                    if mode == "segment-protected-edge-band"
                    else "not_applicable"
                ),
                "rectangular_background_policy": (
                    "forbidden"
                    if mode != "framed-source-fallback"
                    else "allowed_only_as_an_explicit_visible_frame"
                ),
            }
        )
    ready_count = sum(
        item["readiness"] in {"ready_transparent", "ready_for_semantic_render"}
        for item in items
    )
    preparation_count = sum(
        item["readiness"] == "requires_preparation" for item in items
    )
    blocked_count = sum(
        item["readiness"] == "blocked_for_seamless_embedding" for item in items
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": manifest["job_id"],
        "generated_at": utc_now(),
        "renderer": active_renderer,
        "items": items,
        "summary": {
            "object_count": len(items),
            "ready_count": ready_count,
            "requires_preparation_count": preparation_count,
            "blocked_count": blocked_count,
            "seamless_embedding_gate": (
                "blocked" if blocked_count else "prepare_then_compose" if preparation_count else "ready"
            ),
        },
        "global_policy": [
            "Remove inherited source backgrounds before layout placement.",
            "Keep protected core pixels separate from the editable silhouette edge band.",
            "Do not fake transparency by feathering a rectangular crop into the new canvas.",
            "Use a visible frame only as an explicit degraded fallback.",
        ],
    }


def _embedding_plan_for_candidate(
    candidate: Dict[str, Any],
    manifest: Dict[str, Any],
    renderer: str,
    asset_plan: Dict[str, Any],
) -> Dict[str, Any]:
    direction_family = candidate["direction_family"]
    topology = candidate["topology_family"]
    blocked = asset_plan["summary"]["blocked_count"] > 0
    if renderer in {"model-led", "generative"}:
        product_mode = "semantic-joint-render"
        text_mode = "joint-typography"
    elif blocked:
        product_mode = "framed-fallback"
        text_mode = "editorial-annotation"
    else:
        topology_text = f"{direction_family} {topology}".casefold()
        if direction_family == "spatial-stage" or any(
            token in topology_text for token in ("shelf", "stage", "depth", "foreground")
        ):
            product_mode = "grounded-stage"
        elif direction_family == "tactile-organic" or any(
            token in topology_text for token in ("tactile", "organic", "fold", "ribbon")
        ):
            product_mode = "material-tuck"
        else:
            product_mode = "transparent-flat"

        if direction_family == "editorial-hierarchy":
            text_mode = "editorial-annotation"
        elif direction_family in {"flow-path", "radial-network", "diagrammatic-data"}:
            text_mode = "contour-rail"
        elif direction_family in {"spatial-stage", "tactile-organic"}:
            text_mode = "material-surface"
        else:
            text_mode = "direct-on-quiet-field"
    preparation_needed = asset_plan["summary"]["requires_preparation_count"] > 0
    return {
        "product_mode": product_mode,
        "text_mode": text_mode,
        "asset_requirement": (
            "explicit_framed_fallback_or_new_asset_required"
            if blocked
            else "prepare_transparent_assets_before_composition"
            if preparation_needed and renderer not in {"model-led", "generative"}
            else "ready_or_semantically_rendered"
        ),
        "joint_node_rule": (
            "Treat each bound object-plus-copy group as one semantic composition node. "
            "Plan object silhouette, type anchor, material interaction, connector, and negative space together."
        ),
        "anti_paste_rule": (
            "No inherited rectangular image background, generic repeated card, detached caption box, "
            "or ungrounded cutout. Match edge color, local light, contact shadow, texture, and overlap logic."
        ),
    }


def _wireframe_for_candidate(candidate: Dict[str, Any]) -> str:
    family = candidate["direction_family"]
    templates = {
        "flow-path": "HERO -> node \\ node -> node \\ node -> close",
        "editorial-hierarchy": "HERO + lead object | staggered story modules | caption rail",
        "modular-comparison": "hero module -> unequal bands -> comparison rail -> footer",
        "radial-network": "entry -> orbiting semantic nodes -> focal core -> exit fact",
        "diagrammatic-data": "legend -> connected nodes/branches -> synthesis point",
        "spatial-stage": "foreground anchor / mid-depth nodes / rear facts / shared ground",
        "typographic-graphic": "headline as structure -> objects locked into type rhythm -> fact trail",
        "tactile-organic": "material gesture -> tucked object nodes -> flowing annotations -> close",
    }
    return templates.get(
        family,
        "hero anchor -> structurally varied semantic nodes -> controlled close",
    )


def _annotate_direction_cards(
    shortlist: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    renderer: str,
    asset_plan: Dict[str, Any],
) -> Dict[str, str]:
    family_boldness = {
        "flow-path": 13,
        "editorial-hierarchy": 7,
        "modular-comparison": 4,
        "radial-network": 14,
        "diagrammatic-data": 8,
        "spatial-stage": 15,
        "typographic-graphic": 16,
        "tactile-organic": 15,
    }
    family_safety = {
        "flow-path": 7,
        "editorial-hierarchy": 14,
        "modular-comparison": 16,
        "radial-network": 3,
        "diagrammatic-data": 13,
        "spatial-stage": 7,
        "typographic-graphic": 5,
        "tactile-organic": 4,
    }
    readiness = asset_plan["summary"]["seamless_embedding_gate"]
    integration_base = {"ready": 94, "prepare_then_compose": 76, "blocked": 38}[readiness]
    density = manifest.get("content", {}).get("text_density", "medium")
    for candidate in shortlist:
        embedding = _embedding_plan_for_candidate(candidate, manifest, renderer, asset_plan)
        candidate["embedding_plan"] = embedding
        candidate["wireframe"] = _wireframe_for_candidate(candidate)
        compatibility = min(100.0, round(float(candidate["score"]) * 0.7, 1))
        text_capacity = 92 if density in {"low", "medium"} else 84
        if candidate["direction_family"] in {
            "editorial-hierarchy",
            "modular-comparison",
            "diagrammatic-data",
        }:
            text_capacity += 5
        boldness = min(
            100,
            48 + len(candidate.get("changed_axes", [])) * 5 + family_boldness.get(candidate["direction_family"], 5),
        )
        safety = min(
            100,
            54 + family_safety.get(candidate["direction_family"], 5) + integration_base * 0.25,
        )
        integration = min(
            100,
            integration_base
            + (7 if embedding["product_mode"] in {"grounded-stage", "material-tuck"} else 0),
        )
        overall = round(
            compatibility * 0.35
            + text_capacity * 0.25
            + integration * 0.25
            + safety * 0.15,
            1,
        )
        candidate["decision_scores"] = {
            "overall": overall,
            "compatibility": compatibility,
            "boldness": round(boldness, 1),
            "production_safety": round(safety, 1),
            "integration_confidence": round(integration, 1),
        }
        candidate["text_capacity"] = (
            "high" if text_capacity >= 88 else "medium" if text_capacity >= 72 else "low"
        )
        candidate["production_risk"] = (
            "high" if safety < 65 else "medium" if safety < 82 else "low"
        )
        candidate["recommendation"] = "alternative"

    recommendations: Dict[str, str] = {}
    remaining = list(shortlist)
    if remaining:
        best = max(remaining, key=lambda item: (item["decision_scores"]["overall"], item["id"]))
        best["recommendation"] = "best_overall"
        recommendations["best_overall"] = best["id"]
        remaining.remove(best)
    if remaining:
        bold = max(remaining, key=lambda item: (item["decision_scores"]["boldness"], item["id"]))
        bold["recommendation"] = "boldest_change"
        recommendations["boldest_change"] = bold["id"]
        remaining.remove(bold)
    if remaining:
        safe = max(
            remaining,
            key=lambda item: (item["decision_scores"]["production_safety"], item["id"]),
        )
        safe["recommendation"] = "safest_production"
        recommendations["safest_production"] = safe["id"]
    return recommendations


def route_fingerprint(route: Dict[str, Any]) -> str:
    payload = {
        "job_id": route.get("job_id"),
        "renderer": route.get("renderer"),
        "outcome_contract": route.get("outcome_contract"),
        "target_aspect": route.get("target_aspect"),
        "candidates": [
            {
                "id": item.get("id"),
                "visual_system_id": item.get("visual_system", {}).get("id"),
                "product_mode": item.get("embedding_plan", {}).get("product_mode"),
                "text_mode": item.get("embedding_plan", {}).get("text_mode"),
            }
            for item in route.get("candidates", [])
            if isinstance(item, dict)
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_selection_record(
    route: Dict[str, Any],
    strategy_id: str,
    selected_by: str = "human",
    rationale: str = "",
) -> Dict[str, Any]:
    if selected_by not in SELECTION_ACTORS:
        raise RecomposerError(f"selected_by must be one of {sorted(SELECTION_ACTORS)}")
    candidate = next(
        (
            item
            for item in route.get("candidates", [])
            if isinstance(item, dict) and item.get("id") == strategy_id
        ),
        None,
    )
    if not candidate:
        raise RecomposerError(f"Strategy {strategy_id} is not in the validated route shortlist")
    stored_fingerprint = route.get("route_fingerprint")
    current_fingerprint = route_fingerprint(route)
    if stored_fingerprint != current_fingerprint:
        raise RecomposerError("Route fingerprint is missing or stale; rebuild the direction board")
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": route.get("job_id"),
        "selected_at": utc_now(),
        "selected_by": selected_by,
        "route_fingerprint": current_fingerprint,
        "selected_strategy_id": strategy_id,
        "selected_visual_system_id": candidate.get("visual_system", {}).get("id"),
        "selected_embedding_plan": candidate.get("embedding_plan"),
        "recommendation_profile": candidate.get("recommendation", "alternative"),
        "rationale": rationale.strip(),
        "workflow_transition": {
            "from": "AWAITING_HUMAN_SELECTION",
            "to": "DIRECTION_SELECTED",
        },
    }


def validate_selection_record(
    route: Dict[str, Any], selection: Dict[str, Any]
) -> Dict[str, Any]:
    if not isinstance(selection, dict):
        raise RecomposerError(
            "Compilation requires an independent human selection record created after route review"
        )
    if route.get("workflow_state") != "AWAITING_HUMAN_SELECTION":
        raise RecomposerError("Route is not at the human selection checkpoint")
    transition = selection.get("workflow_transition", {})
    if transition != {
        "from": "AWAITING_HUMAN_SELECTION",
        "to": "DIRECTION_SELECTED",
    }:
        raise RecomposerError("Selection record has an invalid workflow transition")
    if selection.get("job_id") != route.get("job_id"):
        raise RecomposerError("Selection job_id does not match the route")
    if selection.get("route_fingerprint") != route_fingerprint(route):
        raise RecomposerError("Selection record does not match this route fingerprint")
    strategy_id = selection.get("selected_strategy_id")
    if not isinstance(strategy_id, str):
        raise RecomposerError("Selection record requires selected_strategy_id")
    candidate = next(
        (
            item
            for item in route.get("candidates", [])
            if isinstance(item, dict) and item.get("id") == strategy_id
        ),
        None,
    )
    if not candidate:
        raise RecomposerError(f"Selected strategy {strategy_id} is not in the route shortlist")
    if selection.get("selected_visual_system_id") != candidate.get("visual_system", {}).get("id"):
        raise RecomposerError("Selection visual system does not match the selected route lane")
    if selection.get("selected_by") not in SELECTION_ACTORS:
        raise RecomposerError("Selection record has an invalid selected_by value")
    return candidate


def build_route_decision(
    manifest: Dict[str, Any], catalog: Dict[str, Any], top_k: Optional[int] = None
) -> Dict[str, Any]:
    validation = validate_manifest(manifest)
    if not validation["valid"]:
        raise RecomposerError("Manifest validation failed:\n- " + "\n- ".join(validation["errors"]))
    renderer = choose_renderer(manifest)
    if renderer == "model-led" and choose_fidelity_tier(manifest) == "F3":
        raise RecomposerError(
            "F3 evidence or identity content cannot use model-led rendering; use locked-composite"
        )
    candidates: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for strategy in catalog["strategies"]:
        score, reasons, risks = _strategy_compatibility(strategy, manifest, renderer)
        if score is None:
            rejected.append({"id": strategy.get("id"), "reasons": risks})
            continue
        candidates.append(
            {
                "id": strategy["id"],
                "title": strategy["title"],
                "score": round(score, 2),
                "reference": f"references/strategies/{strategy['leaf']}",
                "direction_family": strategy["direction_family"],
                "topology_family": strategy["topology_family"],
                "reading_path": strategy["reading_path"],
                "changed_axes": strategy["changed_axes"],
                "prompt_hints": strategy.get("prompt_hints", []),
                "reasons": reasons,
                "risks": risks,
            }
        )
    candidates.sort(key=lambda item: (-item["score"], item["id"]))
    if not candidates:
        rejected_summary = "; ".join(
            f"{item['id']}: {', '.join(item['reasons'])}" for item in rejected
        )
        raise RecomposerError(f"No compatible reconstruction strategy. {rejected_summary}")
    requested_count = top_k
    if requested_count is None:
        requested_count = manifest.get("intent", {}).get("direction_count", 6)
    requested_count = max(1, min(12, int(requested_count)))
    direction_mode = manifest.get("intent", {}).get(
        "direction_mode", "diverge_then_select"
    )
    shortlist = (
        _diversified_shortlist(candidates, requested_count)
        if direction_mode == "diverge_then_select"
        else candidates[:requested_count]
    )
    _assign_visual_systems(shortlist, manifest, catalog, renderer)
    asset_plan = build_asset_preparation_plan(manifest, renderer)
    recommendations = _annotate_direction_cards(
        shortlist, manifest, renderer, asset_plan
    )
    unique_direction_families = sorted(
        {item["direction_family"] for item in shortlist}
    )
    unique_topologies = sorted({item["topology_family"] for item in shortlist})
    unique_visual_families = sorted(
        {item["visual_system"]["visual_family"] for item in shortlist}
    )
    route = {
        "schema_version": SCHEMA_VERSION,
        "job_id": manifest["job_id"],
        "generated_at": utc_now(),
        "workflow_state": "AWAITING_HUMAN_SELECTION",
        "fidelity_tier": choose_fidelity_tier(manifest),
        "renderer": renderer,
        "outcome_contract": manifest.get("intent", {}).get(
            "outcome_contract", "audited_content"
        ),
        "target_delta": manifest["intent"]["target_delta"],
        "target_aspect": parse_target_aspect(
            manifest["intent"].get("target_aspect"), manifest.get("source", {}).get("aspect_class", "portrait")
        ),
        "direction_mode": direction_mode,
        "direction_count_requested": requested_count,
        "candidates": [dict(candidate, rank=index) for index, candidate in enumerate(shortlist, start=1)],
        "recommendations": recommendations,
        "asset_readiness_summary": asset_plan["summary"],
        "diversity_summary": {
            "candidate_count": len(shortlist),
            "direction_family_count": len(unique_direction_families),
            "direction_families": unique_direction_families,
            "topology_count": len(unique_topologies),
            "topologies": unique_topologies,
            "visual_family_count": len(unique_visual_families),
            "visual_families": unique_visual_families,
        },
        "rejected": rejected,
        "selection_note": (
            "This is a divergent concept set, not a list of cosmetic variants. The recommendation labels "
            "are decision aids, not an automatic choice. A human selection record is required before compile."
            if direction_mode == "diverge_then_select"
            else "The focused shortlist is a compatibility aid; a human selection record is still required before compile."
        ),
    }
    route["route_fingerprint"] = route_fingerprint(route)
    return route


def _find_strategy(catalog: Dict[str, Any], strategy_id: str) -> Dict[str, Any]:
    for strategy in catalog["strategies"]:
        if strategy.get("id") == strategy_id:
            return strategy
    raise RecomposerError(f"Unknown strategy id: {strategy_id}")


def _required_text_blocks(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    required_ids = set(manifest.get("preservation", {}).get("must_preserve_text_ids", []))
    return [
        block
        for block in manifest.get("content", {}).get("text_blocks", [])
        if isinstance(block, dict) and block.get("id") in required_ids
    ]


def _locked_objects(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        item
        for item in manifest.get("content", {}).get("objects", [])
        if isinstance(item, dict) and item.get("preserve") == "lock_pixels"
    ]


def build_content_graph(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve objects, exact copy, and their non-transferable associations."""
    object_nodes: List[Dict[str, Any]] = []
    text_nodes: List[Dict[str, Any]] = []
    node_by_id: Dict[str, Dict[str, Any]] = {}
    for item in manifest.get("content", {}).get("objects", []):
        if not isinstance(item, dict):
            continue
        node = {
            "id": item.get("id"),
            "node_type": "object",
            "object_type": item.get("type", "object"),
            "label": item.get("label", item.get("id")),
            "preserve": item.get("preserve"),
            "verified": item.get("verified", False),
            "source_bbox": item.get("bbox"),
        }
        object_nodes.append(node)
        if isinstance(node["id"], str):
            node_by_id[node["id"]] = node
    required_ids = set(manifest.get("preservation", {}).get("must_preserve_text_ids", []))
    for block in manifest.get("content", {}).get("text_blocks", []):
        if not isinstance(block, dict):
            continue
        node = {
            "id": block.get("id"),
            "node_type": "text",
            "kind": block.get("kind", "copy"),
            "text": block.get("text"),
            "importance": block.get("importance"),
            "exact": block.get("id") in required_ids,
            "verified": block.get("verified", False),
            "source_bbox": block.get("bbox"),
        }
        text_nodes.append(node)
        if isinstance(node["id"], str):
            node_by_id[node["id"]] = node

    groups: List[Dict[str, Any]] = []
    grouped_refs: set = set()
    source_groups = manifest.get("content", {}).get("groups", [])
    for source_index, group in enumerate(source_groups, start=1):
        if not isinstance(group, dict):
            continue
        refs = [ref for ref in group.get("member_refs", []) if ref in node_by_id]
        grouped_refs.update(refs)
        groups.append(
            {
                "id": group.get("id"),
                "role": group.get("role"),
                "sequence": group.get("sequence", source_index),
                "member_refs": refs,
                "resolved_members": [node_by_id[ref] for ref in refs],
                "association_lock": "members_must_travel_and_render_as_one_semantic_node",
            }
        )
    groups.sort(key=lambda item: (item.get("sequence", 999999), str(item.get("id", ""))))
    all_refs = set(node_by_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": manifest["job_id"],
        "generated_at": utc_now(),
        "outcome_contract": manifest.get("intent", {}).get(
            "outcome_contract", "audited_content"
        ),
        "nodes": {"objects": object_nodes, "text_blocks": text_nodes},
        "groups": groups,
        "ungrouped_refs": sorted(all_refs - grouped_refs),
        "association_policy": [
            "Never move a value, product name, or qualifier to another group.",
            "Sequence controls reading order, not ranking, unless ranking is explicit source content.",
            "Global ungrouped copy may move in the hierarchy but its wording may not change.",
        ],
    }


def build_layout_spec(
    manifest: Dict[str, Any],
    route: Dict[str, Any],
    catalog: Dict[str, Any],
    selection: Dict[str, Any],
) -> Dict[str, Any]:
    selected_candidate = validate_selection_record(route, selection)
    chosen_id = selection["selected_strategy_id"]
    strategy = _find_strategy(catalog, chosen_id)
    visual_system = selected_candidate.get("visual_system")
    if not isinstance(visual_system, dict) or not visual_system.get("id"):
        raise RecomposerError(
            f"Route candidate {chosen_id} has no paired visual system; rebuild the route"
        )
    embedding_plan = selected_candidate.get("embedding_plan")
    if not isinstance(embedding_plan, dict):
        raise RecomposerError(
            f"Route candidate {chosen_id} has no embedding plan; rebuild the route"
        )
    target_delta = manifest["intent"]["target_delta"]
    mandatory_axes = ["topology", "reading_path"] if target_delta == "radical" else []
    renderer = route["renderer"]
    outcome_contract = manifest.get("intent", {}).get(
        "outcome_contract", "audited_content"
    )
    content_graph = build_content_graph(manifest)
    asset_plan = build_asset_preparation_plan(manifest, renderer)
    composition_modes = {
        "model-led": "joint-model-composition",
        "generative": "joint-model-composition",
        "hybrid": "layout-conditioned-hybrid",
        "locked-composite": "locked-integrated-composite",
        "deterministic": "code-native-joint-composition",
    }
    coordinate_status = (
        "model_resolved_then_audited"
        if renderer in {"model-led", "generative"}
        else "joint_scene_layout_engine_resolved"
    )
    authority = {
        "model-led": "whole_canvas_joint_reconstruction",
        "generative": "whole_canvas_joint_generation",
        "hybrid": "layout_conditioned_surfaces_lighting_and_node_integration",
        "locked-composite": "replaceable_surroundings_with_locked_node_integration",
        "deterministic": "code_native_whole_canvas_composition",
    }[renderer]
    if renderer in {"model-led", "generative"}:
        fidelity_claim = "semantic_identity_plus_audited_copy_no_pixel_fidelity"
    elif _locked_objects(manifest) or manifest.get("preservation", {}).get("protected_regions"):
        fidelity_claim = "protected_core_pixels_plus_audited_copy_after_asset_preparation"
    else:
        fidelity_claim = "audited_content_with_joint_scene_geometry"

    joint_nodes: List[Dict[str, Any]] = []
    for group in content_graph["groups"]:
        joint_nodes.append(
            {
                "id": group["id"],
                "sequence": group["sequence"],
                "role": group["role"],
                "member_refs": group["member_refs"],
                "product_embedding": embedding_plan["product_mode"],
                "text_embedding": embedding_plan["text_mode"],
                "geometry_status": coordinate_status,
                "integration_contract": [
                    "plan object silhouette, type anchor, connector, material interaction, and negative space together",
                    "match local light, contact shadow, edge color, grain, and overlap logic",
                    "preserve the group association while changing its spatial expression",
                    "do not place the group inside a generic repeated rectangular card",
                ],
            }
        )
    if content_graph["ungrouped_refs"]:
        joint_nodes.append(
            {
                "id": "global-ungrouped-content",
                "sequence": 0,
                "role": "global_copy_or_unbound_subject",
                "member_refs": content_graph["ungrouped_refs"],
                "product_embedding": embedding_plan["product_mode"],
                "text_embedding": embedding_plan["text_mode"],
                "geometry_status": coordinate_status,
                "integration_contract": [
                    "bind global content to the headline, legend, or conclusion hierarchy",
                    "do not leave content as a floating pasted block",
                ],
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": manifest["job_id"],
        "generated_at": utc_now(),
        "workflow_state": "RENDER_CONTRACT_COMPILED",
        "selection": {
            "route_fingerprint": selection["route_fingerprint"],
            "selected_strategy_id": chosen_id,
            "selected_by": selection["selected_by"],
            "recommendation_profile": selection.get("recommendation_profile"),
            "rationale": selection.get("rationale", ""),
        },
        "strategy": {
            "id": strategy["id"],
            "title": strategy["title"],
            "reference": f"references/strategies/{strategy['leaf']}",
            "direction_family": strategy["direction_family"],
            "topology_family": strategy["topology_family"],
            "reading_path": strategy["reading_path"],
        },
        "visual_system": {
            "id": visual_system["id"],
            "title": visual_system["title"],
            "visual_family": visual_system["visual_family"],
            "prompt_hints": visual_system.get("prompt_hints", []),
            "negative_hints": visual_system.get("negative_hints", []),
        },
        "renderer": renderer,
        "composition_mode": composition_modes[renderer],
        "outcome_contract": outcome_contract,
        "fidelity_claim": fidelity_claim,
        "model_authority": authority,
        "canvas": {
            "target_aspect": route["target_aspect"],
            "output_usage": manifest["intent"]["output_usage"],
        },
        "transformation_contract": {
            "target_delta": target_delta,
            "mandatory_changed_axes": mandatory_axes,
            "changed_axes": strategy["changed_axes"],
            "source_features_to_avoid": manifest["preservation"]["source_features_to_avoid"],
        },
        "visual_direction": {
            "direction_family": strategy["direction_family"],
            "topology_family": strategy["topology_family"],
            "reading_path": strategy["reading_path"],
            "wireframe": selected_candidate.get("wireframe"),
            "structural_prompt_hints": strategy.get("prompt_hints", []),
            "visual_system_id": visual_system["id"],
            "visual_family": visual_system["visual_family"],
            "visual_prompt_hints": visual_system.get("prompt_hints", []),
            "visual_negative_hints": visual_system.get("negative_hints", []),
        },
        "embedding_grammar": embedding_plan,
        "asset_readiness": asset_plan["summary"],
        "joint_nodes": joint_nodes,
        "production_stages": [
            "prepare_or_verify_transparent_assets",
            "solve_composition_kernel_and_all_semantic_nodes_as_one_scene_plan",
            "render_or_construct_shared_surfaces_connectors_lighting_and_negative_space",
            "place_exact_copy_and_protected_assets_inside_the_same_node_geometry",
            "apply_contact_shadows_edge_matching_overlap_and_material_interactions",
            "audit_copy_group_associations_asset_edges_and_structural_delta",
        ],
        "degraded_asset_fallback": {
            "active": asset_plan["summary"]["blocked_count"] > 0,
            "mode": "explicit_visible_frame",
            "policy": (
                "Use only for an individual source object that cannot be isolated safely. Keep the frame "
                "visibly intentional and continue to compose the whole canvas jointly. Background-first "
                "or coordinate-reserved overlay production is not an available workflow."
            ),
        },
        "iteration_policy": {
            "mode": manifest.get("render", {}).get(
                "iteration_mode", "edit_latest_result"
            ),
            "max_targeted_repairs": 2,
            "regenerate_only_when": (
                "the composition kernel fails or repair would require moving several content groups"
            ),
        },
        "coordinate_status": coordinate_status,
    }


def build_production_layer_spec(
    manifest: Dict[str, Any],
    layout_spec: Dict[str, Any],
    asset_plan: Dict[str, Any],
) -> Dict[str, Any]:
    required_ids = set(manifest["preservation"]["must_preserve_text_ids"])
    verified_text = [
        {
            "id": block["id"],
            "text": block["text"],
            "kind": block.get("kind", "copy"),
            "importance": block["importance"],
            "source_bbox": block.get("bbox"),
            "exact": block["id"] in required_ids,
            "placement": (
                "joint_model_typography_then_audit"
                if layout_spec["renderer"] in {"model-led", "generative"}
                else "resolve_inside_joint_semantic_node"
            ),
            "embedding_mode": layout_spec["embedding_grammar"]["text_mode"],
        }
        for block in manifest["content"]["text_blocks"]
        if block.get("verified")
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": manifest["job_id"],
        "strategy_id": layout_spec["strategy"]["id"],
        "renderer": layout_spec["renderer"],
        "composition_mode": layout_spec["composition_mode"],
        "coordinate_status": layout_spec["coordinate_status"],
        "text_blocks": verified_text,
        "prepared_assets": asset_plan["items"],
        "group_bindings": build_content_graph(manifest)["groups"],
        "protected_regions": manifest["preservation"]["protected_regions"],
        "joint_nodes": layout_spec["joint_nodes"],
        "integration_requirements": [
            "calculate the final node geometry before styling isolated layers",
            "remove inherited rectangular backgrounds from every seamlessly embedded asset",
            "match edge color, local light direction, contact shadow, grain, and overlap depth",
            "place exact copy within the same surface or flow grammar as its product",
            "prevent overflow, collisions, haloing, color spill, and detached-caption behavior",
            "use cards or source frames only when the plan explicitly marks a fallback",
        ],
        "fallback_policy": layout_spec["degraded_asset_fallback"],
    }


def _imagegen_use_case(manifest: Dict[str, Any]) -> str:
    content_type = manifest["content"]["type"]
    mapping = {
        "multi_product_comparison": "productivity-visual",
        "single_product_poster": "ads-marketing",
        "dense_infographic": "infographic-diagram",
        "editorial_photo": "photorealistic-natural",
        "evidence_comparison": "productivity-visual",
        "screenshot_ui": "ui-mockup",
        "illustration_freeform": "stylized-concept",
        "mixed_unknown": "stylized-concept",
    }
    return mapping[content_type]


def compile_prompt(
    manifest: Dict[str, Any], route: Dict[str, Any], layout_spec: Dict[str, Any]
) -> str:
    renderer = layout_spec["renderer"]
    required_text = _required_text_blocks(manifest)
    locked_objects = _locked_objects(manifest)
    protected_regions = manifest["preservation"]["protected_regions"]
    strategy = layout_spec["strategy"]
    visual = layout_spec["visual_direction"]
    embedding = layout_spec["embedding_grammar"]
    avoid = manifest["preservation"]["source_features_to_avoid"]
    forbidden_inference = manifest["preservation"]["forbidden_inference"]
    object_labels = [
        item.get("label", item.get("id"))
        for item in manifest["content"]["objects"]
        if item.get("verified")
    ]
    content_graph = build_content_graph(manifest)

    lines = [
        "# Rendering contract",
        "",
        f"Use case: {_imagegen_use_case(manifest)}",
        f"Asset type: {manifest['intent']['output_usage']}",
        f"Input images: Image 1 is the {manifest['source']['role'].replace('_', ' ')} and factual content reference.",
        (
            "Primary request: Recompose the source into a substantially different visual system using "
            f"the selected {strategy['title']} concept lane. Preserve verified information while changing topology and reading path."
        ),
        (
            f"Composition/framing: {route['target_aspect']} canvas; direction family is "
            f"{visual['direction_family']}; structural kernel is {visual['topology_family']}; "
            f"reading path is {visual['reading_path']}."
        ),
        (
            f"Visual system: {layout_spec['visual_system']['title']} "
            f"({layout_spec['visual_system']['visual_family']})."
        ),
        (
            "Concept isolation: execute only this selected structural kernel and its paired visual system. "
            "Do not blend, average, or borrow composition logic from the other shortlisted lanes."
        ),
        (
            f"Embedding grammar: products use {embedding['product_mode']}; text uses "
            f"{embedding['text_mode']}; asset readiness is {embedding['asset_requirement']}."
        ),
        (
            "Joint-scene rule: solve the final geometry of each product, its exact copy, local surface, "
            "connector, negative space, overlap, edge treatment, and contact shadow together. This is not "
            "an empty-background-first workflow."
        ),
        (
            "Anti-paste rule: remove inherited rectangular source backgrounds; do not use generic repeated "
            "cards or detached caption boxes. Match local light, edge color, grain, scale, depth, and overlap "
            "so each semantic node belongs to the same scene."
        ),
    ]
    if object_labels:
        lines.append("Subject: " + "; ".join(str(label) for label in object_labels))
    lines.append("Structural directions:")
    lines.extend(f"- {hint}" for hint in visual.get("structural_prompt_hints", []))
    lines.append("Visual-system directions:")
    lines.extend(f"- {hint}" for hint in visual.get("visual_prompt_hints", []))
    if visual.get("visual_negative_hints"):
        lines.append(
            "Visual-system exclusions: "
            + "; ".join(visual["visual_negative_hints"])
            + "."
        )

    lines.append("Bound semantic nodes:")
    for group in content_graph["groups"]:
        member_descriptions: List[str] = []
        for member in group["resolved_members"]:
            if member["node_type"] == "object":
                member_descriptions.append(
                    f"object {member.get('label', member.get('id'))}"
                )
            else:
                exact_label = "exact text" if member.get("exact") else "text"
                member_descriptions.append(
                    f'{exact_label} "{member.get("text", "")}"'
                )
        lines.append(
            f"- Node {group['sequence']} [{group['id']}]: "
            + "; ".join(member_descriptions)
        )
    grouped_refs = {
        ref for group in content_graph["groups"] for ref in group["member_refs"]
    }
    global_exact = [
        block for block in required_text if block.get("id") not in grouped_refs
    ]
    if global_exact:
        lines.append(
            "Global exact copy: "
            + " | ".join(f'"{block["text"]}"' for block in global_exact)
        )

    if renderer in {"model-led", "generative"}:
        lines.extend(
            [
                "Rendering mode: model-led whole-canvas joint reconstruction.",
                (
                    "This is not a background-only pass. Design the headline, dominant composition "
                    "kernel, all item nodes, typography, decorative shapes, texture, and whitespace "
                    "together as one finished poster."
                ),
                (
                    "Object policy: preserve each verified product's semantic identity, silhouette, "
                    "dominant colors, and recognizable front-label cues from the source, but allow "
                    "visual resynthesis. Do not claim that source label pixels or microcopy are unchanged."
                ),
                (
                    "Association policy: every group below is indivisible. Its product, name, values, "
                    "and qualifiers must remain together even when nodes alternate across the composition."
                ),
                (
                    "Text constraints: render every exact text node once in its assigned semantic "
                    "location; duplicate surface strings remain separate nodes; add no invented copy."
                ),
                (
                    "Completion criterion: return one fully composed, presentation-ready poster—not "
                    "a wireframe, background plate, empty template, or collection of loose assets."
                ),
            ]
        )
    elif renderer == "hybrid":
        lines.extend(
            [
                "Rendering mode: layout-conditioned hybrid joint composition.",
                (
                    "Resolve the composition kernel and every semantic node before rendering. Generate "
                    "surfaces, lighting, connectors, material interactions, and decorative structure around "
                    "the final node geometry—not as a standalone empty backdrop."
                ),
                (
                    "Place prepared transparent protected assets and exact typography inside those same "
                    "nodes. Deterministic placement is allowed for fidelity, but it must participate in the "
                    "shared surface, overlap, shadow, and reading-flow grammar."
                ),
                (
                    "Do not redraw locked labels, faces, evidence, or protected core pixels. Editable alpha "
                    "and edge correction are limited to the declared silhouette edge band."
                ),
            ]
        )
    elif renderer == "locked-composite":
        lines.extend(
            [
                "Rendering mode: locked integrated composite.",
                (
                    "Resolve all node geometry first, then construct replaceable surroundings, shared "
                    "surfaces, lighting, connectors, and typography around the protected cores."
                ),
                (
                    "Prepared assets keep protected internal pixels and proportions unchanged. Blend only "
                    "through valid alpha, permitted edge-band cleanup, contact shadows, occlusion, and scene "
                    "color matching; never feather an opaque rectangle into the canvas."
                ),
            ]
        )
    else:
        lines.extend(
            [
                "Rendering mode: deterministic code-native whole-canvas composition.",
                (
                    "Use HTML, SVG, canvas, or the project's layout engine to solve final node geometry, "
                    "typography, prepared transparent assets, shared surfaces, connectors, occlusion, and "
                    "contact shadows as one composition."
                ),
                (
                    "Do not implement this as background generation followed by coordinate-reserved text or "
                    "rectangular image overlays. Decorative bitmap material may be generated only as part of "
                    "the already-solved joint scene."
                ),
            ]
        )

    constraints: List[str] = []
    if locked_objects:
        constraints.append("keep locked object pixels unchanged: " + ", ".join(item["id"] for item in locked_objects))
    if protected_regions:
        constraints.append("obey every protected-region transform allowance in production-layer-spec.json")
    if required_text:
        constraints.append("use only the exact copy bound above and audit it against production-layer-spec.json")
    constraints.append("do not invent brands, claims, labels, fine print, objects, or data")
    constraints.append("change topology and reading path; this must not be a recolor or background swap")
    lines.append("Constraints: " + "; ".join(constraints) + ".")
    if avoid:
        lines.append("Avoid source features: " + "; ".join(avoid) + ".")
    if forbidden_inference:
        lines.append("Never infer: " + "; ".join(forbidden_inference) + ".")
    if renderer in {"model-led", "generative"}:
        lines.extend(
            [
                (
                    "Output intent: a polished, fully composed reconstruction suitable for the named "
                    "asset use, with no watermark."
                ),
                "",
                "# Audit and repair contract",
                "",
                f"Renderer: {renderer}",
                f"Strategy leaf: {strategy['reference']}",
                "After rendering, audit every exact text node, object count, and group association.",
                (
                    "For a local defect, edit the latest result and correct only that defect while "
                    "preserving the successful composition. Allow at most two targeted repairs before "
                    "escalating copy or protected content to a deterministic production pass."
                ),
            ]
        )
    else:
        lines.extend(
            [
                (
                    "Output intent: a polished, fully integrated reconstruction suitable for the named "
                    "asset use, with no inherited crop rectangles, detached content blocks, or watermark."
                ),
                "",
                "# Joint production handoff",
                "",
                f"Renderer: {renderer}",
                f"Strategy leaf: {strategy['reference']}",
                "Exact copy, prepared assets, group bindings, and integration rules are defined in production-layer-spec.json.",
                (
                    "Final node geometry must be calculated as a whole scene and checked for overflow, "
                    "collisions, alpha halos, detached captions, inconsistent light, and pasted-card artifacts."
                ),
            ]
        )
    return "\n".join(lines) + "\n"


def compile_retry_guide(
    manifest: Dict[str, Any], route: Dict[str, Any], layout_spec: Dict[str, Any]
) -> str:
    renderer = route["renderer"]
    lines = [
        "# Targeted repair guide",
        "",
        f"Renderer: {renderer}",
        f"Strategy: {layout_spec['strategy']['id']}",
        f"Direction family: {layout_spec['strategy']['direction_family']}",
        f"Visual system: {layout_spec['visual_system']['id']}",
        "",
    ]
    if renderer not in {"model-led", "generative"}:
        lines.extend(
            [
                (
                    "Repair one joint semantic node at a time in the production layer: copy, geometry, "
                    "alpha edge, contact shadow, overlap, surface binding, or association."
                ),
                "Do not regenerate source-locked pixels to solve a local defect.",
                (
                    "Do not retreat to an opaque rectangle, detached caption, generic card, or empty "
                    "background plus overlay when repairing integration."
                ),
            ]
        )
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            "Use the latest generated image as the edit target. Name one defect per repair.",
            "Freeze the selected direction family, composition kernel, visual system, successful node positions, palette, material, and hierarchy unless the named defect requires a local move.",
            "Repair examples:",
            "- Replace one incorrect exact string inside its existing semantic node.",
            "- Restore one missing product and keep all other nodes fixed.",
            "- Move one colliding node locally without reverting to a grid.",
            "- Correct one product-to-value association without changing the rest of the poster.",
            "",
            "Stop after two targeted model repairs. Escalate to hybrid or deterministic production when exact text, microcopy, or protected pixels still fail.",
        ]
    )
    return "\n".join(lines) + "\n"


def compile_direction_board(route: Dict[str, Any]) -> str:
    """Render the divergent shortlist as comparable concept lanes before selection."""
    recommendations = route.get("recommendations", {})
    lines = [
        "# Reconstruction direction board",
        "",
        f"Workflow state: `{route.get('workflow_state', 'unknown')}`",
        f"Mode: {route.get('direction_mode', 'focused')}",
        f"Renderer: {route.get('renderer', 'unknown')}",
        f"Route fingerprint: `{route.get('route_fingerprint', 'unknown')}`",
        (
            "Human checkpoint: compare structural difference, information capacity, embedding grammar, "
            "and fidelity risk. Select exactly one lane; recommendation labels are decision aids and never "
            "authorize automatic compilation."
        ),
        "",
        "## Recommendation map",
        "",
        f"- Best overall: `{recommendations.get('best_overall', 'not_assigned')}`",
        f"- Boldest change: `{recommendations.get('boldest_change', 'not_assigned')}`",
        f"- Safest production: `{recommendations.get('safest_production', 'not_assigned')}`",
        "",
    ]
    for candidate in route.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        visual = candidate.get("visual_system", {})
        embedding = candidate.get("embedding_plan", {})
        scores = candidate.get("decision_scores", {})
        lines.extend(
            [
                f"## Lane {candidate.get('rank', '?')}: {candidate.get('title', candidate.get('id', 'unknown'))}",
                "",
                f"- Recommendation: `{candidate.get('recommendation', 'alternative')}`",
                f"- Kernel id: `{candidate.get('id', 'unknown')}`",
                f"- Direction family: `{candidate.get('direction_family', 'unknown')}`",
                f"- Topology: `{candidate.get('topology_family', 'unknown')}`",
                f"- Reading path: `{candidate.get('reading_path', 'unknown')}`",
                f"- Visual system: `{visual.get('id', 'unknown')}` ({visual.get('visual_family', 'unknown')})",
                f"- Wireframe: `{candidate.get('wireframe', 'not_available')}`",
                f"- Changed axes: {', '.join(candidate.get('changed_axes', [])) or 'none'}",
                f"- Product embedding: `{embedding.get('product_mode', 'unknown')}`",
                f"- Text embedding: `{embedding.get('text_mode', 'unknown')}`",
                f"- Asset gate: `{embedding.get('asset_requirement', 'unknown')}`",
                f"- Text capacity: `{candidate.get('text_capacity', 'unknown')}`",
                f"- Production risk: `{candidate.get('production_risk', 'unknown')}`",
                (
                    "- Decision scores: "
                    f"overall {scores.get('overall', 'unknown')} / "
                    f"compatibility {scores.get('compatibility', 'unknown')} / "
                    f"boldness {scores.get('boldness', 'unknown')} / "
                    f"safety {scores.get('production_safety', 'unknown')} / "
                    f"integration {scores.get('integration_confidence', 'unknown')}"
                ),
            ]
        )
        reasons = candidate.get("reasons", [])
        risks = candidate.get("risks", []) + visual.get("risks", [])
        if reasons:
            lines.append("- Why it fits: " + "; ".join(reasons))
        if risks:
            lines.append("- Risks: " + "; ".join(risks))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_compiled_artifacts(
    manifest: Dict[str, Any],
    route: Dict[str, Any],
    selection: Dict[str, Any],
    catalog: Dict[str, Any],
    out_dir: Path,
) -> Dict[str, Path]:
    validation = validate_manifest(manifest)
    if not validation["valid"]:
        raise RecomposerError("Manifest validation failed:\n- " + "\n- ".join(validation["errors"]))
    layout_spec = build_layout_spec(manifest, route, catalog, selection)
    content_graph = build_content_graph(manifest)
    asset_plan = build_asset_preparation_plan(manifest, layout_spec["renderer"])
    production_layers = build_production_layer_spec(manifest, layout_spec, asset_plan)
    prompt = compile_prompt(manifest, route, layout_spec)
    retry_guide = compile_retry_guide(manifest, route, layout_spec)
    direction_board = compile_direction_board(route)
    out_dir.mkdir(parents=True, exist_ok=True)
    selection_path = out_dir / "selection-record.json"
    graph_path = out_dir / "content-graph.json"
    asset_path = out_dir / "asset-preparation-plan.json"
    plan_path = out_dir / "reconstruction-plan.json"
    production_path = out_dir / "production-layer-spec.json"
    prompt_path = out_dir / "final-prompt.md"
    retry_path = out_dir / "retry-guide.md"
    board_path = out_dir / "direction-board.md"
    write_json(selection, selection_path)
    write_json(content_graph, graph_path)
    write_json(asset_plan, asset_path)
    write_json(layout_spec, plan_path)
    write_json(production_layers, production_path)
    with prompt_path.open("w", encoding="utf-8") as handle:
        handle.write(prompt)
    with retry_path.open("w", encoding="utf-8") as handle:
        handle.write(retry_guide)
    with board_path.open("w", encoding="utf-8") as handle:
        handle.write(direction_board)
    return {
        "selection": selection_path,
        "content_graph": graph_path,
        "asset_plan": asset_path,
        "plan": plan_path,
        "production_layers": production_path,
        "prompt": prompt_path,
        "retry": retry_path,
        "direction_board": board_path,
    }


def normalize_exact_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", "", normalized)


def compare_required_text(manifest: Dict[str, Any], observed_text: str) -> Dict[str, Any]:
    normalized_observed = normalize_exact_text(observed_text)
    expected = _required_text_blocks(manifest)
    matches: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    for block in expected:
        item = {"id": block["id"], "text": block["text"]}
        if normalize_exact_text(block["text"]) in normalized_observed:
            matches.append(item)
        else:
            missing.append(item)
    return {
        "evaluated": True,
        "expected_count": len(expected),
        "matched_count": len(matches),
        "matched": matches,
        "missing": missing,
        "pass": not missing,
    }


def score_layout_delta(manifest: Dict[str, Any], layout_spec: Dict[str, Any]) -> Dict[str, Any]:
    contract = layout_spec.get("transformation_contract", {})
    changed_axes = set(contract.get("changed_axes", []))
    unknown_axes = sorted(changed_axes - CHANGE_AXES)
    target_delta = manifest.get("intent", {}).get("target_delta")
    required_count = 5 if target_delta == "radical" else 3 if target_delta == "moderate" else 0
    mandatory = {"topology", "reading_path"} if target_delta == "radical" else set()
    missing_mandatory = sorted(mandatory - changed_axes)
    return {
        "target_delta": target_delta,
        "changed_axes": sorted(changed_axes),
        "changed_axis_count": len(changed_axes),
        "score": round(len(changed_axes & CHANGE_AXES) / len(CHANGE_AXES), 4),
        "required_axis_count": required_count,
        "missing_mandatory_axes": missing_mandatory,
        "unknown_axes": unknown_axes,
        "pass": len(changed_axes & CHANGE_AXES) >= required_count and not missing_mandatory and not unknown_axes,
    }


def build_qa_report(
    manifest: Dict[str, Any],
    route: Dict[str, Any],
    layout_spec: Dict[str, Any],
    result_image: Optional[Path] = None,
    observed_text: Optional[str] = None,
    observed_text_source: Optional[str] = None,
    protected_pixels_verified: bool = False,
    visual_review_passed: bool = False,
    integration_review_passed: bool = False,
) -> Dict[str, Any]:
    validation = validate_manifest(manifest)
    layout_delta = score_layout_delta(manifest, layout_spec)
    result: Dict[str, Any] = {"provided": False}
    ocr_notes: List[str] = []
    if result_image:
        result_image = result_image.expanduser().resolve()
        if not result_image.is_file():
            raise RecomposerError(f"Result image does not exist: {result_image}")
        width, height, engine = image_dimensions(result_image)
        result = {
            "provided": True,
            "path": str(result_image),
            "sha256": sha256_file(result_image),
            "width": width,
            "height": height,
            "aspect_class": classify_aspect(width, height),
            "dimension_engine": engine,
        }
        if observed_text is None:
            ocr = run_tesseract(result_image, "auto")
            observed_text = ocr["plain_text"]
            observed_text_source = "automatic_tesseract"
            ocr_notes.extend(ocr["warnings"])

    if observed_text is None:
        text_check = {
            "evaluated": False,
            "pass": None,
            "reason": "No result OCR or independently extracted text was provided.",
        }
    else:
        text_check = compare_required_text(manifest, observed_text)
        text_check["source"] = observed_text_source or "provided"
        if observed_text_source == "automatic_tesseract" and text_check["missing"]:
            text_check["pass"] = None
            text_check["reason"] = "Automatic OCR misses are candidates for manual review, not proof of absent text."

    manual_checks: List[str] = []
    content_groups = manifest.get("content", {}).get("groups", [])
    association_check = {
        "group_count": len(content_groups) if isinstance(content_groups, list) else 0,
        "evaluated": visual_review_passed,
        "pass": True if visual_review_passed else None,
        "method": "manual_visual_review" if visual_review_passed else None,
    }
    integration_check = {
        "evaluated": integration_review_passed,
        "pass": True if integration_review_passed else None,
        "method": "manual_integration_review" if integration_review_passed else None,
        "criteria": [
            "no inherited opaque crop rectangles or accidental halos",
            "product edges match local color and texture without background spill",
            "objects have credible contact shadows, occlusion, scale, and shared light direction",
            "copy belongs to the same surface or flow grammar as its paired object",
            "semantic nodes do not collapse into generic repeated cards or detached captions",
        ],
    }
    if not protected_pixels_verified and manifest["preservation"]["protected_regions"]:
        manual_checks.append("Verify protected pixels against the source or compositing layers.")
    if content_groups and not visual_review_passed:
        manual_checks.append(
            "Verify that every product, name, value, and qualifier remains inside its declared content group."
        )
    if not integration_review_passed:
        manual_checks.extend(
            [
                "Confirm prepared product assets have no inherited rectangular backgrounds, alpha halos, or source-background color spill.",
                "Confirm product edges, local light, contact shadows, grain, scale, occlusion, and overlap belong to the new scene.",
                "Confirm each product and its copy form one semantic node rather than a pasted image plus detached text block.",
                "Confirm generic repeated cards or frames appear only where the selected direction explicitly requires them.",
            ]
        )
    if route.get("renderer") == "model-led" and not visual_review_passed:
        manual_checks.extend(
            [
                "Confirm every verified object is present once and remains semantically recognizable.",
                "Confirm the dominant composition kernel remains visible and the result has not collapsed into a grid.",
                "Treat bottle-label microcopy and internal pixels as resynthesized, not source-verified evidence.",
            ]
        )
    if not visual_review_passed:
        manual_checks.extend(
            [
                "Inspect reading order, hierarchy, overflow, collisions, and target-size legibility.",
                "Confirm every source feature in source_features_to_avoid is absent.",
                "Confirm the result is not merely a recolor, decoration pass, or background swap.",
            ]
        )

    failures: List[str] = []
    if not validation["valid"]:
        failures.append("Source manifest is invalid.")
    if not layout_delta["pass"]:
        failures.append("Layout delta does not satisfy the requested transformation contract.")
    if text_check.get("pass") is False and text_check.get("source") != "automatic_tesseract":
        failures.append("Independently provided result text is missing required exact copy.")
    if result.get("provided") and result.get("aspect_class") != route.get("target_aspect"):
        failures.append(
            f"Result aspect class {result.get('aspect_class')} does not match target {route.get('target_aspect')}."
        )

    if failures:
        status = "fail"
    elif manual_checks or text_check.get("pass") is not True:
        status = "conditional_pass"
    else:
        status = "pass"
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": manifest["job_id"],
        "generated_at": utc_now(),
        "status": status,
        "renderer": route.get("renderer"),
        "outcome_contract": route.get(
            "outcome_contract",
            manifest.get("intent", {}).get("outcome_contract", "audited_content"),
        ),
        "fidelity_claim": layout_spec.get("fidelity_claim"),
        "strategy_id": layout_spec.get("strategy", {}).get("id"),
        "manifest_validation": validation,
        "layout_delta": layout_delta,
        "result_image": result,
        "exact_text_check": text_check,
        "association_check": association_check,
        "integration_check": integration_check,
        "ocr_notes": ocr_notes,
        "protected_pixels_verified": protected_pixels_verified,
        "visual_review_passed": visual_review_passed,
        "integration_review_passed": integration_review_passed,
        "manual_checks": manual_checks,
        "failures": failures,
    }
