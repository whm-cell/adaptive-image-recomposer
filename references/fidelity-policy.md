# Fidelity and outcome policy

Choose the outcome contract before the renderer. Fidelity risk and creative ambition are separate decisions.

## Outcome contracts

| Contract | What may change | What must be proved | Default renderer |
|---|---|---|---|
| `creative_reconstruction` | whole composition, typography, decorative system, object rendering, spacing | required visible copy, no undeclared copy, object count, associations, visual delta | `model-led`, or `hybrid` for dense closed-world content |
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

Use the highest tier present, but do not let the tier silently choose the outcome contract. Dense exact-copy or multi-product F2 work uses hybrid by default because the renderer must preserve a closed content budget. A lower-density creative F2 result may still be attempted with `model-led`; it becomes production-ready only after bidirectional text, object-count, and association checks pass.

## Hard gates

1. F3 content never uses `model-led`.
2. `model-led` is incompatible with `lock_pixels` objects or protected regions. Change the contract or use an independently auditable source layer inside the jointly planned composition.
3. Exact-copy and multi-product jobs require a closed visible-text whitelist, exact object cardinalities, and declared group schemas. A visual review cannot replace these gates.
4. Blocking uncertainties stop the workflow before a provider request is invoked. They cannot cancel an in-flight request or suppress an artifact that the provider already returned.
5. Unreadable source microcopy must remain absent or visually non-readable; it must not be invented.
6. A flattened protected crop is not ready for seamless insertion until its silhouette and edge band can be isolated without changing protected core pixels. Otherwise use an explicit frame or stop for a cleaner asset.

## Escalation

- Start with `model-led` for a creative whole-canvas reconstruction.
- If exact text, item associations, or local integration fail, repair the affected semantic node in the latest result.
- Never retry automatically. Each follow-up provider call requires a fresh explicit human authorization for exactly one request.
- After at most two human-authorized follow-up calls, switch to hybrid or deterministic composition.
- If the missing requirement is a clean protected source asset, stop and request it.

Renderer escalation changes production authority, not the selected layout concept. Hybrid and deterministic routes still build one joint composition; they do not fall back to an empty background with detached coordinate overlays. Do not describe a visually similar product or face as pixel-preserved.
