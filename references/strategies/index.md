# Strategy index

The active seed library contains 8 structural families and 32 topology kernels. Read only the family leaves referenced by the shortlisted lanes in `route-decision.json`; do not load the entire library into a render prompt.

| Direction family | Structural kernels | Family leaf |
|---|---|---|
| `flow-path` | `serpentine-flow`, `spiral-unfold`, `zigzag-ribbon`, `river-confluence` | [flow-path.md](flow-path.md) |
| `editorial-hierarchy` | `feature-cover-stack`, `newspaper-spread`, `split-feature-dialogue`, `annotated-column-essay` | [editorial-hierarchy.md](editorial-hierarchy.md) |
| `modular-comparison` | `catalogue-bands`, `hero-matrix-break`, `masonry-clusters`, `indexed-lanes` | [modular-comparison.md](modular-comparison.md) |
| `radial-network` | `focal-orbit`, `constellation-network`, `radial-wedges`, `hub-spoke-dashboard` | [radial-network.md](radial-network.md) |
| `spatial-stage` | `museum-exhibit-wall`, `scene-shelf`, `isometric-stage`, `depth-gallery` | [spatial-stage.md](spatial-stage.md) |
| `typographic-graphic` | `diagonal-zine`, `kinetic-type-islands`, `number-led-scoreboard`, `stamp-label-field` | [typographic-graphic.md](typographic-graphic.md) |
| `tactile-organic` | `cut-paper-collage`, `liquid-islands`, `botanical-archipelago`, `textile-patchwork` | [tactile-organic.md](tactile-organic.md) |
| `diagrammatic-data` | `subway-map`, `decision-tree`, `annotated-blueprint`, `spectrum-map` | [diagrammatic-data.md](diagrammatic-data.md) |

Structure and finish are independent. The router pairs a shortlisted kernel with one of 12 compatible visual systems, then assigns compatible product/text embedding grammars and an asset gate. These choices produce one decision card; they do not authorize automatic selection. The catalog metadata in [catalog.json](catalog.json) is authoritative for automatic compatibility checks; family leaves supply art direction and failure controls. See [../embedding-grammar.md](../embedding-grammar.md) for integration behavior.

There are no brand-specific, source-specific, or successful-example-specific active leaves. `serpentine-flow` is one ordinary kernel among 32, not the portrait-comparison default.
