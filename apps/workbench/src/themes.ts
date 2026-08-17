// The import attribute is required, not stylistic: this module is loaded by two different
// loaders — Vite for the page and Playwright's for the spec files — and the latter refuses a
// JSON module without it.
import manifest from "@terpjs/contract/tokens.manifest.json" with { type: "json" };

import type { Theme } from "@terpjs/react-core";

// The themes the workbench renders, taken from the contract's published manifest rather than
// listed here.
//
// The list used to be `["light", "dark"] as const`, restated in three files — the page and both
// spec files. A theme added to the contract would then have been invisible to all three, which
// is the failure the manifest exists to prevent: a palette that is compiled, contrast-gated and
// published, and that nothing ever renders. Reading it here means a new theme arrives in the
// page and in the accessibility lane with no edit to any of them.
//
// `@terpjs/contract` is a real dependency of this app and the manifest is an export of it, so
// this is the ordinary consumption path, not a reach into the package's internals.

/** Every theme the contract ships, in registry order. */
export const THEMES = manifest.themes.map((theme) => theme.name as Theme);

/** The base theme — what a bare visit and an unrecognised `?theme=` fall back to. */
export const BASE_THEME = manifest.base as Theme;

/**
 * The themes the per-specimen screenshots cover: the two an app renders without anyone
 * choosing a theme at all — the base, and the one the OS dark preference selects.
 *
 * Deliberately narrower than {@link THEMES}, and the reasoning is the same one that made the
 * baselines per-specimen instead of per-page: a baseline earns its place by making one change
 * legible. A component's markup and geometry are identical in every theme — only colours
 * differ — so a third, fourth and fifth set of per-specimen shots re-prove what the first two
 * already prove, at the cost of tripling the number of PNGs a reviewer has to accept when a
 * padding value changes.
 *
 * What the extra themes genuinely need checking is legibility, and that is measured twice over
 * without a screenshot: statically for every declared pairing in `tokens.contrast.test.js`, and
 * against the painted pixels for every specimen in `a11y.spec.ts`, which does run in all of
 * them. If Phase 3 turns out to need per-theme geometry evidence, widening this to `THEMES` is
 * a one-word change.
 */
export const SCREENSHOT_THEMES: readonly Theme[] = [
  manifest.base as Theme,
  manifest.systemDark as Theme,
];
