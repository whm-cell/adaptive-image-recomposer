# Source manifest

The source manifest is the factual boundary for the reconstruction. It is not a creative brief. Complete it before selecting a visual strategy.

## Provenance states

Every text block and critical object must identify its evidence:

- `visual`: directly legible in the source image.
- `ocr`: proposed by OCR and not yet manually confirmed.
- `user`: supplied explicitly by the user.
- `source_file`: read from an authoritative layered or structured source.

Set `verified: true` only after the value is legible or authoritative. Never verify a guess because it looks plausible.

## Required top-level fields

```json
{
  "schema_version": "0.2",
  "job_id": "stable-job-id",
  "source": {
    "path": "/absolute/path/image.png",
    "role": "edit_target",
    "sha256": "...",
    "width": 1080,
    "height": 1440,
    "aspect_ratio": 0.75
  },
  "intent": {
    "output_usage": "social poster",
    "target_delta": "radical",
    "target_aspect": "portrait",
    "exact_text_required": true,
    "outcome_contract": "creative_reconstruction",
    "direction_mode": "diverge_then_select",
    "direction_count": 6
  },
  "content": {
    "type": "multi_product_comparison",
    "item_count": 9,
    "text_density": "high",
    "objects": [],
    "text_blocks": [],
    "groups": [],
    "contract": {
      "mode": "closed_world",
      "unknown_policy": "block",
      "forbid_undeclared_text": true,
      "allowed_visible_text_ids": [],
      "required_item_count": 9,
      "group_schemas": []
    }
  },
  "source_layout": {
    "topology": "split background with card grid",
    "reading_path": "top-to-bottom row scan",
    "grouping": "2+3+4 product rows",
    "hierarchy": ["headline", "products", "data cards", "footnote"],
    "containers": ["speech bubbles", "white rounded data cards"],
    "palette": ["pale yellow", "pink", "black", "orange"],
    "motifs": ["green stars"]
  },
  "preservation": {
    "must_preserve_text_ids": [],
    "protected_regions": [],
    "forbidden_inference": [],
    "source_features_to_avoid": []
  },
  "render": {
    "preferred_mode": "auto",
    "iteration_mode": "edit_latest_result"
  },
  "uncertainties": []
}
```

## Objects

Each `content.objects` entry uses:

```json
{
  "id": "product-01",
  "type": "product",
  "label": "verified display name",
  "bbox": [0.31, 0.15, 0.44, 0.32],
  "preserve": "lock_pixels",
  "evidence": "visual",
  "verified": true,
  "asset": {
    "source_path": "/absolute/path/product-01.png",
    "source_kind": "transparent_original",
    "alpha_status": "valid",
    "edge_status": "clean",
    "background_complexity": "none"
  }
}
```

Bounding boxes are normalized `[x1, y1, x2, y2]` in the range 0–1. Allowed `preserve` values are `none`, `semantic`, `shape`, and `lock_pixels`.

The optional `asset` block makes seamless integration auditable:

- `source_kind`: `transparent_original`, `clean_flat`, `flattened_crop`, or `unavailable`;
- `alpha_status`: `valid`, `opaque_background`, `needs_segmentation`, or `unknown`;
- `edge_status`: `clean`, `needs_refinement`, or `unknown`;
- `background_complexity`: `none`, `simple`, `complex`, or `unknown`;
- `source_path`: an absolute path when an independent asset exists.

If `asset` is absent but `bbox` exists, the planner conservatively treats the object as a flattened crop that needs segmentation. Do not mark a crop as a transparent original merely because its visible background is white.

## Text blocks

```json
{
  "id": "item-01-dose",
  "text": "含量400mg",
  "kind": "data",
  "language": "zh-Hans",
  "bbox": [0.31, 0.33, 0.47, 0.37],
  "importance": "required",
  "lock_exact": true,
  "evidence": "visual",
  "confidence": 1.0,
  "verified": true
}
```

`importance` is `required`, `supporting`, or `decorative`. Required exact text must be verified and listed in `must_preserve_text_ids`.

## Content groups

Groups preserve relationships while the composition changes. They are required for model-led multi-item work.

```json
{
  "id": "item-mythsky",
  "role": "comparison_item",
  "member_refs": [
    "product-01",
    "item-01-name",
    "item-01-dose",
    "item-01-combination"
  ],
  "sequence": 1
}
```

Every `member_refs` value must resolve to an object or text-block ID. Keep a name, its numbers, qualifiers, and product in the same group; do not depend on source proximity. A title, legend, or footnote may use its own group role.

## Protected regions

```json
{
  "id": "product-01-label",
  "bbox": [0.34, 0.19, 0.43, 0.29],
  "reason": "product label must not be regenerated",
  "allowed_transforms": [
    "crop",
    "scale",
    "translate",
    "alpha_mask",
    "edge_refine",
    "color_decontaminate"
  ]
}
```

Allowed transforms are `crop`, `scale`, `translate`, `frame`, `alpha_mask`, `edge_refine`, and `color_decontaminate`. For a protected object, masking, edge refinement, and color decontamination may affect only the silhouette edge band; the protected core remains unchanged. If a protected region cannot be isolated from a flattened asset, record that limitation in `uncertainties` and use an explicit visible frame or request a clean asset. Do not claim pixel fidelity that the available source cannot support.

## Closed content contract

Use `closed_world` whenever exact copy is required or the image compares multiple items. `allowed_visible_text_ids` is the complete visible-text whitelist, not merely a required-text list. Every required ID must be present, verified, and exact. `forbid_undeclared_text` must be true. `required_item_count` must equal `content.item_count`.

Declare the shape of every repeated semantic group:

```json
{
  "role": "comparison_item",
  "required_count": 9,
  "required_object_types": {"product": 1},
  "required_text_kinds": {"item_name": 1, "data": 2}
}
```

Validation rejects a missing group, extra group, or wrong member composition before routing. For `multi_product_comparison`, declared product cardinality must equal `content.item_count`, and every product must belong to exactly one schema-bound comparison group. Optional `cardinality` on an object or text block is a positive integer and is used by validation, capacity routing, prompting, and QA. Do not create extra nodes to make a layout look full.

Choose one unknown-value policy:

- `block`: stop until the value is verified;
- `explicit_missing`: show only a verified missing-value literal whose text ID is whitelisted;
- `omit_dimension`: omit a declared text kind consistently and list it in `omitted_text_kinds`.

Never allow a generator to guess an unknown value. `open_world` is reserved for low-risk freeform work without an exact-copy obligation.

## Uncertainties and blocking rules

```json
{
  "id": "uncertain-label-01",
  "field": "content.objects[0].label_microcopy",
  "reason": "blurred in source",
  "severity": "blocking",
  "resolution": "request clean product source or omit microcopy"
}
```

Allowed severity values are `info`, `warning`, and `blocking`. Rendering must stop when a blocking uncertainty affects required text, object identity, evidence, or protected pixels.

## Supported routing values

`content.type`:

- `multi_product_comparison`
- `single_product_poster`
- `dense_infographic`
- `editorial_photo`
- `evidence_comparison`
- `screenshot_ui`
- `illustration_freeform`
- `mixed_unknown`

`text_density`: `low`, `medium`, or `high`.

`intent.target_delta`: `conservative`, `moderate`, or `radical`.

`intent.outcome_contract`:

- `creative_reconstruction`: allow whole-canvas semantic resynthesis and audit the result.
- `audited_content`: require exact content and independent treatment of critical assets.
- `pixel_fidelity`: require protected-source compositing evidence.

`intent.direction_mode`:

- `diverge_then_select`: explore structurally different families before compiling one lane. This is the default.
- `focused`: return the highest-scoring compatible lanes without diversity reranking; use only after a direction has already been narrowed.

`intent.direction_count` is an integer from 1 to 12. The default is 6. It controls the direction board, not the number of concepts blended into one prompt.

`render.preferred_mode`: `auto`, `model-led`, `generative`, `hybrid`, `locked-composite`, or `deterministic`.

`render.iteration_mode`: `edit_latest_result` or `regenerate_from_source`. Prefer `edit_latest_result` after a composition succeeds so a repair does not discard the whole design.
