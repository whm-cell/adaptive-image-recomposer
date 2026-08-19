# Asset preparation and embedding grammar

Seamless integration is planned before rendering. It is not a cosmetic blur, feather, or shadow applied after a product crop has been pasted onto a finished background.

## Three independent decisions

1. **Asset preparation** decides what pixels may be used and changed.
2. **Product embedding** decides how the object participates in the composition.
3. **Text embedding** decides how bound copy shares the same node and reading path.

The router attaches product and text grammars to every direction card. The selected pair remains invariant across renderer escalation.

## Asset-preparation modes

| Mode | Use when | Contract |
|---|---|---|
| `use-transparent-original` | A verified clean-alpha source exists | Preserve the asset, then match scale, local edge color, light, grounding, and scene texture. |
| `segment-protected-edge-band` | A required object exists only in a flattened raster | Keep the protected core unchanged; edit only the silhouette alpha/edge band to remove old-background spill. |
| `semantic-resynthesis` | The creative contract permits semantic rather than pixel identity | Render the object and its surroundings jointly, then audit recognizable identity. |
| `framed-source-fallback` | Safe isolation is impossible | Use an intentional visible frame and report the degradation; never pretend the crop is transparent. |

A white or visually simple crop is not automatically a transparent asset. When metadata is missing, infer conservatively and require preparation.

## Product-embedding grammars

- `semantic-joint-render`: model-render the object and scene as one node; no pixel-fidelity claim.
- `transparent-flat`: place a clean-alpha asset directly into the visual field with shared grain, edge color, and grounding.
- `grounded-stage`: anchor the object to a shelf, shadow, halo, light pool, or spatial plane used by neighboring nodes.
- `material-tuck`: overlap or tuck the object into paper, ribbon, contour, glass, or another shared material boundary without repainting a protected core.
- `framed-fallback`: contain an unsafe source crop in a deliberately visible frame; never recommend this as seamless embedding.

## Text-embedding grammars

- `joint-typography`: compose type and imagery together in a model-led semantic node, then audit exact copy.
- `direct-on-quiet-field`: place exact type directly on a low-frequency region planned with the object, without a generic card.
- `material-surface`: let type occupy a shared ribbon, shelf, paper, glass, or light surface already structuring the node.
- `editorial-annotation`: bind captions, pull facts, marginalia, or callouts to the object through alignment and hierarchy.
- `contour-rail`: place copy on the path, contour, radial rail, or connector that also expresses reading order.
- `card-fallback`: use a bounded text card only when density or contrast makes integrated placement unsafe, and record why.

## Joint semantic-node contract

Every content group becomes one composition node containing:

- the prepared or semantically rendered object;
- its exact name, values, qualifiers, and local hierarchy;
- a shared anchor or surface;
- silhouette and negative-space envelope;
- permitted overlap and occlusion;
- local edge, light, shadow, grain, and texture behavior;
- connector or reading-path role when applicable.

The node is planned in the final canvas geometry. Exact copy and protected assets may remain independent production layers, but they are not late detached overlays.

## Integration acceptance checks

Reject the result when any of these appears:

- inherited rectangular source background or feathered crop boundary;
- alpha halo, old-background color spill, or inconsistent edge sharpness;
- floating object with no credible scale, contact shadow, overlap, or shared light;
- pasted product beside a detached caption box;
- repeated generic cards replacing the selected structural grammar;
- texture or grain that stops at the insert boundary;
- edge cleanup that changes protected core pixels;
- exact strings that have migrated to a different product node.

Inspect both the whole-canvas reading path and close-up object edges. Content QA, protected-pixel QA, and integration QA remain separate checks.

## Renderer behavior

- `model-led` and `generative`: use semantic joint rendering only when fidelity permits; audit identity and copy.
- `hybrid`: solve final nodes first, then generate and assemble material around those exact anchors.
- `locked-composite`: lock protected cores, prepare only their edge bands, and construct the scene around final silhouettes.
- `deterministic`: render the entire composition from the content graph and node grammar; generation may provide local material, never an empty backdrop contract.

Background-first overlay is not an available workflow. The only degraded asset fallback is an intentional visible frame around an object that cannot be isolated safely; the whole canvas still follows the selected joint-composition grammar.

## Extension and pruning

Add a grammar only when it defines a new object-to-scene or copy-to-object relationship that can be tested. Do not add variants that differ only by palette, texture, corner radius, or shadow style. Remove modes that duplicate another grammar, hide rectangular crops, or restore the old “background plus cards” workflow.
