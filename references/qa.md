# Reconstruction QA

Scripts can prove file facts and enforce a structured content contract; visual review is still required for appearance and integration. The two evidence types are independent.

## Content fidelity

- Every required verified string appears exactly once unless deliberate repetition is specified.
- Numbers, decimals, units, punctuation, asterisks, and footnotes match the manifest.
- Object and product counts match.
- No unverified brand, claim, fine print, or decorative copy was invented.
- Every item keeps its own name, values, qualifiers, and product association. Correct strings attached to the wrong item fail.

Run two text comparisons: required text must be contained in observed text, and observed text must be contained in the declared whitelist. Count occurrences, so duplicated allowed-looking copy still fails when it exceeds cardinality. OCR is supporting evidence, not sole proof. Normalize whitespace for comparison, but do not normalize away meaningful punctuation, units, decimals, or masked characters.

## Structured observations

For a production pass, provide `result-observations.json`:

```json
{
  "text_regions": [
    {"text_id": "item-01-dose", "text": "含量400mg", "group_id": "item-01", "confidence": 0.99}
  ],
  "object_regions": [
    {"object_id": "product-01", "group_id": "item-01", "confidence": 0.99}
  ]
}
```

One record represents one independently segmented visible occurrence. Optional normalized `bbox` values provide audit evidence. The QA gate checks literal text, whitelist membership, duplicate and missing occurrences, object cardinality, total product count, and the expected `group_id` for every stable node ID. Unknown IDs fail in a closed world. Low-confidence observations remain conditional until reviewed.

Flat `--ocr-text` cannot prove object inventory or associations and therefore cannot produce a full pass for a grouped product comparison. Automatic OCR discrepancies remain review candidates; independently reviewed structured discrepancies are hard failures. `--visual-review-passed` never changes text, object-count, or association results.

## Protected pixels

- Faces, skin, evidence, testimonials, product labels, and protected regions remain unchanged internally.
- Only transforms allowed by the manifest were applied.
- Cutout edges do not introduce halos, missing label pixels, or synthetic repainting.

A production pipeline should use image-region comparison or source-layer compositing to prove this. Visual similarity alone is insufficient.

Skip the protected-pixel claim for `model-led`; instead record that objects were semantically resynthesized. If pixel equality is required, the renderer selection is wrong.

## Seamless embedding

Review prepared assets and their relationship to copy as one integration system:

- No inherited opaque crop rectangle, accidental alpha halo, or source-background color spill remains.
- Product edge color, sharpness, grain, and local texture belong to the new scene.
- Scale, occlusion, contact shadow, grounding, and light direction are credible and consistent.
- Each product and its bound copy share an anchor, surface, connector, contour, or flow gesture; they do not read as an image pasted beside an unrelated text box.
- Generic repeated cards, frames, and detached captions appear only when the selected direction explicitly requires them.
- A protected core was not repainted during edge cleanup.

This review is independent from OCR and layout-delta checks. Pass `--integration-review-passed` only after inspecting the rendered image at both full-canvas and edge-detail scale.

## Layout integrity

- No overflow, clipping, accidental overlap, or unreadably small copy.
- The reading path is understandable at the target display size.
- Text contrast is sufficient and content groups remain traceable.
- Safe areas and target aspect ratio are respected.
- The selected topology and reading path remain perceptible; a distinctive kernel must not collapse into an ordinary grid, split column, or unrelated decoration.

## Radicality

- Compare the changed axes in `reconstruction-plan.json` with the source layout.
- For radical jobs, topology and reading path changed and at least five axes changed.
- Source features in `source_features_to_avoid` are absent.
- The result is not merely a recolor, new background, or decoration pass.
- The result belongs to the selected lane only; accidental blending with another shortlisted lane is a failure.

## Result states

Presentation and acceptance are independent. If the provider returned an image, show and retain it before or alongside QA regardless of the state below. A `fail` result means “visible candidate that failed acceptance,” not “hide the candidate and regenerate.” If the provider returned no artifact, report that provider failure separately; QA cannot manufacture a result.

- `pass`: bidirectional text, object-count, and association checks pass, and all named visual, protected-pixel, and integration reviews are complete.
- `conditional_pass`: machine checks pass but named visual, association, protected-pixel, or integration checks remain.
- `fail`: a required invariant, fidelity rule, or radicality rule failed.
- `blocked`: required source information or a clean protected asset is unavailable.

Retry one defect at a time only after the human explicitly authorizes one additional provider call. Repair the affected semantic node—object, copy anchor, edges, grounding, and local material together. Do not repair integration by reverting to a generic background plus overlay. If the defect is text fidelity in a generative result, switch to hybrid or deterministic rendering instead of repeatedly asking the generator to typeset dense copy.

Automatic retries are forbidden. Permit at most two human-authorized follow-up calls across targeted repairs and provider retries. Then escalate the renderer if the same string, association, or object-identity defect persists.
