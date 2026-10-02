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
export type Theme = "midday" | "twilight" | "evening" | "night" | "contrast" | "system";

/**
 * The names three themes had before they were renamed for the time of day they suit:
 * `light` is now `midday`, `dark` is `evening` and `midnight` is `night`.
 *
 * Still accepted wherever a theme is NAMED -- a stored choice, `defaultTheme`, an app's
 * `layout-contract.json`, a hand-written `data-theme` -- and mapped to today's name by
 * {@link resolveTheme}, so no app changes palette because of the rename. The token sheet paints
 * each one as the theme it now names (`aliases` in the contract's `themes.json`). New code
 * writes the new names; these exist so old code and old storage keep working.
 */
export type LegacyTheme = "light" | "dark" | "midnight";

/**
 * Every value {@link Theme} admits, in the order the theme control offers them: the shipped
 * palettes in registry order, then the OS-preference sentinel last.
 *
 * This is the runtime half of the union — the type does not survive to runtime, and a stored
 * string, a JSON file and a bootstrap option are all `string` until something checks them.
 */
export const THEMES: readonly Theme[] = [
  "midday",
  "twilight",
  "evening",
  "night",
  "contrast",
  "system",
];

/** Each {@link LegacyTheme} and the theme it now names. Mirrors `aliases` in `themes.json`. */
export const THEME_ALIASES: Readonly<Record<LegacyTheme, Theme>> = {
  light: "midday",
  dark: "evening",
  midnight: "night",
};

/**
 * The theme a stored, declared or passed name stands for: itself if it is one, today's name if
 * it is an earlier one, and `null` if it is neither. The one place an old name becomes a new
 * one, so the provider, the layout declaration and the bootstrap all agree on it.
 */
export function resolveTheme(name: string | null | undefined): Theme | null {
  if (name === null || name === undefined) {
    return null;
  }
  if ((THEMES as readonly string[]).includes(name)) {
    return name as Theme;
  }
  // Own keys only: "constructor" is not a theme.
  return Object.hasOwn(THEME_ALIASES, name) ? THEME_ALIASES[name as LegacyTheme] : null;
}
