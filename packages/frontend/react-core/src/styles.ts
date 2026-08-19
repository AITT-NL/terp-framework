/**
 * The one stylesheet for react-core: component base styles, variants and
 * interaction states, keyed by the `data-terp` / `data-variant` attributes the
 * components stamp on their roots (ADR 0094).
 *
 * Rules are attribute selectors, never class names, so the boundary lint's
 * `style`/`className` prohibition on app modules is untouched — react-core
 * itself is allowed to inject a stylesheet; the rule targets *app modules*.
 *
 * Migration in progress. A migrated component gets its base here and renders
 * no `style={}` for it — though it may still pass an inline value the sheet
 * has no business owning, which is why `Stack` keeps `align` / `justify`
 * inline. A component that has not migrated still carries inline base styles,
 * and its interaction rules still need `!important` to beat them (`style={}`
 * outranks any author rule, in any layer, for `:hover` / `:focus` / `:disabled`
 * alike). Those escalations are state-scoped, so they cannot leak into resting
 * styles, and each disappears with its component. The count is the phase's
 * measurable.
 *
 * The subtlety that bit once, and is worth stating: `!important` comes off per
 * CONSUMER, not per rule. Several selectors are shared. `input` is stamped by
 * `Combobox` and both date pickers as well as by the three text controls;
 * `[data-terp]:focus-visible` and the reduced-motion block match *every*
 * component in the package, so they are the last escalations that may retire.
 * A shared rule drops its `!important` only when the LAST element it matches
 * has migrated. Dropping `input`'s when the first three had left a disabled
 * `Combobox` painted exactly like an enabled one.
 *
 * It runs the other way too, and that direction is quieter: an escalation kept
 * after its last inline consumer migrated still outranks the app `theme.css`
 * this phase exists to empower, and nothing renders differently to say so.
 * `tab` was in that state until its rules were relaxed.
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
   tokens to their compact counterparts, and every rule reading a live token
   follows via custom-property inheritance. Two dimensions today: control
   height, read by Button, Input, Select and the date-picker trigger; and cell
   padding, read by the DataView's header and body cells, its cards, its
   expanded-row cell and the inline padding of its toolbar and pagination bars.
   The cell tokens were published one stage before anything read them and were
   deleted for it — they are back here, with their readers, in the same commit.

   The bars read only the inline half (--density-cell-pad-x, with --space-2
   vertically) so a bar's left edge stays flush with the first cell's text at
   either density. The header reads the same inline half and keeps --space-2
   vertically, because its comfortable value already IS the compact cell value:
   density moves the header's inline axis only, and tying a comfortable header
   to the compact scale would surprise anyone moving it from theme.css.

   "comfortable" is the token sheet's :root value, so the attribute for it
   matches no rule — an app sets density per subtree (the shell for an app-wide
   default, an embedded DataView for one table), never per rule. A comfortable
   island inside a compact subtree is not expressible yet; that needs a named
   comfortable copy of each live token, which ADR 0094 defers until something
   asks for it. Nothing does until AppShell takes a density of its own, which is
   the first time a DataView can find itself inside an already-compact subtree.

   Unlayered on purpose: the contract's token sheet declares these on :root
   without a layer, and an unlayered declaration beats a layered one whatever
   its specificity — inside a layer this rule would lose to :root whenever the
   attribute sits on the same element as those :root declarations (the app sets
   data-density on <html> for an app-wide default), and the attribute would
   silently do nothing. On any element BELOW the root the mechanism does not
   depend on that at all: a custom property declared on an ancestor is inherited
   rather than cascaded against, so a DataView stamping the attribute on itself
   wins over :root whatever the source order. */
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

/* Text controls ------------------------------------------------------------ */
/* Input, Select and Textarea deliberately share one marker, because the focus
   ring, the hover border and the disabled treatment are the same control
   affordance in all three. Only their geometry differs, so the element type
   carries that — no second attribute for a distinction the tag name already
   makes. */
[data-terp="input"] {
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-md);
  color: var(--color-neutral-900);
  background: var(--color-neutral-0);
  box-sizing: border-box;
  font-family: var(--font-family-sans);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-normal);
  line-height: 1.25;
  transition: border-color 150ms ease, box-shadow 150ms ease;
}
input[data-terp="input"] {
  min-height: var(--density-control-min-height);
  padding: 0 var(--space-3);
  line-height: 1.2;
}
/* The chevron is a background image, so the padding-right reserves its box and
   the shorthand restates the surface colour behind it. Appearance is reset on
   all three prefixes: the native affordance cannot be token-themed. */
select[data-terp="input"] {
  max-width: 100%;
  min-width: 0;
  min-height: var(--density-control-min-height);
  padding: 0 calc(var(--space-3) + 1.25rem) 0 var(--space-3);
  line-height: 1.2;
  background: url("data:image/svg+xml;charset=UTF-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none' stroke='%2364748b' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m5 8 5 5 5-5'/%3E%3C/svg%3E") no-repeat right var(--space-2) center / 1rem 1rem, var(--color-neutral-0);
  appearance: none;
  -webkit-appearance: none;
  -moz-appearance: none;
}
textarea[data-terp="input"] {
  padding: var(--space-2) var(--space-3);
  line-height: 1.4;
}

/* Stack -------------------------------------------------------------------- */
/* direction, gap and wrap are closed sets, so they are attributes with a rule
   each. align and justify are not: they take any alignment keyword CSS
   accepts, and minting a rule per keyword would be inventing a vocabulary the
   platform already has. Those two stay inline — the boundary ADR 0094 draws
   between styling policy and a value the caller measures. */
[data-terp="stack"] {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
}
[data-terp="stack"][data-direction="row"] { flex-direction: row; }
[data-terp="stack"][data-gap="0"] { gap: var(--space-0); }
[data-terp="stack"][data-gap="1"] { gap: var(--space-1); }
[data-terp="stack"][data-gap="2"] { gap: var(--space-2); }
[data-terp="stack"][data-gap="3"] { gap: var(--space-3); }
[data-terp="stack"][data-gap="4"] { gap: var(--space-4); }
[data-terp="stack"][data-gap="6"] { gap: var(--space-6); }
[data-terp="stack"][data-gap="8"] { gap: var(--space-8); }
[data-terp="stack"][data-wrap="true"] { flex-wrap: wrap; }

/* Detail lists ------------------------------------------------------------- */
/* The term and value are inline boxes inside a block row, which is what makes
   "Label: value" read as one line and wrap as one paragraph. */
[data-terp="detail-list"] {
  margin: 0;
  display: grid;
  gap: var(--space-1);
}
[data-terp="detail-list-term"] {
  display: inline;
  font-weight: var(--font-weight-medium);
}
[data-terp="detail-list-value"] {
  display: inline;
  margin: 0;
}

/* Checkboxes / radios / switches ------------------------------------------- */
/* One label shape for all three, so the marker is shared: the control differs,
   the "box or dot, gap, then its text" arrangement does not. accent-color is
   what paints the control itself — the browser picks the check colour, so the
   contrast that matters is the control against the page, which is why this is
   the ink token and not the filled-surface one (ADR 0093). */
[data-terp="control-label"] {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-neutral-900);
  cursor: pointer;
  font-size: var(--font-size-sm);
}
[data-terp="checkbox"],
[data-terp="radio"] {
  inline-size: 1rem;
  block-size: 1rem;
  accent-color: var(--color-fg-accent);
  cursor: pointer;
}
[data-terp="switch"] {
  inline-size: 2.25rem;
  block-size: 1.25rem;
  accent-color: var(--color-fg-accent);
  cursor: pointer;
  transition: background-color 150ms ease;
}
[data-terp="radio-group"] {
  display: grid;
  gap: var(--space-2);
  border: 0;
  padding: 0;
  margin: 0;
}
[data-terp="radio-group-legend"] {
  font-weight: var(--font-weight-medium);
  padding: 0;
  margin-block-end: var(--space-1);
  font-size: var(--font-size-sm);
  color: var(--color-neutral-700);
}
[data-terp="radio-group-options"] {
  display: grid;
  gap: var(--space-2);
}

/* Cards -------------------------------------------------------------------- */
[data-terp="card"] {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  background: var(--color-neutral-0);
  border: 1px solid var(--color-neutral-200);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  min-width: 0;
}
[data-terp="card"][data-gap="0"] { gap: var(--space-0); }
[data-terp="card"][data-gap="1"] { gap: var(--space-1); }
[data-terp="card"][data-gap="2"] { gap: var(--space-2); }
[data-terp="card"][data-gap="3"] { gap: var(--space-3); }
[data-terp="card"][data-gap="4"] { gap: var(--space-4); }
[data-terp="card"][data-gap="6"] { gap: var(--space-6); }
[data-terp="card"][data-gap="8"] { gap: var(--space-8); }
[data-terp="card-header"] {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--space-3);
}
[data-terp="card-heading"] {
  min-width: 0;
}
[data-terp="card-actions"] {
  flex-shrink: 0;
}
[data-terp="card-title"] {
  margin: 0;
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  line-height: 1.3;
}
[data-terp="card-description"] {
  margin: 0;
  color: var(--color-neutral-600);
  font-size: var(--font-size-sm);
}

/* Tabs --------------------------------------------------------------------- */
/* The tab strip sits one pixel over the list's bottom rule, so the selected
   tab's own 2px edge covers it rather than stacking beside it. */
[data-terp="tabs"] {
  display: grid;
  gap: var(--space-3);
}
[data-terp="tab-list"] {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  border-block-end: 1px solid var(--color-neutral-200);
}
[data-terp="tab"] {
  font-family: var(--font-family-sans);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  line-height: 1.25;
  padding: var(--space-2) var(--space-3);
  border: 0;
  border-block-end: 2px solid transparent;
  color: var(--color-neutral-600);
  background: transparent;
  cursor: pointer;
  margin-block-end: -1px;
  border-top-left-radius: var(--radius-sm);
  border-top-right-radius: var(--radius-sm);
  transition: background-color 150ms ease, color 150ms ease, border-color 150ms ease;
}
[data-terp="tab-panel"] {
  color: var(--color-neutral-900);
}

/* Breadcrumbs -------------------------------------------------------------- */
/* The trail owns its whole subtree, so the list and its items are addressed
   structurally and the current crumb by the aria-current it already carries —
   no marker for something the accessibility tree already states. */
[data-terp="breadcrumbs"] {
  font-size: var(--font-size-sm);
  color: var(--color-neutral-600);
}
[data-terp="breadcrumbs"] ol,
[data-terp="breadcrumbs"] li {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}
/* Keyed on our own marker, not on [aria-current="page"]. The trail's ancestor
   crumbs are the app router's links, and TanStack stamps aria-current="page" on
   every link whose path is a PREFIX of the current one — which every ancestor
   crumb is, by definition. Borrowing the attribute therefore painted the whole
   trail as the current page. */
[data-terp="breadcrumbs-current"] {
  color: var(--color-neutral-900);
  font-weight: var(--font-weight-medium);
}
[data-terp="breadcrumbs"] a {
  color: var(--color-neutral-600);
  text-decoration: none;
  transition: color 150ms ease;
}
[data-terp="breadcrumbs-separator"] {
  display: inline-flex;
  color: var(--color-neutral-400);
  line-height: 0;
}

/* DataView: the composition root ------------------------------------------- */
/* One display for both return paths, so it belongs on the bare marker rather than
   being duplicated per variant.

   And it is the one declaration in this block that NO lane gates, which is worth
   saying out loud rather than leaving for someone to discover by deleting it.
   Measured, not assumed: forcing this root to display: block leaves rootW, rootH,
   every child's width and the scroll wrapper's clientWidth/scrollWidth identical on
   dataview-wide, dataview-full and dataview-embedded alike — because the root's three
   children are full-width block boxes with no margins, which a single-column grid and
   a block container stack the same way. Deleting it would move no baseline. It is
   kept because the inline style declared it and this commit moves declarations rather
   than deciding them, and because it is not inert in the way a token with no reader
   is: the browser reads it, it simply cannot be told apart from the initial value by
   the compositions that exist.

   It also does not mean what the pairing story would have it mean, and the difference
   only shows up if the rule below is ever removed. A grid item's automatic minimum
   size is content-based unless its overflow is something other than visible, so under
   grid a wide table without overflow-x would widen the whole DataView, while under
   block the wrapper would stay at 100% and the table would simply spill out of it.
   Both are wrong; they are wrong differently. So the two rules are coupled, and
   dropping overflow-x is what dataview-wide catches — not this. */
[data-terp="dataview"] {
  display: grid;
}
/* The full variant's surface. (0,2,0) against the bare marker's (0,1,0), so it wins
   on specificity — no tie, no :not(), no source order. BOTH values of data-variant
   are stamped and only this one has a rule, which is the theme-toggle idiom where
   inline is stamped and takes the shared base while only stacked declares anything.
   Rejected: putting the surface on the bare marker and un-declaring it under
   [data-variant="embedded"], which needs background: transparent, border: 0 and
   border-radius: 0 — the shape ADR 0094 exists to avoid. Also rejected: stamping
   nothing for the default on the density precedent, which holds only because
   comfortable IS the :root value and so has nothing to declare.
   Byte-identical to [data-terp="card"]'s trio; written flat anyway, the Badge /
   Alert / row-tone precedent. No overflow: hidden, and none should be added here —
   the last row's border crossing the rounded bottom corners is pre-existing and
   belongs to its own commit. */
[data-terp="dataview"][data-variant="full"] {
  background: var(--color-neutral-0);
  border: 1px solid var(--color-neutral-200);
  border-radius: var(--radius-lg);
}
/* The horizontal scroll container the reset's scrollbar comment already names. A
   marker rather than [data-terp="dataview"] > div, which also matches the toolbar.
   Marking it makes it match [data-terp]:focus-visible for the first time: Chrome
   focuses a scroller only when it holds no keyboard-focusable descendant —
   reachable with every column enableSorting: false, no selection, no onRowClick and
   no row actions — so such a view now paints the accent ring around its table.
   Arguably correct, and invisible to all three lanes. */
[data-terp="dataview-scroll"] {
  overflow-x: auto;
}
/* The default error path's inset. Presence-conditional rather than
   value-conditional: this wrapper exists only when the caller supplies no
   renderError, so a caller-supplied error node gets no inset at all. The empty
   branch has no inset either — a pre-existing asymmetry visible in dataview-empty,
   and not something to tidy while moving declarations. */
[data-terp="dataview-error"] {
  padding: var(--space-4);
}
/* The loading skeleton. --space-3 stays --space-3 and does NOT become
   --density-cell-pad-x: comfortable is 0.75rem either way, so reading the token
   would be zero-diff in every existing baseline and a silent geometry change at
   compact — the trap the table header's comment already records, arriving here as
   the opposite decision because the skeleton's bars deliberately do not follow
   density. */
[data-terp="dataview-skeleton"] {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3);
}
/* The five placeholder bars. Structural rather than five markers, the card-main /
   actions-cell precedent: repeated identical boxes in a place where only bars sit.
   2.75rem is a literal — no published token carries it and the density family has
   no small-control step. In the contrast theme neutral-100 on neutral-0 is 1.12:1
   and so nearly invisible; that is pre-existing, non-text and aria-hidden.
   If this ever gains a shimmer: a transition here is caught by styles.test.ts,
   because the selector ends in a bare tag and its reduced-motion entry is then
   demanded — but an animation, the natural choice, is caught by nothing. */
[data-terp="dataview-skeleton"] > div {
  height: 2.75rem;
  background: var(--color-neutral-100);
  border-radius: var(--radius-md);
}

/* DataView: the toolbar ---------------------------------------------------- */
/* The band, both modes. The background is one of the ten declarations and that is
   deliberate: the inline style it replaces read
   selectionMode ? neutral-50 : neutral-0 — an explicit value in BOTH branches,
   not a conditional-or-nothing. Dropping it from the resting rule is invisible in
   every lane (the full variant's root and the workbench's specimen card are both
   neutral-0) and breaks the EMBEDDED variant in a real app, whose root declares
   nothing but display: grid — the band would go transparent and show the page
   canvas, body's neutral-50. dataview-toolbar-bare renders on a neutral-50 host
   precisely so that mutation fails a baseline instead of only a browser.

   Padding reads the inline half of the cell tokens with --space-2 vertically, so
   the bar's left edge stays flush with the first cell's text at either density —
   the same bargain the pagination bar strikes at the other end of the box, and
   the reader the density comment at the top of this file already claims to have.
   Comfortable --density-cell-pad-x IS --space-3, so only dataview-compact moves.

   The two radii are PHYSICAL, matching [data-terp="tab"], and they are
   load-bearing rather than decorative: DataView's root rounds its border with no
   overflow: hidden, so nothing else keeps the selection band's neutral-50 inside
   the rounded frame.

   min-height is inert at comfortable (1rem of block padding plus a 2.25rem
   control is 3.25rem) and exactly equal at compact (a 2rem control is 3.00rem),
   and it is not dead: it is the only floor when the embedded band renders for a
   caller's filter slot or trailing slot alone. It stays a literal for the same
   reason the pager arrows' 2rem does — no published token carries it.

   No colour declaration here on purpose. Two of this element's direct children
   are arbitrary caller slots, and inheriting a muted ink onto app-authored filter
   controls would be a silent restyle of app DOM. */
[data-terp="dataview-toolbar"] {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  padding: var(--space-2) var(--density-cell-pad-x);
  border-block-end: 1px solid var(--color-neutral-200);
  background: var(--color-neutral-0);
  border-top-left-radius: var(--radius-lg);
  border-top-right-radius: var(--radius-lg);
  min-height: 3rem;
}
/* Selection mode. A resting surface rather than an interaction state, so
   terp.base — and (0,2,0) against the base's (0,1,0) means it wins on
   specificity alone, needing no :not() and no source-order dependency. */
[data-terp="dataview-toolbar"][data-variant="selection"] {
  background: var(--color-neutral-50);
}
[data-terp="dataview-toolbar-count"] {
  font-weight: var(--font-weight-medium);
}
/* The batch-action group. NOT [data-terp="page-actions"] in disguise — that rule
   adds align-items: center and justify-content: flex-end. */
[data-terp="dataview-toolbar-actions"] {
  display: inline-flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}
/* One name, two elements, both of them spacers — the dataview-card-meta call.
   A bare > span:empty would reach both with no marker at all and is rejected: the
   batch-action group above is legitimately empty whenever a caller passes no
   batchActions, and would take flex: 1 in the commonest selection configuration. */
[data-terp="dataview-toolbar-spacer"] {
  flex: 1;
}
/* The search box's positioning context, the anchor three descendant rules hang
   off — exactly as [data-terp="combobox-field"] anchors the combobox's input and
   clear button. align-items: center is what vertically centres the absolutely
   positioned glyph, which is why the icon rule below needs no
   inset-block-start / translateY pair the way the combobox's clear button does. */
[data-terp="dataview-toolbar-search"] {
  position: relative;
  display: inline-flex;
  align-items: center;
}
/* The search glyph. Structural, and safe HERE and only here: this wrapper holds
   no caller slot, and once the clear button wears data-terp="iconbutton" it is a
   <button>, so this is the wrapper's only span child. neutral-500 on an
   aria-hidden decorative glyph owes no token pairing and axe abstains on it — do
   not "fix" it to fg-subtle by analogy with the status text below. */
[data-terp="dataview-toolbar-search"] > span {
  position: absolute;
  inset-inline-start: var(--space-2);
  display: inline-flex;
  color: var(--color-neutral-500);
  pointer-events: none;
}
/* The field. It must out-rank input[data-terp="input"] { padding: 0 var(--space-3) }
   and does so on SPECIFICITY rather than source order: two attributes (0,2,0)
   against an attribute plus a type (0,1,1). This is the equal-weight trap the
   header warns about, except the weights are not equal and that is the whole
   reason the rule is safe. The symmetric physical shorthand mirrors
   input[data-terp="input"][role="combobox"], which reserves room for its own clear
   button the same way; paired with logical insets above it is RTL-correct and
   zero-diff in LTR, the one place logical properties cost nothing here. 16rem is
   a fixed design width, not a caller measurement, so it is rule-side. */
[data-terp="dataview-toolbar-search"] > [data-terp="input"] {
  padding: 0 var(--space-6);
  width: 16rem;
  max-width: 100%;
}
/* The clear-search button, the package's fourth bare-glyph icon button.
   Deliberately NOT merged into the combobox clear button's selector list: that
   rule adds min-width and min-height 1.75rem, a radius and a centring pair, so
   joining them would enlarge this hit area and round its hover chip — a
   hover-only diff no baseline can catch. It can never match :disabled (it takes
   no disabled prop and renders only while the field is non-empty), so the shared
   :disabled derivation is unaffected by its arrival. */
[data-terp="dataview-toolbar-search"] > [data-terp="iconbutton"] {
  position: absolute;
  inset-inline-end: var(--space-1);
  display: inline-flex;
  padding: var(--space-1);
  background: transparent;
  border: none;
  cursor: pointer;
  color: var(--color-neutral-500);
}
/* "Refreshing…", and this is the one place the prefer-an-existing-DOM-attribute
   rule is REFUSED with its own reasoning. [data-terp="dataview-toolbar"]
   > [role="status"] looks textbook — the component does own this span's role — but
   the selector's scope is the band's direct children, two of which are arbitrary
   caller slots, so a caller's live region in a filter slot would silently take the
   muted 14px treatment. Owning one instance of an attribute is not owning every
   element a selector reaches. The ink is fg-subtle for the same declared-pairing
   reason as the column-settings caption: neutral-500 fails AA on a tinted surface,
   and this band has one in selection mode. */
[data-terp="dataview-toolbar-status"] {
  font-size: var(--font-size-sm);
  color: var(--color-fg-subtle);
}
/* The layout-toggle group: the anchor for the two buttons, as dataview-pager is
   for the four arrows. NOT dataview-pager itself — that carries gap: var(--space-2)
   and align-items: center, so sharing it would move these two apart. */
[data-terp="dataview-toolbar-layout"] {
  display: inline-flex;
  gap: var(--space-1);
}
/* The two toggles at rest, which is to say INACTIVE. 2rem stays a literal, pager
   reasoning. Their border is the neutral-300 control boundary, which measures
   1.48-1.78:1 against the band in four themes — below the 3:1 SC 1.4.11 asks of a
   control boundary, recorded as contract debt rather than fixed here, because a
   token clearing 3:1 repaints every bordered control in the package. */
[data-terp="dataview-toolbar-layout"] > [data-terp="iconbutton"] {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 2rem;
  padding: var(--space-1) var(--space-2);
  background: transparent;
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--color-neutral-500);
}

/* DataView: the table ------------------------------------------------------ */
/* Cells are reached from the ROW rather than from the table. A
   "tbody td" descendant selector would also match the expanded row's cell,
   which has a padding and a border of its own and would then have to
   out-specify this rule rather than simply not match it. */
[data-terp="dataview-table"] {
  width: 100%;
  border-collapse: collapse;
  table-layout: auto;
}
/* The header cell's inline axis follows density; its block axis does not,
   because --space-2 is already worth what --density-compact-cell-pad-y is. The
   0.04em tracking stays a literal: the contract's letter-spacing scale offers
   tight / base / wide, and wide is 0.08em, which would double it. */
[data-terp="dataview-table"] > thead > tr > th {
  position: relative;
  padding: var(--space-2) var(--density-cell-pad-x);
  text-align: left;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--color-neutral-500);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-bottom: 1px solid var(--color-neutral-200);
  white-space: nowrap;
  background: var(--color-neutral-0);
}
[data-terp="dataview-row"] > td {
  padding: var(--density-cell-pad-y) var(--density-cell-pad-x);
  border-bottom: 1px solid var(--color-neutral-100);
  font-size: var(--font-size-sm);
  color: var(--color-neutral-900);
  overflow: hidden;
  text-overflow: ellipsis;
}

/* The row marker was conditional on the row being clickable, which made every
   rule keyed on it conditional too: a toned but unclickable row carried
   data-tone on an element no selector could reach, and the row-tones baseline
   would have lost its tints the moment the tone moved out of a style object.
   It is unconditional now, and clickability is an attribute of its own. */
[data-terp="dataview-row"][data-clickable="true"] {
  cursor: pointer;
}
/* Row tone: a flat rule per tone, the shape Badge, Alert and toast use, because
   a private plumbing custom property is what tokens.guard.test.ts refuses.

   A row's own state outranks the selection tint, and the :not() is what says so
   without depending on source order — both selectors weigh (0,2,0) otherwise,
   which is precisely the trap the layer comment at the top of this file
   describes. Selection stays legible through the checkbox and data-selected. */
[data-terp="dataview-row"][data-selected="true"]:not([data-tone]) {
  background: var(--color-neutral-50);
}
[data-terp="dataview-row"][data-tone="neutral"] {
  background: var(--color-neutral-100);
}
[data-terp="dataview-row"][data-tone="info"] {
  background: var(--color-status-info-soft);
}
[data-terp="dataview-row"][data-tone="success"] {
  background: var(--color-status-success-soft);
}
[data-terp="dataview-row"][data-tone="warning"] {
  background: var(--color-status-warning-soft);
}
[data-terp="dataview-row"][data-tone="danger"] {
  background: var(--color-status-danger-soft);
}

/* The sort control. aria-sort sits on the th and only while the column IS
   sorted, so the unsorted glyph's dimming keys off its ABSENCE rather than off
   an attribute minted for it — this component owns aria-sort, unlike the
   breadcrumb's aria-current, which a router stamps on every ancestor link. */
[data-terp="dataview-column-sort"] {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font: inherit;
  color: inherit;
  background: transparent;
  border: none;
  padding: 0;
  cursor: pointer;
}
[data-terp="dataview-table"] > thead > tr > th:not([aria-sort]) > [data-terp="dataview-column-sort"] > svg {
  opacity: 0.5;
}
/* The resize handle sits flush with the cell's inline end. A negative offset
   would let the last column's handle spill past the table and trip the scroll
   container's overflow-x, adding a spurious scrollbar. The z-index is a local
   lift inside the cell's stacking context and deliberately NOT a place in the
   app-wide --z-index-* order. */
[data-terp="dataview-column-resizer"] {
  position: absolute;
  inset-block-start: 0;
  inset-inline-end: 0;
  width: 7px;
  height: 100%;
  cursor: col-resize;
  z-index: 1;
  touch-action: none;
}
/* System columns are pinned at pixel widths that ignore font size and density.
   Kept exactly as they were: a column-sizing model is on the debt list, and
   rewriting 40px as 2.5rem here would move them for any app whose root font
   size is not 16px. Scoped to th, which is where the width sits; the matching
   td wears the marker so the expand toggle has something to descend from. */
th[data-terp="dataview-expand-cell"],
th[data-terp="dataview-select-cell"] {
  width: 40px;
}
th[data-terp="dataview-actions-cell"] {
  width: 56px;
}
td[data-terp="dataview-actions-cell"] {
  text-align: right;
}
/* Visually hidden, twice over: the row's native activation button and the
   actions column's header text. The th qualifier is load-bearing — the actions
   BODY cell's only child is the row-actions cluster, and an unqualified
   descendant span would clip that out of the layout entirely. */
[data-terp="dataview-row-open"],
th[data-terp="dataview-actions-cell"] > span {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}

/* DataView: the card layout ------------------------------------------------ */
/* The responsive stand-in for a row, so it reads the same cell-padding tokens:
   a card IS the row's padding, and having compact tighten the table while
   leaving the cards alone would make the attribute mean two things. */
[data-terp="dataview-card-list"] {
  list-style: none;
  margin: 0;
  padding: var(--space-2);
  display: grid;
  gap: var(--space-2);
}
[data-terp="dataview-card"] {
  display: grid;
  gap: var(--space-2);
  padding: var(--density-cell-pad-y) var(--density-cell-pad-x);
  background: var(--color-neutral-0);
  border: 1px solid var(--color-neutral-200);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}
[data-terp="dataview-card"][data-clickable="true"] {
  cursor: pointer;
}
/* Tone outranks the resting surface on specificity alone — two attributes
   against one — so unlike the row's selection tint this needs no :not() and no
   source-order dependency. A card has no selected surface to compete with: the
   checkbox is the whole signal in card view. */
[data-terp="dataview-card"][data-tone="neutral"] {
  background: var(--color-neutral-100);
}
[data-terp="dataview-card"][data-tone="info"] {
  background: var(--color-status-info-soft);
}
[data-terp="dataview-card"][data-tone="success"] {
  background: var(--color-status-success-soft);
}
[data-terp="dataview-card"][data-tone="warning"] {
  background: var(--color-status-warning-soft);
}
[data-terp="dataview-card"][data-tone="danger"] {
  background: var(--color-status-danger-soft);
}
[data-terp="dataview-card-main"] {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
}
/* The two inline-flex wrappers in the card head: the one stopping click
   propagation around the checkbox, and the row-actions cluster. Addressed
   structurally because that is all they are — a span whose only job is to be a
   box, in a place where only those two spans sit. */
[data-terp="dataview-card-main"] > span {
  display: inline-flex;
}
[data-terp="dataview-card-body"] {
  flex: 1;
  min-width: 0;
}
[data-terp="dataview-card-expanded"] {
  border-block-start: 1px solid var(--color-neutral-200);
  padding-block-start: var(--space-2);
}
/* The auto-composed body: what the columns' mobileSlot meta produces when the
   caller supplies no renderCard. */
[data-terp="dataview-card-fields"] {
  display: grid;
  gap: var(--space-1);
}
[data-terp="dataview-card-heading"] {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
[data-terp="dataview-card-title"] {
  font-weight: var(--font-weight-medium);
}
[data-terp="dataview-card-status"] {
  font-size: var(--font-size-sm);
  padding: 0 var(--space-2);
  background: var(--color-neutral-100);
  border-radius: var(--radius-full);
  color: var(--color-neutral-700);
}
/* Subtitle and date share one name because they share every declaration. Two
   markers would suggest the sheet distinguishes them, and it does not.

   The ink is --color-fg-muted rather than --color-neutral-500, and that is a
   contrast fix rather than a preference for the semantic layer. A card's
   background is whichever soft tone getRowTone returned, and neutral-500 fails
   WCAG AA against four of the six surfaces this text can land on: measured,
   light neutral-100 4.34, light info-soft 4.46, light danger-soft 4.35 and
   midnight info-soft 4.12. fg-muted is 6.10 at its worst across all five
   themes, and carries the same value as --color-neutral-600 in every one of
   them, so this costs nothing but the name.

   Worth knowing HOW that was found, because the lesson is about the lane rather
   than the colour. This layout had no specimen at all, so the pairing had never
   been rendered for axe to measure; the first card specimen failed immediately.
   And axe reported exactly ONE of the four failures — the light danger-soft one
   — because the specimen paints the danger and warning tones and midnight's two
   failures are on info and success. Fixing what axe named would have left three
   real failures standing behind tones no specimen renders, which is why the fix
   is the token and why all five tone washes are now declared pairings. */
[data-terp="dataview-card-meta"] {
  font-size: var(--font-size-sm);
  color: var(--color-fg-muted);
}

/* The expand toggle, and the panel row it opens ---------------------------- */
/* The toggle wears the shared iconbutton marker rather than a name of its own,
   which is the third time the package has met this exact control: a bare
   chevron with no border, transparent, in muted ink. The toast dismisser and the
   combobox's clear button are the other two, and all three are addressed the
   same way — structurally, from the marked ancestor they sit in, because where
   it sits is the only thing distinguishing one from another.

   Two ancestors here, not one, and that is why this cannot key off the button.
   The same toggle renders in the table's expand column and in a card's head row.
   A descendant selector loose enough to cover both — anything like "an
   iconbutton inside a row" — would also catch an icon button an app renders
   inside one of its own cells, since a cell's content is arbitrary.

   Adopting the marker is an INTENTIONAL diff, and a hover-only one no baseline
   can see: the toggle gains the shared hover background and the transition every
   other icon button in the package already has. It had neither, which read as an
   oversight rather than a decision. */
[data-terp="dataview-expand-cell"] > [data-terp="iconbutton"],
[data-terp="dataview-card-main"] > [data-terp="iconbutton"] {
  display: inline-flex;
  padding: var(--space-1);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--color-neutral-500);
}
/* The panel cell spans every column. Its block padding follows density like any
   other cell; its inline padding is deliberately one step wider than a cell's
   and stays on the spacing scale, because the extra inset is what reads as
   "this belongs to the row above" rather than as another row. */
[data-terp="dataview-expanded-cell"] {
  padding: var(--density-cell-pad-y) var(--space-4);
  background: var(--color-neutral-50);
  border-block-end: 1px solid var(--color-neutral-200);
}

/* DataView: the pagination bar --------------------------------------------- */
/* The bar reads only the inline half of the cell padding, with --space-2
   vertically, so its left edge stays flush with the first cell's text at either
   density — the same bargain the toolbar strikes at the other end of the box. */
[data-terp="dataview-pagination"] {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
  padding: var(--space-2) var(--density-cell-pad-x);
  border-block-start: 1px solid var(--color-neutral-200);
  font-size: var(--font-size-sm);
  color: var(--color-neutral-500);
}
[data-terp="dataview-pager"] {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}
/* The four arrows: outlined icon buttons, addressed from the pager for the same
   reason the calendar's month arrows are addressed from the calendar header.
   The 2rem height is a literal and stays one: it happens to equal
   --density-compact-control-min-height, but reading that token would say these
   arrows are pinned to the compact scale, and moving the compact scale from
   theme.css would then resize a control at comfortable density. A small-control
   step in the density family is the honest fix and nothing has asked for one. */
[data-terp="dataview-pager"] > [data-terp="iconbutton"] {
  display: inline-flex;
  align-items: center;
  min-height: 2rem;
  padding: var(--space-1) var(--space-2);
  background: var(--color-neutral-0);
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--color-neutral-700);
}

/* DataView: the per-row action cluster ------------------------------------- */
[data-terp="dataview-row-actions"] {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-1);
}
/* The custom-control wrappers, addressed structurally rather than named: a span
   whose only job is to be a box, and the only span that is a DIRECT child here.
   Checked rather than assumed — the inline actions are buttons and the overflow
   menu's root is Popover's div, so neither is caught by this. */
[data-terp="dataview-row-actions"] > span {
  display: inline-flex;
}
/* An inline action: a bordered text-and-icon control. The font pair is
   order-dependent and stays in this order — the font shorthand resets font-size,
   so inheriting the row's font and THEN stepping the size down is the sequence
   that produces small text rather than inherited text. */
[data-terp="dataview-inline-action"] {
  font: inherit;
  font-size: var(--font-size-sm);
  display: inline-flex;
  align-items: center;
  min-height: 2rem;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  background: transparent;
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--color-neutral-700);
}
/* The leading icon: the only span inside the control, its sibling being a text
   node. */
[data-terp="dataview-inline-action"] > span {
  display: inline-flex;
}
/* Destructive is the same vocabulary MenuItem already uses for the same idea, so
   the attribute name is data-destructive there and here rather than a second
   spelling of one concept. */
[data-terp="dataview-inline-action"][data-destructive="true"] {
  color: var(--color-status-danger);
}

/* DataView: the view-options panel ----------------------------------------- */
/* The panel content. It carries data-owner="dataview-column-settings" on the
   portalled panel too, so a panel-level rule has somewhere to hang if this ever
   needs geometry a menu's panel does not have. */
/* No rule for the trigger's text: [data-terp="menu-trigger"] already declares
   font-size: var(--font-size-sm) and the span inherits it, so a marker here would
   be a name and a rule that change nothing — which is the offence the density
   tokens were deleted for, in miniature. The span stays unmarked deliberately. */
[data-terp="dataview-column-settings"] {
  display: grid;
  gap: var(--space-1);
}
[data-terp="dataview-column-settings-title"] {
  padding: var(--space-1) var(--space-2);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-neutral-500);
}
[data-terp="dataview-column-option"] {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
}
/* The checkbox and its column name. The only label in the panel, so it is
   reached structurally rather than named. */
[data-terp="dataview-column-option"] > label {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
  cursor: pointer;
  font-size: var(--font-size-sm);
}
/* The reorder arrows, which now wear the shared icon-button marker — the fourth
   instance of the bare-chevron archetype, after the toast dismisser, the
   combobox's clear button and the expand toggle. Same structural treatment: the
   geometry hangs off the row they sit in. */
[data-terp="dataview-column-option"] > [data-terp="iconbutton"] {
  display: inline-flex;
  padding: var(--space-1);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--color-neutral-700);
}

/* Empty / error / loading states ------------------------------------------- */
/* Same centred block, opposite messages: empty is a dashed outline on the page
   surface because nothing is wrong, error is a filled danger wash because
   something is. */
[data-terp="empty-state"] {
  display: grid;
  justify-items: center;
  gap: var(--space-3);
  padding: var(--space-8) var(--space-6);
  text-align: center;
  color: var(--color-neutral-600);
  border: 1px dashed var(--color-neutral-300);
  border-radius: var(--radius-lg);
  background: var(--color-neutral-0);
}
[data-terp="empty-state-icon"] {
  color: var(--color-neutral-400);
  display: inline-flex;
}
[data-terp="empty-state-title"] {
  margin: 0;
  color: var(--color-neutral-900);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
}
[data-terp="empty-state-description"] {
  color: var(--color-neutral-600);
  font-size: var(--font-size-sm);
  line-height: 1.5;
  max-width: 36ch;
}
[data-terp="error-state"] {
  display: grid;
  justify-items: center;
  gap: var(--space-3);
  padding: var(--space-6);
  text-align: center;
  color: var(--color-neutral-700);
  background: var(--color-status-danger-soft);
  border: 1px solid var(--color-status-danger);
  border-radius: var(--radius-lg);
}
[data-terp="error-state-icon"] {
  color: var(--color-status-danger);
  display: inline-flex;
}
[data-terp="error-state-title"] {
  margin: 0;
  color: var(--color-status-danger);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
}
[data-terp="error-state-description"] {
  color: var(--color-neutral-700);
  font-size: var(--font-size-sm);
  line-height: 1.5;
  max-width: 48ch;
}
[data-terp="loading-state"] {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-6);
  color: var(--color-neutral-500);
  font-size: var(--font-size-sm);
}
[data-terp="loading-state-spinner"] {
  color: var(--color-fg-accent);
}
/* The ring's box is inline (the caller passes a pixel size); everything about
   how it sits on the line is not. */
[data-terp="spinner-ring"] {
  display: inline-block;
  vertical-align: middle;
  line-height: 0;
}
[data-terp="spinner-ring"] > svg {
  display: block;
}

/* Icons -------------------------------------------------------------------- */
/* Icon takes any CSS length for its size, so width/height stay inline; the box
   it draws them in does not vary. */
[data-terp="icon"] {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  color: inherit;
}
[data-terp="nav-icon"] {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.25rem;
  height: 1.25rem;
  flex: 0 0 1.25rem;
  font-size: 1rem;
  line-height: 1;
}
[data-terp="nav-icon-fallback"] {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  border-radius: var(--radius-sm);
  background: var(--color-brand-primary-soft);
  color: var(--color-fg-accent);
  font-size: 0.7em;
  font-weight: var(--font-weight-medium);
  line-height: 1;
}

/* Combobox ----------------------------------------------------------------- */
/* The text box keeps the shared input marker, so it inherits the whole control
   surface; role="combobox" is already on it for ARIA and distinguishes its
   geometry here without minting an attribute for something the element
   already says. The extra inline-end padding reserves the clear button's box. */
input[data-terp="input"][role="combobox"] {
  width: 100%;
  min-width: 0;
  padding: 0 calc(var(--space-3) + 1.5rem) 0 var(--space-3);
}
[data-terp="combobox"],
[data-terp="combobox-field"] {
  position: relative;
  display: grid;
}
/* Addressed structurally rather than by a marker of its own: it is an
   iconbutton, and the only thing distinguishing it is where it sits. */
[data-terp="combobox-field"] > [data-terp="iconbutton"] {
  position: absolute;
  inset-inline-end: var(--space-1);
  inset-block-start: 50%;
  transform: translateY(-50%);
  border: none;
  background: transparent;
  color: var(--color-neutral-500);
  cursor: pointer;
  min-width: 1.75rem;
  min-height: 1.75rem;
  border-radius: var(--radius-sm);
}
/* Stacked at the popover level, which is what this is: an anchored disclosure
   panel. It read --z-index-drawer, and was the token's only reader anywhere —
   while the actual drawer, AppShell's mobile sidebar, hardcodes 50. So the one
   binding that existed pointed at the wrong level. The drawer token keeps its
   place in the family because AppShell's own migration is its reader; it is a
   pending consumer, not an unread token. */
[data-terp="combobox-list"] {
  position: absolute;
  inset-inline-start: 0;
  inset-inline-end: 0;
  inset-block-start: calc(100% + var(--space-1));
  z-index: var(--z-index-popover);
  display: grid;
  gap: var(--space-1);
  max-height: 16rem;
  overflow-y: auto;
  padding: var(--space-1);
  background: var(--color-neutral-0);
  border: 1px solid var(--color-neutral-200);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
}
[data-terp="combobox-option"] {
  font-family: var(--font-family-sans);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-normal);
  line-height: 1.25;
  text-align: left;
  padding: var(--space-2) var(--space-3);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-neutral-900);
  cursor: pointer;
}
[data-terp="combobox-empty"] {
  padding: var(--space-2) var(--space-3);
  color: var(--color-neutral-500);
  font-size: var(--font-size-sm);
}

/* Date pickers ------------------------------------------------------------- */
/* The trigger is a button wearing the input surface, so the element type is
   again what separates its geometry from the three text controls. */
button[data-terp="input"] {
  min-height: var(--density-control-min-height);
  width: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: 0 var(--space-3);
  line-height: 1.2;
  cursor: pointer;
}
button[data-terp="input"][data-placeholder="true"] {
  color: var(--color-neutral-500);
}
[data-terp="calendar"] {
  display: grid;
  gap: var(--space-2);
  min-width: 18rem;
}
[data-terp="calendar-header"] {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
[data-terp="calendar-header"] > [data-terp="iconbutton"] {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-neutral-700);
  cursor: pointer;
}
[data-terp="calendar-title"] {
  font-weight: var(--font-weight-semibold);
  color: var(--color-neutral-900);
}
/* The month grid holds six week rows; each row holds seven day cells. The split is
   what makes the ARIA grid valid, and the two gaps below are the one token the flat
   42-cell grid used for both axes, so the cells land unmoved. */
[data-terp="calendar-grid"] {
  display: grid;
  gap: var(--space-1);
}
[data-terp="calendar-week"] {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: var(--space-1);
}
/* The weekday initials and the days outside the visible month are the calendar's two
   subdued surfaces, and both take the SEMANTIC subtle ink rather than a ramp step. The
   distinction is not cosmetic: token-pairs.json declares subtle-on-surface, so the
   contrast gate measures this pairing in every theme, while --color-neutral-500 is the
   raw step and two palettes deliberately lift --color-fg-subtle above it (midnight
   #8b949e vs #7d8590, twilight #a294bd vs #9d90b8) — exactly the correction 0.7.0 made
   after axe found neutral-500 used as muted copy. The weekday row is aria-hidden, so
   axe can never report it: an undeclared pairing there is permanently unmeasured. */
[data-terp="calendar-weekday"] {
  text-align: center;
  font-size: var(--font-size-xs);
  color: var(--color-fg-subtle);
}
[data-terp="calendar-day"] {
  font-family: var(--font-family-sans);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-normal);
  line-height: 1.25;
  min-height: 2rem;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-neutral-900);
  cursor: pointer;
}
/* A day outside the visible month still occupies its grid cell — it is dimmed rather
   than hidden so the weeks keep their shape. Dimmed by INK, not by opacity, and that
   was a real defect rather than a preference: opacity: 0.45 composited the body ink
   against the panel to an effective colour that fails WCAG AA in all five themes
   (measured — light 2.93:1, dark 3.93:1, midnight 4.25:1, twilight 4.05:1, contrast
   3.36:1). Nothing could see it. axe never reached the subtree because nothing in the
   repo opened a calendar, and the static gate measures declared token PAIRINGS, which a
   composite of one token against another is not. The subtle ink is 4.76:1 at worst.

   Opacity also dimmed the cell's background, so an out-of-month day that is selected or
   inside a range used to render as a washed-out chip; it now paints at full strength,
   because a selected day should read as selected whichever month owns it. */
[data-terp="calendar-day"][data-outside-month="true"] {
  color: var(--color-fg-subtle);
}

/* Fields ------------------------------------------------------------------- */
[data-terp="field"],
[data-terp="field-label"] {
  display: grid;
  gap: var(--space-1);
}
[data-terp="field-label-text"] {
  font-weight: var(--font-weight-medium);
  font-size: var(--font-size-sm);
  color: var(--color-neutral-700);
}
[data-terp="field-hint"] {
  color: var(--color-neutral-500);
  font-size: var(--font-size-xs);
}
[data-terp="field-error"] {
  color: var(--color-status-danger);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
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

/* Menus -------------------------------------------------------------------- */
/* The trigger. It wore the shared iconbutton marker and overrode every one of
   that marker's declarations inline, which made it indistinguishable in the sheet
   from a pagination arrow and a toast dismisser. Its own name now, so this look —
   an outlined control with control typography — is stated once and reachable. */
[data-terp="menu-trigger"] {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 2rem;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  background: transparent;
  color: var(--color-neutral-700);
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-md);
  cursor: pointer;
  font-family: var(--font-family-sans);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-normal);
  line-height: 1.25;
  transition: background-color 150ms ease, color 150ms ease, box-shadow 150ms ease;
}
/* The panel's contents. This sits INSIDE popover-panel, which supplies the
   surface — so the menu owns only the stacking of its items. */
[data-terp="menu"] {
  display: grid;
  gap: var(--space-1);
}
[data-terp="menu-item"] {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  text-align: left;
  cursor: pointer;
  color: var(--color-neutral-900);
  font-family: var(--font-family-sans);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-normal);
  line-height: 1.25;
  transition: background-color 150ms ease, color 150ms ease;
}
/* Destructive is the one enumerable choice an item has, so it is an attribute.
   The disabled treatment is a state rule keyed on :disabled, because the element
   is a real button carrying the real attribute. */
[data-terp="menu-item"][data-destructive="true"] {
  color: var(--color-status-danger);
}
[data-terp="menu-item-icon"],
[data-terp="menu-item-check"] {
  display: inline-flex;
}
/* The check sits at the far end of the row rather than beside the label. */
[data-terp="menu-item-check"] {
  margin-inline-start: auto;
}

/* Theme and language menus -------------------------------------------------- */
/* Two variants, and only ONE of them is a popover: inline returns a bare Menu,
   so its root takes the wrapper geometry declared with Popover BELOW, while
   stacked renders
   a captioned grid with the menu inside it. So the stacked rule replaces the
   display rather than adding to it. The inherited position: relative is inert
   here — the stacked root has no positioned descendant of its own, because the
   menu inside carries its own wrapper. */
[data-terp="theme-toggle"][data-variant="stacked"],
[data-terp="language-switcher"][data-variant="stacked"] {
  display: grid;
  justify-items: start;
  gap: var(--space-1);
  font-size: var(--font-size-sm);
}
[data-terp="theme-toggle-label"],
[data-terp="language-switcher-label"] {
  color: var(--color-neutral-600);
}

/* Account menu -------------------------------------------------------------- */
/* UserMenu's root is the popover wrapper too, but unlike the two chrome toggles
   its trigger and its panel look nothing like the defaults — which is why it was
   the last consumer of Menu's triggerStyle and panelStyle props, and why both
   could be deleted once the root had a name. The trigger is reached by descending
   from that name; the PANEL cannot be, because it is portalled to document.body,
   so Popover stamps data-owner on it and the geometry hangs off that instead. */
/* A full-width identity row rather than the outlined control menu-trigger
   describes: two attributes against one, so it wins on specificity in the same
   layer without needing to be declared after it. */
[data-terp="user-menu"] [data-terp="menu-trigger"] {
  justify-content: flex-start;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2);
  text-align: left;
  color: var(--color-neutral-900);
  border-color: transparent;
  min-height: 0;
}
/* Icon-rail mode: the avatar alone, centred, with nothing around it. */
[data-terp="user-menu"][data-variant="collapsed"] [data-terp="menu-trigger"] {
  justify-content: center;
  gap: 0;
  padding: 0;
}
[data-terp="user-menu-avatar"] {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  flex-shrink: 0;
  border-radius: var(--radius-full);
  background: var(--color-brand-primary);
  color: var(--color-brand-primary-contrast);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
}
[data-terp="user-menu-identity"] {
  display: grid;
  min-width: 0;
  font-size: var(--font-size-sm);
}
[data-terp="user-menu-email"] {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
[data-terp="user-menu-role"] {
  color: var(--color-neutral-600);
}
/* The panel's identity block, and the panel's own geometry — both keyed on the
   owner, because the portal put them outside every selector that could otherwise
   reach them. */
[data-terp="popover-panel"][data-owner="user-menu"] {
  min-width: 14rem;
  padding: var(--space-2);
}
[data-terp="user-menu-header"] {
  display: grid;
  gap: var(--space-1);
  padding: var(--space-2);
  margin-block-end: var(--space-1);
  border-block-end: 1px solid var(--color-neutral-200);
  font-size: var(--font-size-sm);
  overflow-wrap: anywhere;
}

/* Page actions ------------------------------------------------------------- */
[data-terp="page-actions"] {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
}

/* Markdown ------------------------------------------------------------------ */
/* One declaration, and it is the whole design. Markdown emitted a fragment of
   bare block elements with no root, so it could not be found, styled or verified
   by anything. A wrapper fixes that but a wrapper is normally a new block box in
   every consumer's layout; display: contents generates NO box, so the blocks stay
   in-flow siblings exactly as the fragment left them, and inside a Stack or a Card
   or a Page article they become real flex and grid items so the parent's gap still
   falls between each one rather than once around the lot.

   Two things to know before adding a second declaration here. Every non-inherited
   property on a display: contents element is silently dropped — padding, margin,
   border, background, box-shadow — so prose rhythm has to be written as descendant
   rules ([data-terp="markdown"] p, ... ul), and a declaration added here would
   simply do nothing with nothing to say so. And display: contents does not change
   selector matching, only box generation: a parent's > * child selector now matches
   this wrapper rather than the blocks. Nothing in this sheet uses one, which is why
   the wrapper is free today.

   Under SSR the sheet is not injected at all (the injector is document-guarded), so
   a server-rendered page has this element as a block box until hydration. That is
   true of every rule in this file, but here the failure mode is restructuring rather
   than degrading. */
[data-terp="markdown"] {
  display: contents;
}

/* Toasts -------------------------------------------------------------------- */
/* The viewport is fixed to the corner of the screen, which is what puts it —
   like a portalled panel and a top-layer dialog — outside the box any per-specimen
   element screenshot could see. It reads the stacking token published for it; the
   component hardcoded 100. */
[data-terp="toast-viewport"] {
  position: fixed;
  inset-block-end: var(--space-4);
  inset-inline-end: var(--space-4);
  display: grid;
  gap: var(--space-2);
  z-index: var(--z-index-toast);
  max-width: min(22.5rem, calc(100vw - 2 * var(--space-4)));
}
[data-terp="toast"] {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: start;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  border-inline-start-width: 3px;
  background: var(--color-neutral-0);
  color: var(--color-neutral-900);
  font-size: var(--font-size-sm);
  box-shadow: var(--shadow-md);
}
[data-terp="toast-icon"] {
  display: inline-flex;
  align-items: center;
  padding-block-start: 2px;
}
[data-terp="toast-body"] {
  display: grid;
  gap: var(--space-1);
}
[data-terp="toast-title"] {
  font-weight: var(--font-weight-semibold);
}
/* Tone is data-tone, the same attribute Badge and Alert use, so one tone means one
   thing across the package. Written flat, per tone, like theirs: a private custom
   property would read better but tokens.guard.test.ts holds every var() in this
   package to a property the contract actually publishes, and an internal plumbing
   variable is not a token a theme editor should be offered. */
[data-terp="toast"][data-tone="success"] {
  border-color: var(--color-status-success-soft);
  border-inline-start-color: var(--color-status-success);
}
[data-terp="toast"][data-tone="success"] [data-terp="toast-icon"],
[data-terp="toast"][data-tone="success"] [data-terp="toast-title"] {
  color: var(--color-status-success);
}
[data-terp="toast"][data-tone="warning"] {
  border-color: var(--color-status-warning-soft);
  border-inline-start-color: var(--color-status-warning);
}
[data-terp="toast"][data-tone="warning"] [data-terp="toast-icon"],
[data-terp="toast"][data-tone="warning"] [data-terp="toast-title"] {
  color: var(--color-status-warning);
}
[data-terp="toast"][data-tone="danger"] {
  border-color: var(--color-status-danger-soft);
  border-inline-start-color: var(--color-status-danger);
}
[data-terp="toast"][data-tone="danger"] [data-terp="toast-icon"],
[data-terp="toast"][data-tone="danger"] [data-terp="toast-title"] {
  color: var(--color-status-danger);
}
/* The dismisser, addressed structurally for the same reason the combobox's clear
   button and the calendar's month arrows are. */
[data-terp="toast"] > [data-terp="iconbutton"] {
  border: none;
  background: none;
  padding: var(--space-1);
  cursor: pointer;
  color: var(--color-neutral-500);
  font-size: var(--font-size-base);
  line-height: 1;
  border-radius: var(--radius-sm);
}

/* Dialogs ------------------------------------------------------------------- */
/* A native dialog opened with showModal(). Note what is NOT declared: display.
   The UA sheet hides a closed dialog with dialog:not([open]) { display: none },
   and any author display here would beat it and leave the dialog permanently
   visible — the same trap the tooltip's comment records. Author rules beat the UA
   sheet whatever layer they sit in, so terp.base is enough to replace the UA
   dialog's border, padding, background and colour. */
[data-terp="dialog"] {
  width: 100%;
  max-width: 26rem;
  padding: 0;
  border: 1px solid var(--color-neutral-200);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  background: var(--color-neutral-0);
  color: var(--color-neutral-900);
}
[data-terp="dialog-body"] {
  display: grid;
  gap: var(--space-3);
  padding: var(--space-6);
}
[data-terp="dialog-title"] {
  margin: 0;
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  letter-spacing: 0;
  color: var(--color-neutral-900);
}
[data-terp="dialog-description"] {
  color: var(--color-neutral-600);
  font-size: var(--font-size-sm);
  line-height: 1.5;
}
[data-terp="dialog-actions"] {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-block-start: var(--space-2);
}

/* Icon-only buttons. Thirteen elements wear this marker and not one declares a
   transition inline, so this belongs in terp.base — it sat in terp.state only
   because that is where the hover rules needing it live. Same correction 817f572
   made for Tabs and Breadcrumbs. */
[data-terp="iconbutton"] {
  transition: background-color 150ms ease, color 150ms ease, box-shadow 150ms ease;
}

/* Popover ------------------------------------------------------------------ */
/* The wrapper the trigger sits in. Popover is the rendered root of Menu and of
   both date pickers, so this is the geometry of far more than one component —
   and of three components that ARE it. ThemeToggle, LanguageSwitcher and
   UserMenu each return a bare Menu, so this element is their rendered root and
   they name it themselves through Menu rather than wrapping it in a box nobody
   asked for. Every one of those names has to be in this selector list or the
   wrapper silently loses its geometry the moment a component claims its root:
   [data-terp="popover"] stops matching an element that now says theme-toggle,
   and nothing about the rule looks wrong. */
[data-terp="popover"],
[data-terp="theme-toggle"],
[data-terp="language-switcher"],
[data-terp="user-menu"] {
  position: relative;
  display: inline-flex;
}
/* The panel, which is portalled to document.body — so nothing about it can be
   reached by a descendant selector from the trigger's side of the tree.

   position: fixed belongs here rather than inline: it is structural, the same
   for every panel, and the fixed CONTAINING BLOCK is what makes the portal work
   (a panel positioned against the viewport is never clipped by an ancestor's
   overflow). What stays inline is only the measured part — the left/top the
   layout effect computes from the trigger's rect and clamps against the
   viewport, plus the visibility that hides the panel for the one frame before
   that measurement exists. Those are caller-measured lengths in ADR 0094's
   sense, and no rule could carry them.

   The stacking level is the token that was published for it. Every component in
   the package hardcoded its own number while a full --z-index-* family sat
   unread. AppShell still writes 50/40/30 for drawer/backdrop/sticky and comes
   right with its own migration; the toast viewport already reads
   --z-index-toast. Tooltip's z-index:
   1 above is deliberately NOT a token — the tooltip is absolutely positioned
   inside its own anchor, so 1 is a local lift within a stacking context rather
   than a place in the app-wide order. */
[data-terp="popover-panel"] {
  position: fixed;
  z-index: var(--z-index-popover);
  min-width: 12rem;
  padding: var(--space-1);
  font-family: var(--font-family-sans);
  color: var(--color-neutral-900);
  background: var(--color-neutral-0);
  border: 1px solid var(--color-neutral-200);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
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
/* The ring had no opaque part. The outline was transparent — present only so
   forced-colors mode has an outline to force — which left a translucent
   box-shadow as the entire visible indicator, and a translucent shadow's real
   colour is its alpha blend over whatever sits behind it. Measured that way,
   against neutral-0 and neutral-50, it reaches 1.67 / 1.65 in light, 2.30 / 2.43
   in dark, 2.51 / 2.59 in twilight and 2.73 / 2.68 in midnight. WCAG 2.1 SC
   1.4.11 asks 3:1 of a focus indicator, so four of the five shipped themes failed
   it on every focusable component in the package — and on many of them the ring
   REPLACED a user-agent outline that did meet it, because this rule sets outline
   at all.

   The outline now carries the colour and the shadow stays as its halo.
   --color-fg-accent is 6.70 / 6.41 light, 5.75 / 7.02 dark, 7.49 / 8.13
   midnight, 5.87 / 6.53 twilight, 9.14 contrast — never below 5.75. The offset
   keeps a 1px gap of surface between the element's own edge and the outline, so
   the indicator's adjacent colour is the surface rather than the control's fill,
   which is what makes one accent value safe on a filled button and on a bare
   input alike.

   Which lane saw it is worth recording, because the first answer was wrong. axe
   does not evaluate focus indicators and the keyboard lane asserts where focus
   GOES rather than what it paints — but SEVEN baselines moved on this change, and
   they are the visual proof of it: every specimen that renders a control focused
   on mount (both date pickers, three open menus, and both confirm dialogs) paints
   the ring at rest. What no lane covers is the ring on a control focused by an
   actual keystroke, which is every other component in the package, so the text
   assertion below is still the general gate.

   One detail fell out of that, and it is the useful half: the view-options panel
   did NOT move. Popover focuses the panel container, which carries tabIndex -1,
   and a programmatically focused non-interactive container does not match
   :focus-visible — while a programmatically focused BUTTON does. So the
   often-repeated shorthand that programmatic focus never matches :focus-visible is
   too coarse to plan a specimen with.

   The arithmetic is recorded here rather than as a test because token-pairs.json
   carries TEXT pairings only — a non-text pairing section is the real home for it
   and is deferred deliberately rather than bolted on. */
[data-terp]:focus-visible {
  outline: 2px solid var(--color-fg-accent);
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

/* Icon-only buttons: the shell's two header toggles, four pagination arrows, the
   toast dismisser, the combobox's clear button, the calendar's two month arrows,
   the DataView's expand toggle and the view-options panel's two reorder arrows.
   Thirteen SITES sharing a transition and nothing else — no shared SURFACE,
   because each is styled by where it sits. Sites rather than elements, and the
   distinction is new: the reorder arrows render twice per column row, so the
   element count is a function of how many columns a view has, while the list of
   places to check is fixed. The list matters because the escalations here retire
   per consumer, and an incomplete list is the input a future reader uses to
   decide whether one can come off.

   The hover pair still has to shout, and exactly one component is why: AppShell's
   toggleStyle declares background and colour inline on both header toggles, and
   nothing but !important reaches a style attribute. They come off with the shell.

   The :not([aria-pressed="true"]) on that pair is not defensive, and it is what
   makes shouting here safe. This marker is worn by toggles whose PRESSED look is
   byte-identical to these two values, so unguarded an !important hover paints an
   inactive toggle exactly like the active one — and because the declaration is
   both layered and important, nothing could restore it: not a higher-specificity
   author rule, not a later one, not an app's unlayered theme.css, which for
   important declarations sorts BELOW every layer. The guard makes the two rules
   mutually exclusive rather than merely equal-valued; without it they weigh
   (0,3,0) against (0,4,0) in one layer with the !important on the wrong one, and
   are benign only by coincidence of values. Same shape as
   [data-terp="tab"]:hover:not(:disabled):not([aria-selected="true"]).

   Safe by enumeration rather than by hope: aria-pressed appears at exactly three
   sites in the whole package, none of them a header toggle, a pager arrow, a month
   arrow, a reorder arrow, a toast dismisser or a combobox clear button — so every
   element wearing this marker today keeps its hover unchanged. That is why the
   guard lands here rather than alongside the toggles that need it: folded into a
   sixteen-site migration it would be one line of a large diff, and a change to a
   rule reaching seven components across the package should be reviewable as
   itself.

   The :disabled cursor no longer shouts, and re-deriving that is more useful than
   trusting it. The question is never "has anything migrated" but "can any element
   this selector matches still beat it" — so: which of the eleven can carry the
   disabled attribute at all? The shell's toggles cannot (no disabled prop). The
   toast dismisser cannot. The combobox's clear button renders only while the
   field is enabled and takes no disabled of its own. The calendar's arrows page
   the month unconditionally. The expand toggle has no disabled state. That leaves
   the four pagination arrows, which were the ONLY consumer, and which set cursor
   in pagerButtonStyle until this commit. So the escalation retired with them, and
   the day a calendar arrow gains a min/max bound the answer changes back. */
[data-terp="iconbutton"]:hover:not(:disabled):not([aria-pressed="true"]) {
  background: var(--color-neutral-100) !important;
  color: var(--color-neutral-900) !important;
}
[data-terp="iconbutton"]:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Inputs / selects / textareas -------------------------------------------- */
/* The escalation these carried is gone, and the condition for removing it was
   the marker's LAST consumer rather than its first. The input marker is shared
   by six elements — Input, Select, Textarea, the Combobox text box and both
   date-picker triggers — and while the latter three still styled themselves
   inline, these rules needed !important to reach them at all. Dropping it when
   only the text controls had migrated left a disabled Combobox painted exactly
   like an enabled one and deleted the aria-invalid border outright. All six
   now take their base from this sheet, so layer order is enough. */
[data-terp="input"]:hover:not(:disabled):not(:focus) {
  border-color: var(--color-neutral-400);
}
[data-terp="input"]:focus,
[data-terp="input"]:focus-visible {
  outline: none;
  border-color: var(--color-fg-accent);
  box-shadow: 0 0 0 3px var(--color-focus-ring);
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
  background-color: var(--color-neutral-50);
  color: var(--color-neutral-500);
  cursor: not-allowed;
}
[data-terp="input"][aria-invalid="true"] {
  border-color: var(--color-status-danger);
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
  cursor: not-allowed;
}
/* :has() rather than an attribute on the label: the label has no idea whether
   its control is disabled, and threading that through would duplicate state
   the DOM already carries. */
[data-terp="control-label"]:has([data-terp="checkbox"]:disabled),
[data-terp="control-label"]:has([data-terp="radio"]:disabled),
[data-terp="control-label"]:has([data-terp="switch"]:disabled) {
  cursor: not-allowed;
  color: var(--color-neutral-500);
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
  background: var(--color-neutral-100);
}

/* Tabs -------------------------------------------------------------------- */
/* Selection is a state, so it lives here rather than beside the tab's base:
   the accent edge and label have to beat the resting colour, and aria-selected
   is already on the element for assistive tech. */
[data-terp="tab"][aria-selected="true"] {
  font-weight: var(--font-weight-semibold);
  border-block-end-color: var(--color-fg-accent);
  color: var(--color-fg-accent);
}
[data-terp="tab"]:hover:not(:disabled):not([aria-selected="true"]) {
  color: var(--color-neutral-900);
  background: var(--color-neutral-100);
}
[data-terp="tab"]:disabled {
  opacity: 0.5;
  cursor: not-allowed;
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
/* The hover edge recolours hubcard-BODY, not the card.

   The rule here used to set border-color on [data-terp="hubcard"], which is the outer <li>
   and has no border: HubPage puts the visible edge on the inner hubcard-body span. So the
   accent edge — clearly the intent, since the title goes accent and the card lifts and gains
   a shadow at the same moment — never painted. Measured in a browser rather than reasoned
   about, because no baseline captures a hover: the li computes border 0px none at rest and
   0px none in the accent colour on hover, while the shadow and the transform do apply.

   The escalation moves with the declaration and is still required: hubcard-body's border is
   inline in HubPage, so a layered rule cannot beat it. It comes off when HubPage migrates.
   The transition splits for the same reason the hover did — box-shadow and transform animate
   on the card, border-color animates on the body, and declaring each where its property lives
   is what stops the next reader inheriting the same confusion. */
[data-terp="hubcard"] {
  transition: box-shadow 150ms ease, transform 150ms ease;
}
[data-terp="hubcard-body"] {
  transition: border-color 150ms ease;
}
[data-terp="hubcard"]:hover {
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}
[data-terp="hubcard"]:hover [data-terp="hubcard-body"] {
  border-color: var(--color-fg-accent) !important;
}
[data-terp="hubcard"]:hover [data-terp="hubcard-title"] {
  color: var(--color-fg-accent) !important;
}

/* Which layout is active, expressed as more than a wash. terp.state, and keyed on the
   real ARIA attribute — the [data-terp="tab"][aria-selected="true"] precedent — and the
   reuse is safe in the strong sense the breadcrumb case defines: DataViewToolbar is the
   sole author of aria-pressed on these two elements, setting it from its own layout
   prop, and no router, wrapper or caller can reach them.

   The border is the whole point of this rule, and it replaces a state that was carried
   by colour alone. Measured over the manifest's per-theme values: the neutral-100 fill
   against the band's transparent is 1.10 (light), 1.16 (dark), 1.09 (midnight), 1.12
   (twilight), 1.12 (contrast) — nowhere near the 3:1 SC 1.4.11 asks of a state
   indicator — and on two icon-only controls whose entire job is to say which layout is
   current, an ink difference alone is also SC 1.4.1. The accent border measures 6.12 /
   4.95 / 6.85 / 5.23 / 8.17 against its own neutral-100 fill and 6.70 / 5.75 / 7.49 /
   5.87 / 9.14 against the band, so it clears 3:1 on both sides in every theme. It is a
   NON-TEXT pairing, which token-pairs.json has no section for; recorded here with its
   numbers until it does.

   Deliberately NOT a box-shadow, and this one is a cascade fact rather than a taste:
   [data-terp]:focus-visible sets box-shadow in this same layer at (0,2,0) against this
   rule's (0,3,0), so an inset shadow here would win and a focused active toggle would
   lose its focus ring.

   No tie with the shared [data-terp="iconbutton"]:hover rule, and NOT because this one
   out-specifies it: that rule carries :not([aria-pressed="true"]), so the two selectors
   are mutually exclusive. Before that guard they were (0,3,0) and (0,4,0) in this same
   layer with identical values and the !important on the wrong one, so hovering the
   inactive toggle painted it exactly like the active one. */
[data-terp="dataview-toolbar-layout"] > [data-terp="iconbutton"][aria-pressed="true"] {
  background: var(--color-neutral-100);
  border-color: var(--color-fg-accent);
  color: var(--color-fg-accent);
}

/* Breadcrumb links -------------------------------------------------------- */
[data-terp="breadcrumbs"] a:hover {
  color: var(--color-neutral-900);
  text-decoration: underline;
}

/* The pager's disabled ink, scoped rather than added to the shared iconbutton
   rule above: of the thirteen sites wearing that marker only these four can be
   disabled at all, and giving the shared rule a colour would change how a
   disabled calendar arrow looks the day one becomes disableable. The shared rule
   supplies the opacity and the cursor; this supplies the ink the pager had
   inline. */
[data-terp="dataview-pager"] > [data-terp="iconbutton"]:disabled {
  color: var(--color-neutral-300);
}

/* A disabled inline action outranks a destructive one, which is the order the
   component's own ternary had: disabled first, destructive second. Here that
   ordering is the LAYER rather than the sequence of two equal-specificity rules
   — terp.state over terp.base — so it cannot be broken by moving a block. */
[data-terp="dataview-inline-action"]:disabled {
  color: var(--color-neutral-300);
  cursor: not-allowed;
}

/* A reorder arrow at the end of the list. The ink is scoped here for the same
   reason the pager's is: only a handful of the elements wearing the icon-button
   marker can be disabled, and putting a colour on the shared rule would change
   how a disabled month arrow looks the day one becomes disableable. */
[data-terp="dataview-column-option"] > [data-terp="iconbutton"]:disabled {
  color: var(--color-neutral-300);
}

/* DataView table ----------------------------------------------------------- */
/* Column resizing switches the table from auto to fixed layout, so the columns
   the user is not dragging stop reflowing mid-drag. A state, and an enumerable
   one, so it is an attribute rather than the inline table-layout it used to be
   — which also means the resting table declares no style attribute at all. */
[data-terp="dataview-table"][data-resizing="true"] {
  table-layout: fixed;
}
[data-terp="dataview-table"] tbody tr {
  transition: background-color 150ms ease;
}
[data-terp="dataview-table"] tbody tr:hover td {
  background: var(--color-neutral-50);
}
/* The row containing keyboard focus, highlighted because it is the one Enter would
   open. Guarded on data-clickable, and the guard is not decoration: the row marker
   became unconditional when the tone rules moved into this sheet, and without the
   guard this selector silently widened to any row with something focusable in it —
   a selection checkbox in a view with no onRowClick, painting a brand wash over a
   row nothing will open, and over its status tone. Widening it deliberately is a
   defensible change; arriving there as a side effect of marking the row is not.

   Neither lane can see this. The baselines capture the resting state, axe reads a
   static tree, and the keyboard lane is about where focus GOES rather than what it
   paints. So it is pinned from both ends instead: styles.test.ts asserts the guard
   is on this selector, and a unit test asserts a non-clickable row claims no
   data-clickable for it to match.

   The !important is GONE, and the condition was this rule's last inline consumer
   rather than its first. The two halves were never in the same state: the row half
   had nothing to out-shout — a body cell declares no background — while the card
   half faced DataViewCardList's inline background on the very element it matches.
   Both halves now take their surface from this sheet, so terp.state's layer order
   is enough, and the card's tone rules lose to it on layer rather than on
   specificity. Keeping the escalation past this point is the quiet failure: nothing
   would render differently, the declaration would simply become unthemeable. */
[data-terp="dataview-row"][data-clickable="true"]:focus-within td,
[data-terp="dataview-card"]:focus-within {
  background: var(--color-brand-primary-soft);
}

/* Combobox options. data-active is the roving keyboard/pointer highlight, which
   is not selection — both can be true at once, and the selected rule is
   declared second so it wins on the option the user actually chose. */
[data-terp="combobox-option"][data-active="true"] {
  background: var(--color-neutral-100);
}
[data-terp="combobox-option"][aria-selected="true"] {
  color: var(--color-fg-accent);
  font-weight: var(--font-weight-semibold);
}
[data-terp="combobox-option"]:disabled {
  color: var(--color-neutral-400);
  cursor: not-allowed;
}

/* Calendar days. Selection is the filled accent surface, so its label is the
   one token allowed on it; a day inside a range gets the soft wash instead. */
[data-terp="calendar-day"][data-in-range="true"] {
  background: var(--color-brand-primary-soft);
}
[data-terp="calendar-day"][aria-selected="true"] {
  border-color: var(--color-brand-primary);
  background: var(--color-brand-primary);
  color: var(--color-brand-primary-contrast);
}
/* A day that is BOTH outside the visible month and inside the selected range: the two rules
   above set different properties, so both apply and the subtle ink lands on the accent wash
   rather than on the panel surface. That pairing fails WCAG AA in two of the five themes
   (measured: light 4.37:1, midnight 4.26:1). The muted ink is 5.19:1 at worst across the five,
   and muted-on-soft is now a declared pairing — which is what gates it, and not for the reason
   one would guess. A specimen was added that paints the state, and axe still will not report
   it: it returns color-contrast as INCOMPLETE for these cells, reasoning that "Element content
   is too short to determine if it is actual text content". A one- or two-digit day number is
   below its heuristic. So axe can never gate contrast on a day cell — nor on any other
   one-glyph surface here, the toast dismisser and the breadcrumb separator included — and the
   declared-pairings gate in @terpjs/contract is the only lane that covers them. Measured,
   because the obvious assumption was that painting the state would be enough.

   The :not() guard is load-bearing rather than defensive. Without it this selector weighs
   (0,3,0) against the aria-selected rule's (0,2,0) in the same layer and would strip the
   contrast ink off a selected range ENDPOINT — and the endpoints are in range, because
   isWithinRange uses >= and <=. */
[data-terp="calendar-day"][data-in-range="true"][data-outside-month="true"]:not([aria-selected="true"]) {
  color: var(--color-fg-muted);
}
[data-terp="calendar-day"]:disabled {
  color: var(--color-neutral-300);
  cursor: not-allowed;
}

/* Menu items and the menu trigger.

   The escalation on these two item rules is GONE, and the condition for removing
   it was the marker's LAST consumer rather than its first. MenuItem is the only
   thing in the package that renders data-terp="menu-item" — unlike input, which
   six elements wear — so once it stopped carrying inline base styles there was
   nothing left for the rules to out-shout, and layer order is enough. Keeping
   !important past that point is the quiet failure: nothing renders differently,
   the rule just silently outranks the app theme.css this phase exists to
   empower. Both directions are pinned in styles.test.ts.

   The base declarations that used to sit up here — the item's transition and
   radius — have moved down to terp.base where they belong. They were here only
   because an inline style would have beaten them anywhere. */
[data-terp="menu-item"]:hover:not(:disabled) {
  background: var(--color-neutral-100);
  color: var(--color-neutral-900);
}
[data-terp="menu-item"][data-selected="true"] {
  background: var(--color-brand-primary-soft);
  color: var(--color-fg-accent);
}
[data-terp="menu-item"]:disabled {
  color: var(--color-neutral-300);
  cursor: not-allowed;
}
/* No :disabled rule for the trigger: Menu exposes no disabled prop, so the
   button can never carry the attribute. A selector matching nothing is dead
   styling that reads as live — the rule sits in the sheet looking like the state
   is handled. :not(:disabled) stays on the hover, because it costs nothing and
   the day the prop arrives the hover is already correct. */
[data-terp="menu-trigger"]:hover:not(:disabled) {
  background: var(--color-neutral-100);
  color: var(--color-neutral-900);
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
   spinner animation everywhere the sheet applies them.

   The layer puts this above terp.base and terp.state, which is enough for
   every transition this sheet declares ON a marked element. It is NOT enough
   for the ones still declared inline: AppShell's nav links and HubPage's card
   title each set transition in a style object, and no layer beats the style
   attribute — without !important a reduced-motion user still got those
   animations, an accessibility preference silently ignored that no screenshot
   can see. Those come off when the two components migrate.

   Note the selector list is the real limit here, not the layer: a transition
   on an element carrying no data-terp is reached only if something below names
   it. Breadcrumb links are such a case and are listed. AppShell's sidebar
   collapse (transition: width, in sidebarStyle) is NOT: the aside carries no
   marker, so nothing here matches it and a reduced-motion user still sees the
   rail animate. That is fixed by AppShell's own migration, which moves the
   declaration into this sheet, rather than by adding a marker to an element
   about to change shape. */
@media (prefers-reduced-motion: reduce) {
  [data-terp],
  [data-terp="appshell-nav"] a,
  [data-terp="breadcrumbs"] a,
  [data-terp="dataview-table"] tbody tr {
    transition: none !important;
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
