/**
 * The one stylesheet for react-core: component base styles, variants and
 * interaction states, keyed by the `data-terp` / `data-variant` attributes the
 * components stamp on their roots (ADR 0094).
 *
 * Rules are attribute selectors, never class names, so the boundary lint's
 * `style`/`className` prohibition on app modules is untouched — react-core
 * itself is allowed to inject a stylesheet; the rule targets *app modules*.
 *
 * Migration in progress. A component that has moved renders no `style={}` and
 * gets its base here; one that has not still carries inline base styles, and
 * its interaction rules still need `!important` to beat them (`style={}` wins
 * the cascade over author stylesheets, even for `:hover` / `:focus`). Those
 * escalations are state-scoped, so they cannot leak into resting styles, and
 * each disappears with its component. The count is the phase's measurable.
 *
 * ## Layers
 *
 * The sheet is ordered by cascade layer rather than by source order, because
 * source order is what actually decides these rules and it is not something a
 * reader can see. `[data-terp]:focus-visible` and
 * `[data-terp="button"][data-variant="primary"]` both weigh (0,2,0) — an
 * attribute plus a pseudo-class against two attributes — so nothing but their
 * order in this file separates them. The shared focus ring has always been
 * declared near the top; the moment the primary button's resting shadow became
 * a rule here instead of an inline style, the ring stopped painting on the most
 * focus-relevant control in the package. Measured, not reasoned about: with
 * both in one layer the focused primary button computes
 * `rgba(15,23,42,0.06) 0 1px 2px` — its resting shadow — and with the ring in
 * `terp.state` it computes `rgba(37,99,235,0.35) 0 0 0 3px`.
 *
 * `terp.state` sits above `terp.base`, so a state rule wins on layer order
 * whatever its specificity and wherever it sits in the file, and needs no
 * `!important`. `terp.motion` sits above both so the reduced-motion override
 * beats every transition.
 *
 * Two things are deliberately left UNLAYERED, and the reason is the same for
 * both: unlayered author declarations beat layered ones regardless of
 * specificity. The density re-scoping must therefore stay unlayered, or the
 * contract's own unlayered `:root` token values would beat it and the compact
 * attribute would do nothing. And an app's `theme.css` is unlayered too, which
 * is what lets an app override any framework rule without `!important` — the
 * restyling this phase exists to enable.
 *
 * The injector is idempotent, SSR-safe (guarded on `document`), and appends
 * the rules through `textContent` — never `innerHTML` — so no HTML sink is
 * touched.
 */

/** The `<style>` element id used to detect a prior injection. */
export const TERP_STYLES_ID = "terp-core-styles";

/** The component base, variant and interaction rules react-core injects once. */
export const TERP_STYLES_CSS = `
@layer terp.reset, terp.base, terp.state, terp.motion;

/* Density: a subtree stamped data-density="compact" re-scopes the live density
   tokens to their compact counterparts, and every rule that reads the live
   token follows via custom-property inheritance. "comfortable" is the token
   sheet's :root value, so the attribute for it matches no rule — an app sets
   density per subtree (the shell for an app-wide default, an embedded DataView
   for one table), never per rule. A comfortable island inside a compact
   subtree is not expressible yet; that needs a named comfortable copy of each
   live token, which ADR 0094 defers until something asks for it.

   Unlayered on purpose: the contract's token sheet declares these on :root
   without a layer, and an unlayered declaration beats a layered one whatever
   its specificity — inside a layer this rule would lose to :root and the
   attribute would silently do nothing. */
[data-density="compact"] {
  --density-control-min-height: var(--density-compact-control-min-height);
  --density-cell-pad-y: var(--density-compact-cell-pad-y);
  --density-cell-pad-x: var(--density-compact-cell-pad-x);
}

@layer terp.reset {
/* Document reset: the app shell owns the full canvas. Without this the
   browser's default 8px body margin leaves the document's own (white)
   canvas visible as a ring around the shell — most obvious in Studio's
   preview iframe and in dark mode. The body carries the same canvas token
   as the shell so overscroll never flashes white. */
html, body {
  margin: 0;
}
body {
  background: var(--color-neutral-50);
}
/* Border-box baseline: react-core sizes components as padding-inclusive
   (e.g. LoginView's 100vh page with padding, inputs at width:100% with
   padding) and app modules cannot ship a stylesheet of their own, so the
   framework owns this. Under the browser default (content-box) a
   min-height:100vh + padding screen overflows the viewport by exactly its
   padding — phantom scrollbars on pages that fit. */
*,
*::before,
*::after {
  box-sizing: border-box;
}

/* Themed scrollbars: the OS default chrome (thick, grey, light-only) ignores
   the app theme and looks foreign against a token-styled surface — most
   obvious on the horizontal overflow of a DataView table. These rules give
   every scroll container a thin, token-coloured bar that tracks light/dark.
   Firefox uses the inheritable scrollbar-* properties (set once on the root);
   WebKit/Blink use the ::-webkit-scrollbar pseudo-elements (not inherited, so
   they match every scrollable element globally). Paired with the color-scheme
   declaration on the token roots so any native chrome we do not restyle here
   (notably the native <select> option popup) also follows the theme. */
html {
  scrollbar-width: thin;
  scrollbar-color: var(--color-neutral-300) transparent;
}
::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background-color: var(--color-neutral-300);
  border: 2px solid transparent;
  background-clip: padding-box;
  border-radius: var(--radius-full);
}
::-webkit-scrollbar-thumb:hover {
  background-color: var(--color-neutral-400);
}
::-webkit-scrollbar-corner {
  background: transparent;
}
}

@layer terp.base {
/* Buttons ------------------------------------------------------------------ */
[data-terp="button"] {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  width: fit-content;
  max-width: 100%;
  min-height: var(--density-control-min-height);
  padding: 0 var(--space-4);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  box-sizing: border-box;
  cursor: pointer;
  white-space: normal;
  text-align: center;
  font-family: var(--font-family-sans);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  line-height: 1.2;
  transition: background-color 150ms ease, color 150ms ease,
    border-color 150ms ease, box-shadow 150ms ease, transform 100ms ease;
}
[data-terp="button"][data-variant="primary"] {
  background: var(--color-brand-primary);
  color: var(--color-brand-primary-contrast);
  box-shadow: var(--shadow-sm);
}
[data-terp="button"][data-variant="secondary"] {
  background: var(--color-neutral-0);
  color: var(--color-neutral-900);
  border-color: var(--color-neutral-300);
}
[data-terp="button"][data-variant="danger"] {
  background: var(--color-status-danger);
  color: var(--color-neutral-0);
}
[data-terp="button"][data-variant="ghost"] {
  background: transparent;
  color: var(--color-neutral-700);
}
[data-terp="button-icon"] {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

/* Badges ------------------------------------------------------------------- */
/* The border matches the soft fill exactly, so it reads as one flat pill while
   still occupying a border box — which is what keeps a Badge the same height
   next to a bordered control. */
[data-terp="badge"] {
  display: inline-flex;
  align-items: center;
  border: 1px solid;
  border-radius: var(--radius-full);
  padding: 2px var(--space-2);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  line-height: 1.4;
  white-space: nowrap;
}
[data-terp="badge"][data-tone="neutral"] {
  color: var(--color-neutral-600);
  background: var(--color-neutral-100);
  border-color: var(--color-neutral-100);
}
[data-terp="badge"][data-tone="info"] {
  color: var(--color-status-info);
  background: var(--color-status-info-soft);
  border-color: var(--color-status-info-soft);
}
[data-terp="badge"][data-tone="success"] {
  color: var(--color-status-success);
  background: var(--color-status-success-soft);
  border-color: var(--color-status-success-soft);
}
[data-terp="badge"][data-tone="warning"] {
  color: var(--color-status-warning);
  background: var(--color-status-warning-soft);
  border-color: var(--color-status-warning-soft);
}
[data-terp="badge"][data-tone="danger"] {
  color: var(--color-status-danger);
  background: var(--color-status-danger-soft);
  border-color: var(--color-status-danger-soft);
}

/* Alerts ------------------------------------------------------------------- */
/* The tone sets the root's color, which the border picks up as currentColor
   and the icon inherits — so a tone is one declaration pair rather than three
   places to keep in step. The body restates the reading colour, because the
   copy must stay neutral-900 while the frame and glyph carry the tone. */
[data-terp="alert"] {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid;
  border-radius: var(--radius-md);
}
[data-terp="alert"][data-tone="neutral"] {
  color: var(--color-neutral-600);
  background: var(--color-neutral-50);
}
[data-terp="alert"][data-tone="info"] {
  color: var(--color-status-info);
  background: var(--color-status-info-soft);
}
[data-terp="alert"][data-tone="success"] {
  color: var(--color-status-success);
  background: var(--color-status-success-soft);
}
[data-terp="alert"][data-tone="warning"] {
  color: var(--color-status-warning);
  background: var(--color-status-warning-soft);
}
[data-terp="alert"][data-tone="danger"] {
  color: var(--color-status-danger);
  background: var(--color-status-danger-soft);
}
[data-terp="alert-icon"] {
  display: inline-flex;
  align-items: flex-start;
  padding-top: 2px;
}
[data-terp="alert-body"] {
  display: grid;
  gap: var(--space-1);
  min-width: 0;
  color: var(--color-neutral-900);
}
[data-terp="alert-title"] {
  font-weight: var(--font-weight-semibold);
}

/* Tooltips ----------------------------------------------------------------- */
/* No display declaration here on purpose: the panel is hidden with the hidden
   attribute, and any author display would beat the UA's [hidden] rule and
   leave the tooltip permanently visible. */
[data-terp="tooltip-anchor"] {
  position: relative;
  display: inline-flex;
}
[data-terp="tooltip"] {
  position: absolute;
  z-index: 1;
  inset-block-end: calc(100% + var(--space-1));
  inset-inline-start: 0;
  max-inline-size: min(18rem, calc(100vw - 2 * var(--space-4)));
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  color: var(--color-neutral-0);
  background: var(--color-neutral-900);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  line-height: 1.4;
  box-shadow: var(--shadow-md);
  pointer-events: none;
  white-space: normal;
}
}

@layer terp.state {
/* Shared focus-visible ring: every interactive element that opts in via
   [data-terp] shows a soft outline ring. It must stay in terp.state. It ties
   with [data-terp="button"][data-variant="primary"] on specificity — both
   (0,2,0) — so in a single layer the later rule would win, and this one is
   declared first: the primary button's resting shadow would suppress the ring
   entirely. The layer is what makes the ring independent of where either rule
   happens to sit in this file. */
[data-terp]:focus-visible {
  outline: 2px solid transparent;
  outline-offset: 1px;
  box-shadow: 0 0 0 3px var(--color-focus-ring);
}

/* Buttons ------------------------------------------------------------------ */
[data-terp="button"][data-variant="primary"]:hover:not(:disabled) {
  background: var(--color-brand-primary-hover);
}
[data-terp="button"][data-variant="secondary"]:hover:not(:disabled) {
  background: var(--color-neutral-100);
  border-color: var(--color-neutral-300);
}
[data-terp="button"][data-variant="ghost"]:hover:not(:disabled) {
  background: var(--color-neutral-100);
  color: var(--color-neutral-900);
}
[data-terp="button"][data-variant="danger"]:hover:not(:disabled) {
  filter: brightness(0.94);
}
[data-terp="button"]:active:not(:disabled) {
  transform: translateY(1px);
}
[data-terp="button"]:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* Icon-only buttons (header toggle, dismissers, pagination). */
[data-terp="iconbutton"] {
  transition: background-color 150ms ease, color 150ms ease, box-shadow 150ms ease;
}
[data-terp="iconbutton"]:hover:not(:disabled) {
  background: var(--color-neutral-100) !important;
  color: var(--color-neutral-900) !important;
}
[data-terp="iconbutton"]:disabled {
  opacity: 0.4;
  cursor: not-allowed !important;
}

/* Inputs / selects / textareas -------------------------------------------- */
[data-terp="input"] {
  transition: border-color 150ms ease, box-shadow 150ms ease;
}
[data-terp="input"]:hover:not(:disabled):not(:focus) {
  border-color: var(--color-neutral-400, var(--color-neutral-500)) !important;
}
[data-terp="input"]:focus,
[data-terp="input"]:focus-visible {
  outline: none;
  border-color: var(--color-fg-accent) !important;
  box-shadow: 0 0 0 3px var(--color-focus-ring) !important;
}
[data-terp="input"]::placeholder {
  color: var(--color-neutral-500);
  opacity: 1;
}
[data-terp="input"] option {
  color: var(--color-neutral-900);
  background: var(--color-neutral-0);
}
[data-terp="input"]:disabled {
  /* background-color (not the background shorthand) so the Select's chevron,
     drawn as a background-image, survives the disabled state. */
  background-color: var(--color-neutral-50) !important;
  color: var(--color-neutral-500) !important;
  cursor: not-allowed !important;
}
[data-terp="input"][aria-invalid="true"] {
  border-color: var(--color-status-danger) !important;
}
/* Number steppers are browser chrome and cannot be token-themed consistently.
   Keep keyboard/wheel/manual numeric input while removing the mismatched arrows. */
[data-terp="input"][type="number"] {
  appearance: textfield;
  -moz-appearance: textfield;
}
[data-terp="input"][type="number"]::-webkit-inner-spin-button,
[data-terp="input"][type="number"]::-webkit-outer-spin-button {
  appearance: none;
  -webkit-appearance: none;
  margin: 0;
}

/* Checkboxes / radios / switches ------------------------------------------- */
[data-terp="checkbox"]:disabled,
[data-terp="radio"]:disabled,
[data-terp="switch"]:disabled {
  cursor: not-allowed !important;
}
label:has([data-terp="checkbox"]:disabled),
label:has([data-terp="radio"]:disabled),
label:has([data-terp="switch"]:disabled) {
  cursor: not-allowed !important;
  color: var(--color-neutral-500) !important;
}

/* Sidebar navigation links (from the shell or any app-provided <a>). The hover
   rule skips the active route's link (aria-current="page") so the brand-soft
   active highlight is not washed out on hover. */
[data-terp="appshell-nav"] a {
  transition: background-color 150ms ease, color 150ms ease;
}
[data-terp="appshell-nav"] a:hover:not([aria-current="page"]) {
  background: var(--color-neutral-100) !important;
  color: var(--color-neutral-900) !important;
}
[data-terp="appshell-nav"][data-collapsed="true"] {
  overflow-x: hidden;
  scrollbar-width: none;
}
[data-terp="appshell-nav"][data-collapsed="true"]::-webkit-scrollbar {
  width: 0;
  height: 0;
}
[data-terp="appshell-brand"] {
  transition: background-color 150ms ease;
}
[data-terp="appshell-brand"]:hover {
  background: var(--color-neutral-100) !important;
}

/* Tabs -------------------------------------------------------------------- */
[data-terp="tab"] {
  transition: background-color 150ms ease, color 150ms ease, border-color 150ms ease;
  border-top-left-radius: var(--radius-sm);
  border-top-right-radius: var(--radius-sm);
}
[data-terp="tab"]:hover:not(:disabled):not([aria-selected="true"]) {
  color: var(--color-neutral-900) !important;
  background: var(--color-neutral-100) !important;
}
[data-terp="tab"]:disabled {
  opacity: 0.5;
  cursor: not-allowed !important;
}

/* Hub cards --------------------------------------------------------------- */
[data-terp="hubcard-link"],
[data-terp="hubcard"] a {
  text-decoration: none;
  color: inherit;
  display: block;
  height: 100%;
  min-height: 0;
}
[data-terp="hubcard"] {
  transition: border-color 150ms ease, box-shadow 150ms ease, transform 150ms ease;
}
[data-terp="hubcard"]:hover {
  border-color: var(--color-fg-accent) !important;
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}
[data-terp="hubcard"]:hover [data-terp="hubcard-title"] {
  color: var(--color-fg-accent) !important;
}

/* Breadcrumb links -------------------------------------------------------- */
[data-terp="breadcrumbs"] a {
  color: var(--color-neutral-600);
  text-decoration: none;
  transition: color 150ms ease;
}
[data-terp="breadcrumbs"] a:hover {
  color: var(--color-neutral-900);
  text-decoration: underline;
}

/* DataView table row hover ------------------------------------------------- */
[data-terp="dataview-table"] tbody tr {
  transition: background-color 150ms ease;
}
[data-terp="dataview-table"] tbody tr:hover td {
  background: var(--color-neutral-50);
}
[data-terp="dataview-row"]:focus-within td,
[data-terp="dataview-card"]:focus-within {
  background: var(--color-brand-primary-soft) !important;
}

/* Menu items (UserMenu, DataView row-actions / column settings). */
[data-terp="menu-item"] {
  transition: background-color 150ms ease, color 150ms ease;
  border-radius: var(--radius-sm);
}
[data-terp="menu-item"]:hover:not(:disabled) {
  background: var(--color-neutral-100) !important;
  color: var(--color-neutral-900) !important;
}
[data-terp="menu-item"][data-selected="true"] {
  background: var(--color-brand-primary-soft) !important;
  color: var(--color-fg-accent) !important;
}

/* Dialogs: ::backdrop cannot be set inline, so the dim layer lives here and
   matches the mobile drawer backdrop for one consistent overlay darkness. */
[data-terp="dialog"]::backdrop {
  background: rgb(0 0 0 / 0.4);
}

/* Spinner keyframes for the LoadingState ring. */
@keyframes terp-spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
[data-terp="spinner-ring"] {
  animation: terp-spin 0.8s linear infinite;
}

}

@layer terp.motion {
/* Respect the user's reduced-motion preference — kill transitions and the
   spinner animation everywhere the sheet applies them. The layer is above
   terp.base and terp.state, so this wins without !important. */
@media (prefers-reduced-motion: reduce) {
  [data-terp],
  [data-terp="appshell-nav"] a,
  [data-terp="dataview-table"] tbody tr {
    transition: none;
  }
  [data-terp="spinner-ring"] { animation: none; }
}
}
`;

/**
 * Inject the react-core interaction-state stylesheet once per document.
 *
 * SSR-safe: no-op when `document` is undefined. Idempotent: the sheet element
 * is keyed by {@link TERP_STYLES_ID}, so repeated calls (from any component's
 * module scope) attach the rules exactly once. Content is set via
 * `textContent` — never `innerHTML` — so no HTML-injection sink is touched.
 */
export function injectTerpStyles(): void {
  if (typeof document === "undefined") {
    return;
  }
  if (document.getElementById(TERP_STYLES_ID) !== null) {
    return;
  }
  const el = document.createElement("style");
  el.id = TERP_STYLES_ID;
  el.textContent = TERP_STYLES_CSS;
  document.head.appendChild(el);
}
