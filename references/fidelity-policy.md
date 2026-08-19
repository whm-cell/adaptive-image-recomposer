# Fidelity and outcome policy

Choose the outcome contract before the renderer. Fidelity risk and creative ambition are separate decisions.

## Outcome contracts

| Contract | What may change | What must be proved | Default renderer |
|---|---|---|---|
| `creative_reconstruction` | whole composition, typography, decorative system, object rendering, spacing | required visible copy, object count, associations, visual delta | `model-led` |
| `audited_content` | whole-canvas layout and replaceable visual language; critical assets remain independently auditable inside final semantic nodes | exact copy, associations, object identity, protected-source treatment, integration | `hybrid` or `deterministic` |
| `pixel_fidelity` | surroundings plus approved transforms of protected pixels | region equality or source-layer compositing evidence | `locked-composite` |

`creative_reconstruction` preserves semantic identity, not pixels. It is appropriate for a polished image-model result only when the user accepts that product artwork and micro-label details may be resynthesized.

## Fidelity tiers

| Tier | Typical material | Required treatment |
|---|---|---|
| F3 evidence locked | face, skin, before/after, testimonial, medical or legal evidence | keep pixels unchanged; only approved crop, scale, translate, or frame |
| F2 exact structured | dosage, price, comparison values, dense Chinese copy | verify exact strings and their item associations |
| F1 asset sensitive | product pack, bottle, logo-bearing object | choose semantic redraw or locked source explicitly |
| F0 semantic | illustration, texture, generic scene | preserve meaning and user constraints |

Use the highest tier present, but do not let the tier silently choose the outcome contract. A creative F2 result can be attempted with `model-led`; it becomes production-ready only after exact-copy and association checks pass.

## Hard gates

1. F3 content never uses `model-led`.
2. `model-led` is incompatible with `lock_pixels` objects or protected regions. Change the contract or use an independently auditable source layer inside the jointly planned composition.
3. For a multi-item model-led job, provide `content.groups` so values cannot migrate between items.
4. Blocking uncertainties stop rendering.
5. Unreadable source microcopy must remain absent or visually non-readable; it must not be invented.
6. A flattened protected crop is not ready for seamless insertion until its silhouette and edge band can be isolated without changing protected core pixels. Otherwise use an explicit frame or stop for a cleaner asset.

## Escalation

- Start with `model-led` for a creative whole-canvas reconstruction.
- If exact text, item associations, or local integration fail, repair the affected semantic node in the latest result.
- After two targeted failures of the same kind, switch to hybrid or deterministic composition.
- If the missing requirement is a clean protected source asset, stop and request it.

Renderer escalation changes production authority, not the selected layout concept. Hybrid and deterministic routes still build one joint composition; they do not fall back to an empty background with detached coordinate overlays. Do not describe a visually similar product or face as pixel-preserved.
