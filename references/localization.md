# Presentation localization

Presentation language is independent from routing. Structural compatibility, diversity scoring, fidelity, capacity, and renderer choice operate only on stable IDs and structured manifest fields. Human-facing direction copy and the style-reference prompt come from `references/locales/` after the shortlist is fixed.

Set `intent.presentation_locale` in the manifest. `references/locales/index.json` resolves aliases and declares the default. A locale bundle provides direction-family copy, visual-system copy, content-boundary text, direction-board templates, and style-reference prompt templates.

The production Skill currently ships only `zh-CN`. Do not add a production locale merely to prove that routing is language-neutral. The regression suite creates a transient pseudo-locale for that invariant, so production translation maintenance remains single-source.

`references/locales/contract.json` is the language-pack structure contract. Loading a locale fails before routing when a required field is absent, a template placeholder changes, or direction/visual records drift from the strategy catalog.

To add a language:

1. Confirm that the product actually needs the additional presentation language.
2. Copy the default locale bundle and translate values without changing keys or placeholders.
3. Add the locale and any aliases to `index.json`.
4. Add the new locale file to `skill-pack.json` and refresh its digests.
5. Run the locale-contract, routing-invariance, and full regression tests.

Do not put language keywords into routing logic. Source-language words, labels, OCR output, and localized presentation copy are not risk classifiers. Record observed risk as structured `risk.signals`; the core uses each verified signal's declared minimum fidelity tier.
