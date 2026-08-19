# Strategy routing

Routing must produce a genuinely divergent direction set before it produces a render prompt. A reference image is evidence about content and an anti-copy signal; it never becomes a preferred composition merely because one earlier result looked successful.

## Selection tree

Choose in this order:

1. outcome contract and fidelity boundary;
2. content archetype, density, and asset readiness;
3. structural direction family;
4. topology kernel and reading path;
5. independent visual system;
6. product and text embedding grammars;
7. human selection;
8. renderer and production contract.

This order prevents three common errors: treating style as layout, allowing one sample to become the default answer, and mixing many incompatible ideas into one giant prompt. See [direction-tree.md](direction-tree.md) for the full tree and extension rules.

## Stage A: hard gates

1. Stop when source completeness fails.
2. Reject `model-led` for protected regions, pixel-locked objects, or F3 evidence.
3. Classify every critical object's alpha, edge, source-background, and isolation readiness. Require semantic resynthesis, a clean cutout, an approved edge-band treatment, or a declared blocker.
4. Reject kernels that cannot support the renderer, text density, item count, target aspect, or available asset treatment.
5. For `radical`, require both topology and reading-path change plus at least five changed axes.
6. Reject any kernel whose defining topology directly repeats a forbidden source feature.

## Stage B: compatibility score

Score every surviving kernel using content type, target aspect, item count, text density, renderer, protected-region support, novelty against the source signature, meaningful change axes, and kernel specialization. This score establishes viability, not final taste.

## Stage C: diversity reranking

The default `diverge_then_select` mode returns six candidates. The first pass chooses from unused compatible direction families before any family may repeat. Reuse of a topology family or reading path also receives a diversity penalty. Visual-system pairing likewise uses unused visual families first when compatible options exist.

The shortlist must satisfy these checks whenever enough compatible kernels exist:

- candidates span multiple direction families;
- topology and reading path are not cosmetic variants of one another;
- visual systems are varied independently from structure;
- no source-specific sample route receives a bonus;
- no lane is automatically selected by rank or score.

Use `focused` only when the user has explicitly selected a direction family or when production constraints leave very few compatible kernels.

## Stage D: visual and embedding pairing

After structural diversification, pair each lane with one compatible visual system. Visual systems control palette, material, typography tone, texture, and finish. They do not change the structural identity of a lane. A new color palette on the same grid is still the same layout.

Then assign one product-embedding grammar and one text-embedding grammar. Their shared anchor, edge/light/texture behavior, and content capacity must appear in the direction card wireframe. A generic card is allowed only when the selected structural grammar explicitly calls for a container; it is never the universal solution.

## Stage E: decision board and human selection

`direction-board.md` presents each candidate as a decision card. Compare:

- magnitude of structural change from the source;
- legibility of the proposed reading path;
- ability to keep semantic groups intact;
- fit for the output context;
- asset readiness, text capacity, fidelity, integration, and production risk;
- visual-system fit.

The board may label `best_overall`, `boldest_change`, and `safest_production`. These labels expose tradeoffs; they do not authorize automatic selection. Routing must stop in `AWAITING_HUMAN_SELECTION`. A human chooses a candidate, and the `select` command records the candidate, its visual system, rationale, and route fingerprint.

## Stage F: route-bound compilation

Compilation requires a valid human selection record. Reject missing, stale, mismatched, or non-human selections. Compile exactly one selected kernel with its paired visual and embedding grammars. Do not concatenate the shortlist into one prompt. If two lanes are worth exploring, create two explicit selection records in separate jobs and render them as separate concepts.

## Radicality contract

Track eight axes: aspect ratio, topology, reading path, hierarchy, grouping, container grammar, palette/material system, and text-image relationship.

- `radical`: topology and reading path change, and at least five axes change.
- `moderate`: at least three axes change.
- `conservative`: topology remains unless the user explicitly requests otherwise.

Changing only background, palette, typeface, texture, or decoration never satisfies a radical contract.

The catalog is [strategies/catalog.json](strategies/catalog.json). Use [strategies/index.md](strategies/index.md) to locate the family leaf for each shortlisted kernel.
