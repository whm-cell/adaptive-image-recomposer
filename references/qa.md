# Reconstruction QA

Scripts can prove file facts and compare text candidates; visual review is still required.

## Content fidelity

- Every required verified string appears exactly once unless deliberate repetition is specified.
- Numbers, decimals, units, punctuation, asterisks, and footnotes match the manifest.
- Object and product counts match.
- No unverified brand, claim, fine print, or decorative copy was invented.
- Every item keeps its own name, values, qualifiers, and product association. Correct strings attached to the wrong item fail.

OCR is supporting evidence, not sole proof. Normalize whitespace for comparison, but do not normalize away meaningful punctuation, units, decimals, or masked characters.

## Protected pixels

- Faces, skin, evidence, testimonials, product labels, and protected regions remain unchanged internally.
- Only transforms allowed by the manifest were applied.
- Cutout edges do not introduce halos, missing label pixels, or synthetic repainting.

A production pipeline should use image-region comparison or source-layer compositing to prove this. Visual similarity alone is insufficient.

Skip the protected-pixel claim for `model-led`; instead record that objects were semantically resynthesized. If pixel equality is required, the renderer selection is wrong.

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

- `pass`: all machine-checkable requirements pass and visual review is complete.
- `conditional_pass`: machine checks pass but named manual checks remain.
- `fail`: a required invariant, fidelity rule, or radicality rule failed.
- `blocked`: required source information or a clean protected asset is unavailable.

Retry one defect at a time. If the defect is text fidelity in a generative result, switch to hybrid or deterministic rendering instead of repeatedly asking the generator to typeset dense copy.

For model-led work, permit two targeted repair edits to the latest result. Then escalate the renderer if the same string, association, or object-identity defect persists.
