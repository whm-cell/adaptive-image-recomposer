# Strategy routing

Routing must produce a genuinely divergent direction set before it produces a render prompt. A reference image is evidence about content and an anti-copy signal; it never becomes a preferred composition merely because one earlier result looked successful.

## Selection tree

Choose in this order:

1. outcome contract and fidelity boundary;
2. content archetype and density;
3. structural direction family;
4. topology kernel and reading path;
5. independent visual system;
6. renderer.

This order prevents three common errors: treating style as layout, allowing one sample to become the default answer, and mixing many incompatible ideas into one giant prompt. See [direction-tree.md](direction-tree.md) for the full tree and extension rules.

## Stage A: hard gates

1. Stop when source completeness fails.
2. Reject `model-led` for protected regions, pixel-locked objects, or F3 evidence.
3. Reject kernels that cannot support the renderer, text density, item count, or target aspect.
4. For `radical`, require both topology and reading-path change plus at least five changed axes.
5. Reject any kernel whose defining topology directly repeats a forbidden source feature.

## Stage B: compatibility score

Score every surviving kernel using content type, target aspect, item count, text density, renderer, protected-region support, novelty against the source signature, meaningful change axes, and kernel specialization. This score establishes viability, not final taste.

## Stage C: diversity reranking

The default `diverge_then_select` mode returns six candidates. The first pass chooses from unused compatible direction families before any family may repeat. Reuse of a topology family or reading path also receives a diversity penalty. Visual-system pairing likewise uses unused visual families first when compatible options exist.

The shortlist must satisfy these checks whenever enough compatible kernels exist:

- candidates span multiple direction families;
- topology and reading path are not cosmetic variants of one another;
- visual systems are varied independently from structure;
- no source-specific sample route receives a bonus;
- the first lane is provisional, not an automatic final choice.

Use `focused` only when the user has explicitly selected a direction family or when production constraints leave very few compatible kernels.

## Stage D: visual-system pairing

After structural diversification, pair each lane with one compatible visual system. Visual systems control palette, material, typography tone, texture, and finish. They do not change the structural identity of a lane. A new color palette on the same grid is still the same layout.

## Stage E: selection and compilation

Read `direction-board.md`, compare the candidates, and choose one lane using:

- magnitude of structural change from the source;
- legibility of the proposed reading path;
- ability to keep semantic groups intact;
- fit for the output context;
- fidelity and production risk;
- visual-system fit.

Compile exactly one selected kernel with its paired visual system. Do not concatenate the shortlist into one prompt. If two lanes are worth exploring, compile and render them as two separate concepts.

## Radicality contract

Track eight axes: aspect ratio, topology, reading path, hierarchy, grouping, container grammar, palette/material system, and text-image relationship.

- `radical`: topology and reading path change, and at least five axes change.
- `moderate`: at least three axes change.
- `conservative`: topology remains unless the user explicitly requests otherwise.

Changing only background, palette, typeface, texture, or decoration never satisfies a radical contract.

The catalog is [strategies/catalog.json](strategies/catalog.json). Use [strategies/index.md](strategies/index.md) to locate the family leaf for each shortlisted kernel.
