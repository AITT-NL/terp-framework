/**
 * Per-theme custom properties that are NOT design tokens, as an exact list.
 *
 * Two gates are stated over "non-colour" tokens and mean it: geometry is theme-invariant
 * (`tokens.themes.test.js`), and the manifest names every token the base root declares
 * (`tokens.manifest.test.js`). This pair is neither — it is the theme's own `appearance` in
 * the one form a stylesheet can branch on, because `color-scheme` records the same fact and no
 * selector can read it. The values are `block` / `none`, so it varies per theme by
 * construction and belongs in no theme editor.
 *
 * Hand-written rather than imported from the generator that emits it, and that is the point:
 * a third such property appearing in `tokens.css` fails both gates until someone adds it here
 * with a reason. Importing the generator's own list would make every future addition
 * self-approving.
 */
export const APPEARANCE_MECHANISM_TOKENS = [
  "--appearance-show-light",
  "--appearance-show-dark",
];
