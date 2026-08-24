/**
 * The theme names, as a leaf module: no React, no DOM, two literals and nothing else.
 *
 * They live here rather than beside `ThemeProvider` because two consumers need them and only
 * one of them is a component. The provider needs the list to decide whether a stored choice is
 * still a theme this build ships; {@link ./layoutDeclaration.resolveLayoutDeclaration} needs it
 * to refuse a palette an app's checked-in declaration names and this release cannot honour.
 * Importing `theme.tsx` from that resolver would have pulled React, the icon set and the
 * component stylesheet's module-scope injection into a module whose entire job is to validate a
 * JSON file — and into the node-environment test that covers it, where the stylesheet's
 * `document` guard is the only thing standing between it and a crash.
 *
 * The union is a restatement of a published contract — `@terpjs/contract`'s compiled stylesheet
 * and its token manifest — so it can drift from it, in both directions and quietly:
 *
 *   * A theme the sheet ships that this union omits is a palette no app can ever select. It is
 *     compiled, gated for contrast and completeness, published in the manifest, unreachable.
 *   * A theme this union offers that the sheet has no block for sets `data-theme` to a value
 *     nothing matches, so the app renders the base palette while the control reports the choice
 *     took.
 *
 * `theme.themes.test.ts` holds this file against the manifest for exactly that. The names are
 * written out rather than derived from the manifest at runtime because react-core publishes
 * unbuilt source and imports nothing but React: resolving a sibling package's JSON module would
 * add a bundler and tsconfig requirement to every consumer, which is the consumption-model
 * change the framework spends real effort avoiding. The copy stays a copy, and the copy is
 * checked.
 */

/**
 * The visual theme: an explicit choice, or `"system"` to follow the OS preference.
 *
 * The token stylesheet (`@terpjs/contract/tokens.css`) carries every palette: it applies each
 * named theme's colours under `<html data-theme="<name>">` and — with no attribute — applies the
 * dark palette under `@media (prefers-color-scheme: dark)`, so `"system"` simply removes the
 * attribute.
 */
export type Theme = "light" | "dark" | "midnight" | "twilight" | "contrast" | "system";

/**
 * Every value {@link Theme} admits, in the order the theme control offers them: the shipped
 * palettes in registry order, then the OS-preference sentinel last.
 *
 * This is the runtime half of the union — the type does not survive to runtime, and a stored
 * string, a JSON file and a bootstrap option are all `string` until something checks them.
 */
export const THEMES: readonly Theme[] = [
  "light",
  "dark",
  "midnight",
  "twilight",
  "contrast",
  "system",
];
