/**
 * The one interaction-state stylesheet for react-core.
 *
 * Components keep their inline token styles as the visible base (so tests can
 * still assert `element.style.background` etc.); this sheet layers hover,
 * active, focus-visible and small animation polish on top, keyed by
 * `data-terp` / `data-variant` attributes the components already set. That
 * keeps the boundary lint's inline-style rule intact (react-core itself is
 * allowed to inject a stylesheet — the rule targets *app modules*), while
 * giving every button, link, tab, row and menu real interaction states.
 *
 * Because the base styles are inline (`style={}` wins the cascade over author
 * stylesheets, even for `:hover` / `:focus` / `:disabled` rules), every
 * interaction-state declaration that overrides an inline base property is
 * marked `!important`. The rules are state-scoped (hover / focus / disabled
 * only), so the escalation cannot leak into resting styles.
 *
 * The injector is idempotent, SSR-safe (guarded on `document`), and appends
 * the rules through `textContent` — never `innerHTML` — so no HTML sink is
 * touched.
 */

/** The `<style>` element id used to detect a prior injection. */
export const TERP_STYLES_ID = "terp-core-styles";

/** The interaction-state rules layered over the component's inline base styles. */
export const TERP_STYLES_CSS = `
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

/* Shared focus-visible ring: every interactive element that opts in via
   [data-terp] shows a soft outline ring. !important lets the ring beat
   inline base box-shadows (e.g. the primary button's resting shadow) so
   keyboard focus is always visible. */
[data-terp]:focus-visible {
  outline: 2px solid transparent;
  outline-offset: 1px;
  box-shadow: 0 0 0 3px var(--color-focus-ring) !important;
}

/* Buttons ------------------------------------------------------------------ */
[data-terp="button"] {
  transition: background-color 150ms ease, color 150ms ease,
    border-color 150ms ease, box-shadow 150ms ease, transform 100ms ease;
}
[data-terp="button"][data-variant="primary"]:hover:not(:disabled) {
  background: var(--color-brand-primary-hover) !important;
}
[data-terp="button"][data-variant="secondary"]:hover:not(:disabled) {
  background: var(--color-neutral-100) !important;
  border-color: var(--color-neutral-300) !important;
}
[data-terp="button"][data-variant="ghost"]:hover:not(:disabled) {
  background: var(--color-neutral-100) !important;
  color: var(--color-neutral-900) !important;
}
[data-terp="button"][data-variant="danger"]:hover:not(:disabled) {
  filter: brightness(0.94);
}
[data-terp="button"]:active:not(:disabled) {
  transform: translateY(1px);
}
[data-terp="button"]:disabled {
  opacity: 0.55;
  cursor: not-allowed !important;
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
  border-color: var(--color-brand-primary) !important;
  box-shadow: 0 0 0 3px var(--color-focus-ring) !important;
}
[data-terp="input"]::placeholder {
  color: var(--color-neutral-500);
  opacity: 1;
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
}
[data-terp="hubcard"] {
  transition: border-color 150ms ease, box-shadow 150ms ease, transform 150ms ease;
}
[data-terp="hubcard"]:hover {
  border-color: var(--color-brand-primary) !important;
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}
[data-terp="hubcard"]:hover [data-terp="hubcard-title"] {
  color: var(--color-brand-primary) !important;
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

/* Menu items (UserMenu, DataView row-actions / column settings). */
[data-terp="menu-item"] {
  transition: background-color 150ms ease, color 150ms ease;
  border-radius: var(--radius-sm);
}
[data-terp="menu-item"]:hover:not(:disabled) {
  background: var(--color-neutral-100) !important;
  color: var(--color-neutral-900) !important;
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

/* Respect the user's reduced-motion preference — kill transitions and the
   spinner animation everywhere the sheet applies them. */
@media (prefers-reduced-motion: reduce) {
  [data-terp],
  [data-terp="appshell-nav"] a,
  [data-terp="dataview-table"] tbody tr {
    transition: none !important;
  }
  [data-terp="spinner-ring"] { animation: none !important; }
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
