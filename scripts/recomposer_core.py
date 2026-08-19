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
CATALOG_VERSION = "0.2"
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
ALLOWED_REGION_TRANSFORMS = {"crop", "scale", "translate", "frame"}


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
        if item.get("preserve") == "lock_pixels" and isinstance(item_id, str):
            locked_object_ids.append(item_id)

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
    unique_direction_families = sorted(
        {item["direction_family"] for item in shortlist}
    )
    unique_topologies = sorted({item["topology_family"] for item in shortlist})
    unique_visual_families = sorted(
        {item["visual_system"]["visual_family"] for item in shortlist}
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": manifest["job_id"],
        "generated_at": utc_now(),
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
        "selected_strategy_id": shortlist[0]["id"],
        "candidates": [dict(candidate, rank=index) for index, candidate in enumerate(shortlist, start=1)],
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
            "This is a divergent concept set, not a list of cosmetic variants. Visually compare all lanes, "
            "then compile exactly one structural kernel plus its paired visual system."
            if direction_mode == "diverge_then_select"
            else "The focused shortlist is a compatibility aid; visually review the selected leaf before rendering."
        ),
    }


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
    manifest: Dict[str, Any], route: Dict[str, Any], catalog: Dict[str, Any], strategy_id: Optional[str] = None
) -> Dict[str, Any]:
    chosen_id = strategy_id or route.get("selected_strategy_id")
    if not isinstance(chosen_id, str):
        raise RecomposerError("Route decision does not contain selected_strategy_id")
    candidate_ids = {candidate.get("id") for candidate in route.get("candidates", []) if isinstance(candidate, dict)}
    if strategy_id and strategy_id not in candidate_ids:
        raise RecomposerError(f"Strategy {strategy_id} is not in the validated route shortlist")
    strategy = _find_strategy(catalog, chosen_id)
    selected_candidate = next(
        (
            candidate
            for candidate in route.get("candidates", [])
            if isinstance(candidate, dict) and candidate.get("id") == chosen_id
        ),
        None,
    )
    if not selected_candidate:
        raise RecomposerError(f"Strategy {chosen_id} is not present in the route shortlist")
    visual_system = selected_candidate.get("visual_system")
    if not isinstance(visual_system, dict) or not visual_system.get("id"):
        raise RecomposerError(
            f"Route candidate {chosen_id} has no paired visual system; rebuild the route"
        )
    target_delta = manifest["intent"]["target_delta"]
    mandatory_axes = ["topology", "reading_path"] if target_delta == "radical" else []
    locked_objects = _locked_objects(manifest)
    required_text = _required_text_blocks(manifest)
    renderer = route["renderer"]
    outcome_contract = manifest.get("intent", {}).get(
        "outcome_contract", "audited_content"
    )
    content_graph = build_content_graph(manifest)
    if renderer == "model-led":
        zones: List[Dict[str, Any]] = [
            {
                "id": "whole-canvas-joint-reconstruction",
                "role": "joint_model_render",
                "content_refs": [group["id"] for group in content_graph["groups"]],
                "geometry_status": "model_resolved_at_render_time",
                "intent": (
                    "Generate title, composition kernel, semantic item nodes, typography, "
                    "decorative forms, material, and negative space as one coordinated poster."
                ),
            }
        ]
        coordinate_status = "model_resolved_at_render_time"
        model_authority = "whole_canvas_joint_reconstruction"
        fidelity_claim = "semantic_identity_plus_audited_copy_no_pixel_fidelity"
    else:
        zones = [
            {
                "id": "generated-visual-field",
                "role": "generated_backdrop",
                "content_refs": [],
                "geometry_status": "intent_only",
                "intent": "Provide the non-critical visual field and reserved negative space for overlays.",
            }
        ]
        if locked_objects or manifest.get("preservation", {}).get("protected_regions"):
            zones.append(
                {
                    "id": "protected-inserts",
                    "role": "locked_inserts",
                    "content_refs": [item["id"] for item in locked_objects],
                    "geometry_status": "requires_layout_engine",
                    "intent": "Composite protected assets without modifying internal pixels.",
                }
            )
        if required_text:
            zones.append(
                {
                    "id": "exact-copy-overlay",
                    "role": "deterministic_overlay",
                    "content_refs": [block["id"] for block in required_text],
                    "geometry_status": "requires_layout_engine",
                    "intent": "Place verified copy with deterministic typography and collision checks.",
                }
            )
        coordinate_status = "intent_only_requires_layout_engine"
        model_authority = "replaceable_visual_field_only"
        fidelity_claim = (
            "protected_pixels_when_verified_plus_deterministic_exact_copy"
            if locked_objects or manifest.get("preservation", {}).get("protected_regions")
            else "audited_content_with_deterministic_geometry"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": manifest["job_id"],
        "generated_at": utc_now(),
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
        "outcome_contract": outcome_contract,
        "fidelity_claim": fidelity_claim,
        "model_authority": model_authority,
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
            "structural_prompt_hints": strategy.get("prompt_hints", []),
            "visual_system_id": visual_system["id"],
            "visual_family": visual_system["visual_family"],
            "visual_prompt_hints": visual_system.get("prompt_hints", []),
            "visual_negative_hints": visual_system.get("negative_hints", []),
        },
        "model_workflow": (
            [
                "perceive_source_roles_and_verified_content",
                "bind_objects_and_copy_into_content_groups",
                "suppress_source_layout_grammar",
                "select_one_dominant_composition_kernel",
                "solve_the_whole_canvas_jointly",
                "semantically_resynthesize_visual_objects",
                "audit_copy_counts_and_group_associations",
                "edit_the_latest_result_for_one_targeted_defect",
            ]
            if renderer == "model-led"
            else []
        ),
        "iteration_policy": {
            "mode": manifest.get("render", {}).get(
                "iteration_mode", "edit_latest_result"
            ),
            "max_targeted_repairs": 2,
            "regenerate_only_when": (
                "the composition kernel fails or repair would require moving several content groups"
            ),
        },
        "zones": zones,
        "coordinate_status": coordinate_status,
    }


def build_overlay_spec(manifest: Dict[str, Any], layout_spec: Dict[str, Any]) -> Dict[str, Any]:
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
                "model_to_resolve_then_audit"
                if layout_spec["renderer"] == "model-led"
                else "layout_engine_to_resolve"
            ),
        }
        for block in manifest["content"]["text_blocks"]
        if block.get("verified")
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": manifest["job_id"],
        "strategy_id": layout_spec["strategy"]["id"],
        "renderer": layout_spec["renderer"],
        "coordinate_status": (
            "model_resolved_then_audited"
            if layout_spec["renderer"] == "model-led"
            else "unresolved"
        ),
        "text_blocks": verified_text,
        "group_bindings": build_content_graph(manifest)["groups"],
        "protected_regions": manifest["preservation"]["protected_regions"],
        "locked_objects": _locked_objects(manifest),
        "layout_engine_requirements": (
            [
                "audit exact copy after rendering",
                "audit product-to-value group associations",
                "escalate to deterministic overlays after two failed targeted repairs",
            ]
            if layout_spec["renderer"] == "model-led"
            else [
                "calculate final coordinates",
                "prevent overflow and collisions",
                "preserve exact copy",
                "apply only allowed protected-region transforms",
            ]
        ),
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
    renderer = route["renderer"]
    required_text = _required_text_blocks(manifest)
    locked_objects = _locked_objects(manifest)
    protected_regions = manifest["preservation"]["protected_regions"]
    strategy = layout_spec["strategy"]
    visual = layout_spec["visual_direction"]
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

    if renderer == "model-led":
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
                "Bound semantic nodes:",
            ]
        )
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
                        f'{exact_label} \"{member.get("text", "")}\"'
                    )
            lines.append(
                f"- Node {group['sequence']} [{group['id']}]: "
                + "; ".join(member_descriptions)
            )
        grouped_refs = {
            ref for group in content_graph["groups"] for ref in group["member_refs"]
        }
        global_exact = [
            block
            for block in required_text
            if block.get("id") not in grouped_refs
        ]
        if global_exact:
            lines.append(
                "Global exact copy: "
                + " | ".join(f'\"{block["text"]}\"' for block in global_exact)
            )
        lines.extend(
            [
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
    elif renderer == "generative":
        if required_text:
            lines.append("Text (verbatim): " + " | ".join(f'\"{block["text"]}\"' for block in required_text))
            lines.append("Text constraints: render each text node in its intended context; no extra text.")
        else:
            lines.append("Text: no text unless explicitly provided by the user.")
    elif renderer == "hybrid":
        lines.extend(
            [
                "Rendering mode: hybrid backdrop generation.",
                "Text: render no readable text; reserve clean zones for deterministic overlays.",
                "Protected assets: treat locked products or evidence as later insert layers; do not redraw labels, faces, or protected pixels.",
            ]
        )
    elif renderer == "locked-composite":
        lines.extend(
            [
                "Rendering mode: locked composite.",
                "Generate only replaceable surroundings, frames, surfaces, lighting, and connectors.",
                "Protected assets are inserts, not style references; keep internal pixels and proportions unchanged.",
                "Text: render no new readable text; use the deterministic overlay specification.",
            ]
        )
    else:
        lines.extend(
            [
                "Rendering mode: deterministic code-native layout.",
                "Build final typography, containers, coordinates, and overlays in HTML, SVG, canvas, or the project's layout engine.",
                "If decorative bitmap assets are generated, create them separately with no text.",
            ]
        )

    constraints: List[str] = []
    if locked_objects:
        constraints.append("keep locked object pixels unchanged: " + ", ".join(item["id"] for item in locked_objects))
    if protected_regions:
        constraints.append("obey every protected-region transform allowance in overlay-spec.json")
    if required_text:
        constraints.append(
            "use only the exact copy bound above and audit it against overlay-spec.json"
            if renderer == "model-led"
            else "source exact copy only from overlay-spec.json"
        )
    constraints.append("do not invent brands, claims, labels, fine print, objects, or data")
    constraints.append("change topology and reading path; this must not be a recolor or background swap")
    lines.append("Constraints: " + "; ".join(constraints) + ".")
    if avoid:
        lines.append("Avoid source features: " + "; ".join(avoid) + ".")
    if forbidden_inference:
        lines.append("Never infer: " + "; ".join(forbidden_inference) + ".")
    if renderer == "model-led":
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
                "Output intent: a polished reconstruction suitable for the named asset use, with clearly reserved overlay zones and no watermark.",
                "",
                "# Deterministic handoff",
                "",
                f"Renderer: {renderer}",
                f"Strategy leaf: {strategy['reference']}",
                "Exact copy and protected inserts are defined in overlay-spec.json.",
                "Final coordinates must be calculated by a layout engine and checked for overflow and collisions.",
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
    if renderer != "model-led":
        lines.extend(
            [
                "Repair copy, coordinates, collisions, and protected inserts in the deterministic production layer.",
                "Do not regenerate source-locked pixels to solve a local defect.",
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
    lines = [
        "# Reconstruction direction board",
        "",
        f"Mode: {route.get('direction_mode', 'focused')}",
        f"Renderer: {route.get('renderer', 'unknown')}",
        (
            "Selection rule: compare structural difference first, then visual-system fit and "
            "fidelity risk. Compile exactly one lane; do not merge lanes."
        ),
        "",
    ]
    for candidate in route.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        visual = candidate.get("visual_system", {})
        lines.extend(
            [
                f"## Lane {candidate.get('rank', '?')}: {candidate.get('title', candidate.get('id', 'unknown'))}",
                "",
                f"- Kernel id: `{candidate.get('id', 'unknown')}`",
                f"- Direction family: `{candidate.get('direction_family', 'unknown')}`",
                f"- Topology: `{candidate.get('topology_family', 'unknown')}`",
                f"- Reading path: `{candidate.get('reading_path', 'unknown')}`",
                f"- Visual system: `{visual.get('id', 'unknown')}` ({visual.get('visual_family', 'unknown')})",
                f"- Compatibility score: {candidate.get('score', 'unknown')}",
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
    manifest: Dict[str, Any], route: Dict[str, Any], catalog: Dict[str, Any], out_dir: Path, strategy_id: Optional[str] = None
) -> Dict[str, Path]:
    validation = validate_manifest(manifest)
    if not validation["valid"]:
        raise RecomposerError("Manifest validation failed:\n- " + "\n- ".join(validation["errors"]))
    layout_spec = build_layout_spec(manifest, route, catalog, strategy_id=strategy_id)
    content_graph = build_content_graph(manifest)
    overlay_spec = build_overlay_spec(manifest, layout_spec)
    prompt = compile_prompt(manifest, route, layout_spec)
    retry_guide = compile_retry_guide(manifest, route, layout_spec)
    direction_board = compile_direction_board(route)
    out_dir.mkdir(parents=True, exist_ok=True)
    graph_path = out_dir / "content-graph.json"
    plan_path = out_dir / "reconstruction-plan.json"
    layout_path = out_dir / "layout-spec.json"
    overlay_path = out_dir / "overlay-spec.json"
    prompt_path = out_dir / "final-prompt.md"
    retry_path = out_dir / "retry-guide.md"
    board_path = out_dir / "direction-board.md"
    write_json(content_graph, graph_path)
    write_json(layout_spec, plan_path)
    # Compatibility artifact for existing callers; reconstruction-plan.json is canonical.
    write_json(layout_spec, layout_path)
    write_json(overlay_spec, overlay_path)
    with prompt_path.open("w", encoding="utf-8") as handle:
        handle.write(prompt)
    with retry_path.open("w", encoding="utf-8") as handle:
        handle.write(retry_guide)
    with board_path.open("w", encoding="utf-8") as handle:
        handle.write(direction_board)
    return {
        "content_graph": graph_path,
        "plan": plan_path,
        "layout": layout_path,
        "overlay": overlay_path,
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
    if not protected_pixels_verified and manifest["preservation"]["protected_regions"]:
        manual_checks.append("Verify protected pixels against the source or compositing layers.")
    if content_groups and not visual_review_passed:
        manual_checks.append(
            "Verify that every product, name, value, and qualifier remains inside its declared content group."
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
        "ocr_notes": ocr_notes,
        "protected_pixels_verified": protected_pixels_verified,
        "visual_review_passed": visual_review_passed,
        "manual_checks": manual_checks,
        "failures": failures,
    }
