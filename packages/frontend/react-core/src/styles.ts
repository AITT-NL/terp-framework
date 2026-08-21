/**
 * The one stylesheet for react-core: component base styles, variants and
 * interaction states, keyed by the `data-terp` / `data-variant` attributes the
 * components stamp on their roots (ADR 0094).
 *
 * Rules are attribute selectors, never class names, so the boundary lint's
 * `style`/`className` prohibition on app modules is untouched — react-core
 * itself is allowed to inject a stylesheet; the rule targets *app modules*.
 *
 * THIS SHEET CARRIES NO `!important`. It carried 35 at 0.7.0, and the count going
 * to zero is what the migration was for: every rule here is now beatable by an
 * app's unlayered `theme.css` without `!important` and without out-specifying
 * anything. A new escalation is therefore a claim that some element still styles
 * itself inline on the same property — state it, with the file, or do not add it.
 *
 * THE LEDGER IS EMPTY. No module declares a module-scope base style object any more,
 * and the unmarked-surface worklist is empty with it — both gated in markers.test.ts,
 * both kept rather than deleted, for the reason the escalation ledger below is kept:
 * an empty gate is where the next entry has to justify itself.
 *
 * And the measure is now the whole surface rather than the annotated part of it. The
 * ledger counts module-scope `CSSProperties` declarations, which a call-site literal and
 * an unannotated style object both slip past — that is how the built-in admin views kept
 * five base styles through the entire migration with both ratchets reading clean. A third
 * gate counts inline style SITES per file, so the only way out of it is to render none;
 * the nine that remain are ADR 0094 §3's permanent inline side and nothing else, named
 * one by one in markers.test.ts.
 *
 * A migrated component gets its base here and renders no `style={}` for it —
 * though it may still pass an inline value the sheet has no business owning, which
 * is why `Stack` keeps `align` / `justify` inline and why DataViewTable keeps a
 * dragged column width.
 *
 * The mechanism is worth keeping even with the ledger empty, because it is what a
 * new rule has to reason about: `style={}` outranks any author rule, in any layer,
 * for `:hover` / `:focus` / `:disabled` alike, so a state rule aimed at an element
 * that styles itself inline is INERT — it works, nothing renders differently, and
 * the claim quietly becomes a lie. And the escalation that fixes it comes off per
 * CONSUMER, not per rule: several selectors are shared, so a shared rule may drop
 * its `!important` only when the LAST element it matches has migrated. Dropping
 * `input`'s when the first three had left a disabled `Combobox` painted exactly
 * like an enabled one.
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
 * ## Motion
 *
 * Every `transition` here names the published motion scale rather than a literal.
 * It wrote `150ms ease` 28 times and `100ms ease` once while reading a motion token
 * zero times — four duration tokens and three easings published in 2a with no reader,
 * which is the shape `--color-fg-on-brand` was deleted for. Wiring them was provably
 * inert: `--motion-duration-fast` IS `150ms`, `--motion-duration-instant` IS `100ms`
 * and `--motion-easing-standard` IS `ease`, so all 29 literals mapped onto a token
 * pair and no computed value changed.
 *
 * Four tokens stay unread, and that is a recorded position rather than an oversight:
 * `--motion-duration-base`, `--motion-duration-slow`, `--motion-easing-entrance` and
 * `--motion-easing-exit` map onto no literal this sheet contains. Deleting them is a
 * contract change (the manifest publishes them); giving them readers means inventing
 * overlay entrance/exit animations, which is a behaviour change dressed as a token
 * wiring — and the screenshot lane runs with `animations: "disabled"`, so it could not
 * see either the animation or a wrong duration in it. They are named in
 * `tokens.guard.test.ts` as an exact list, so wiring one shrinks that list and
 * publishing an eighth forces the decision instead of drifting.
 *
 * The spinner's `0.8s` is the one deliberate literal left. It is a rotation period
 * rather than an interaction step, and the scale tops out at 400ms, so there is no
 * token to name — the gate is scoped to `transition` for exactly that reason.
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
/* And the gutter is reserved whether or not the page is currently long enough to need
   it. Without this, every navigation between a page that fits and a page that does not
   changes the width of the content box by the scrollbar's width, so the whole layout —
   the header, the table, the centred login card — jumps sideways on the way in and back
   on the way out. The document is the scroll container here (the sidebar is sticky in
   normal flow rather than a scroller of its own), so the root is the right and only
   place for it.

   stable, not "stable both-edges": the gutter belongs where the scrollbar goes. The
   cost is that a page which never scrolls is off true viewport centre by the gutter,
   most visibly on the sign-in screen, and that is the trade every app that reserves the
   gutter takes. It is layered, so an app that would rather have the jump can turn it off
   from its own unlayered theme.css.

   This one moves pixels, which is why it is a deliberate line here rather than something
   to slip in beside a refactor: it narrows the content box of every scroll-free page. */
html {
  scrollbar-width: thin;
  scrollbar-color: var(--color-neutral-300) transparent;
  scrollbar-gutter: stable;
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
  transition:
    background-color var(--motion-duration-fast) var(--motion-easing-standard),
    color var(--motion-duration-fast) var(--motion-easing-standard),
    border-color var(--motion-duration-fast) var(--motion-easing-standard),
    box-shadow var(--motion-duration-fast) var(--motion-easing-standard),
    transform var(--motion-duration-instant) var(--motion-easing-standard);
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
/* Size. Two rules, not three: the standard control's geometry is the base rule above, so
   md is the absence of an attribute — the same shape density takes, where "comfortable" is
   the token sheet's own :root value and the attribute for it matches no rule.

   The heights are a calc() off the density token rather than a second family of tokens,
   and that is what makes size and density compose without either knowing about the other:
   a small button in a compact subtree resolves 2rem - 0.5rem, because the compact
   re-scoping has already moved the token this reads. A --control-height-sm of its own
   would have needed a compact counterpart, a re-scoping line, and a rule to keep the two
   in step, to express something the space scale already says. */
[data-terp="button"][data-size="sm"] {
  min-height: calc(var(--density-control-min-height) - var(--space-2));
  padding: 0 var(--space-3);
  font-size: var(--font-size-xs);
}
[data-terp="button"][data-size="lg"] {
  min-height: calc(var(--density-control-min-height) + var(--space-2));
  padding: 0 var(--space-6);
  font-size: var(--font-size-base);
}
/* Full width beats the base rule's width: fit-content on specificity — (0,2,0) against
   (0,1,0) in the same layer — so it needs neither a layer of its own nor an escalation.
   It exists as a prop because the only other way to reach it was the caller writing
   style={{ width: "100%" }}, which app modules may not do. */
[data-terp="button"][data-full-width="true"] {
  width: 100%;
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
  transition:
    border-color var(--motion-duration-fast) var(--motion-easing-standard),
    box-shadow var(--motion-duration-fast) var(--motion-easing-standard);
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
  transition: background-color var(--motion-duration-fast) var(--motion-easing-standard);
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
  transition:
    background-color var(--motion-duration-fast) var(--motion-easing-standard),
    color var(--motion-duration-fast) var(--motion-easing-standard),
    border-color var(--motion-duration-fast) var(--motion-easing-standard);
}
[data-terp="tab-panel"] {
  color: var(--color-neutral-900);
}

/* Module navigation -------------------------------------------------------- */
/* Secondary tabs for a module's sub-pages, and very nearly the same object as tab
   above: a transparent 2px edge the active item colours, muted ink the active item
   darkens. The difference is that these are router links rather than buttons, and
   that difference decides where the active state is keyed — see terp.state.

   The edges are logical (border-block-end) to match tab and appshell-footer rather
   than the physical borderBottom the component declared. Identical in every writing
   mode this framework ships, and the sheet already had one convention. */
[data-terp="module-nav"] {
  border-block-end: 1px solid var(--color-neutral-200);
}
[data-terp="module-nav-list"] {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}
[data-terp="module-nav-link"] {
  display: inline-flex;
  align-items: center;
  padding: var(--space-2) 0;
  color: var(--color-neutral-600);
  text-decoration: none;
  border-block-end: 2px solid transparent;
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
  transition: color var(--motion-duration-fast) var(--motion-easing-standard);
}
[data-terp="breadcrumbs-separator"] {
  display: inline-flex;
  color: var(--color-neutral-400);
  line-height: 0;
}

/* The app shell -------------------------------------------------------------- */
/* Twenty-two style objects came out of AppShell.tsx into this block, and with them the
   last five escalations in the sheet. Three facts drive every rule here and each has
   exactly one owner in the DOM:

     data-variant on the SHELL ROOT says mobile or desktop. The breakpoint itself stays in
     the component's media query rather than being restated as a CSS @media rule that
     could drift from it, so everything the viewport decides descends from this one
     attribute.
     data-collapsed on the SIDEBAR says icon rail. Everything the rail decides — its
     width, the brand's centring, the two hidden labels — descends from that.
     aria-current="page" on a nav link says active route. Every router sets it; the
     shell's hover rule has keyed on it since before this migration.

   That is why nothing here needs a style object handed across a public boundary, which
   is what AppShellLinkContext.style and RenderBrandLink's style param used to be. */
[data-terp="appshell"] {
  display: flex;
  align-items: stretch;
  min-height: 100vh;
  font-family: var(--font-family-sans);
  color: var(--color-neutral-900);
  background: var(--color-neutral-50);
}
/* The sidebar. width is a rule now rather than an inline value chosen per render, which
   is what finally puts its transition inside terp.motion's reach: the aside carried no
   marker, so the reduced-motion block matched nothing on it and a reduced-motion user
   watched the rail animate. The sheet's own comment said so and named this commit.
   border-inline-end rather than border-right: RTL-correct and zero-diff in LTR. */
[data-terp="appshell-sidebar"] {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-3);
  box-sizing: border-box;
  flex-shrink: 0;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-x: hidden;
  width: 15rem;
  background: var(--color-neutral-0);
  border-inline-end: 1px solid var(--color-neutral-200);
  transition: width var(--motion-duration-fast) var(--motion-easing-standard);
}
[data-terp="appshell-sidebar"][data-collapsed="true"] {
  width: 4rem;
}
/* The mobile drawer, reached from the shell root's variant rather than from an attribute
   of its own — the viewport is one fact and the root owns it. 100dvh rather than 100vh so
   a mobile browser's collapsing toolbar does not clip the drawer's footer.
   --z-index-drawer's FIRST reader anywhere: the token shipped with the family and the
   only thing that ever wanted it hardcoded 50, which is how the one binding that existed
   ended up pointing at the popover level instead. --z-index-backdrop and
   --z-index-sticky below are likewise first readers. */
[data-terp="appshell"][data-variant="mobile"] [data-terp="appshell-sidebar"] {
  position: fixed;
  inset: 0 auto 0 0;
  height: 100dvh;
  z-index: var(--z-index-drawer);
  box-shadow: var(--shadow-lg);
}
[data-terp="appshell-backdrop"] {
  position: fixed;
  inset: 0;
  z-index: var(--z-index-backdrop);
  background: rgb(0 0 0 / 0.4);
}
/* The brand, in its three looks. Only the first is a rule about the brand itself; the
   other two are rules about where it sits, which is what let the style-object parameter
   go. The collapsed look descends from the sidebar's attribute; the mobile look descends
   from the drawer's brand row, which exists only on mobile — so the DOM already says
   which look applies and the shell no longer has to compute one. */
[data-terp="appshell-brand"] {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  min-height: 2.25rem;
  color: var(--color-neutral-900);
  text-decoration: none;
  border-radius: var(--radius-md);
  box-sizing: border-box;
  transition: background-color var(--motion-duration-fast) var(--motion-easing-standard);
}
[data-terp="appshell-sidebar"][data-collapsed="true"] [data-terp="appshell-brand"] {
  justify-content: center;
  padding-inline: 0;
}
[data-terp="appshell-brand-row"] {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
[data-terp="appshell-brand-row"] > [data-terp="appshell-brand"] {
  flex: 1;
  min-width: 0;
}
[data-terp="appshell-brand-title"] {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-neutral-900);
  letter-spacing: 0;
}
[data-terp="appshell-nav"] {
  flex-grow: 1;
  overflow-y: auto;
  min-height: 0;
}
[data-terp="appshell-nav-list"] {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-1);
}
/* Sidebar navigation links, and this is the rule the whole shell migration was for. The
   geometry used to be NAV_LINK_STYLE, a CSSProperties object exported from AppShell for
   every router's link renderer to spread — so an app could not restyle a nav link at all
   (a style attribute outranks any author rule in any layer) and every stack duplicated the
   spread. The selector already existed here for the transition and the hover; it carries
   the resting look now, so the exported constants and the two style parameters are gone.

   The selector deliberately stays a descendant of the nav rather than gaining a marker of
   its own: the link element belongs to the caller's router, not to the shell, so there is
   no element here to stamp. */
[data-terp="appshell-nav"] a {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  color: var(--color-neutral-700);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  box-sizing: border-box;
  min-height: 2.25rem;
  transition:
    background-color var(--motion-duration-fast) var(--motion-easing-standard),
    color var(--motion-duration-fast) var(--motion-easing-standard);
}
/* The collapsed rail's link geometry: one centred fixed-size icon in the content track.
   (0,3,1) against the base's (0,1,1), so it wins on specificity with no source-order
   dependency. */
[data-terp="appshell-sidebar"][data-collapsed="true"] [data-terp="appshell-nav"] a {
  justify-content: center;
  gap: 0;
  padding: var(--space-2);
  width: 100%;
}
[data-terp="appshell-nav-label"] {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* Visually hidden, four elements, one rule. Two are the drawer's focus sentinels, which
   must stay focusable and so cannot be display: none. The other two are the brand title
   and the nav labels in the icon rail, which were a style-object TERNARY before this —
   the component picked between two objects per render, and the collapsed branch was
   painted by nothing, because the rail state was internal and no specimen could reach it.
   That is what defaultCollapsed is for. */
[data-terp="drawer-focus-start"],
[data-terp="drawer-focus-end"],
[data-terp="appshell-sidebar"][data-collapsed="true"] [data-terp="appshell-brand-title"],
[data-terp="appshell-sidebar"][data-collapsed="true"] [data-terp="appshell-nav-label"] {
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
[data-terp="appshell-column"] {
  display: flex;
  flex-direction: column;
  flex-grow: 1;
  min-width: 0;
}
[data-terp="appshell-header"] {
  position: sticky;
  top: 0;
  z-index: var(--z-index-sticky);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4);
  min-height: 3rem;
  box-sizing: border-box;
  background: var(--color-neutral-0);
  border-block-end: 1px solid var(--color-neutral-200);
}
[data-terp="appshell-header-group"] {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
/* The shell's two toggles: the header's sidebar control and the drawer's close button.
   Both already wore the shared iconbutton marker and overrode every one of that marker's
   would-be declarations from toggleStyle, which is what kept the shared hover rule
   shouting — a style attribute outranks any author rule in any layer, so
   [data-terp="iconbutton"]:hover needed !important on background and colour to reach
   these two elements and only these two. They are the last such consumers, so those two
   escalations retire here.
   Reached structurally rather than by a marker of their own, the combobox-clear-button
   precedent: each is an icon button and the only thing distinguishing it is where it
   sits. The typography was CONTROL_TEXT_STYLE, whose only consumer this was — the module
   is deleted with it. */
[data-terp="appshell-header"] > [data-terp="iconbutton"],
[data-terp="appshell-brand-row"] > [data-terp="iconbutton"] {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  padding: 0;
  color: var(--color-neutral-700);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  cursor: pointer;
  font-family: var(--font-family-sans);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-normal);
  line-height: 1.25;
}
[data-terp="appshell-main"] {
  flex-grow: 1;
  padding: var(--space-6);
  min-width: 0;
}
[data-terp="appshell"][data-variant="mobile"] [data-terp="appshell-main"] {
  padding: var(--space-4);
}
[data-terp="appshell-footer"] {
  padding: var(--space-3) var(--space-6);
  border-block-start: 1px solid var(--color-neutral-200);
  color: var(--color-fg-subtle);
  font-size: var(--font-size-xs);
}

/* The page frame ----------------------------------------------------------- */
/* Every routed view is this shape: one header carrying the breadcrumb trail (when
   there is a path back up) and the title row, then the body. HubPage, OverviewPage
   and DetailPage are all this frame with a different trail.

   The header is a <header> ELEMENT and Page has to keep it one, which is a
   constraint this sheet cannot express and the component records at the site: the
   layout contract's runtime slot check reads article.children and drops the header
   by TAG NAME, so re-rendering it as a marked <div> would put it back into the body
   set and fail every governed OverviewPage and DetailPage closed. Marking it is
   additive; retagging it is not. The body likewise takes no wrapper — not even a
   display: contents one, since that check is a DOM traversal and would see the node
   whether or not it generates a box.

   align-content: start is what keeps the rows at the top of a page taller than its
   content — the loading and error frames, where the body is one small block. With
   the default the two rows would spread to fill the height. It needs something to
   stretch the article before it is observable at all, which is why page-loading and
   page-error render inside a grid box rather than a plain tall div. */
[data-terp="page"] {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-4);
  align-content: start;
  min-width: 0;
}
[data-terp="page-header"] {
  display: grid;
  gap: var(--space-2);
}
/* The crumb row keeps a 2rem floor, and it is doing work rather than reserving
   space for its own sake: the trail is shorter than 2rem at font-size-sm, so
   dropping the floor closes the gap under the trail on every page that has one.
   Measured — removing it moves all six baselines with a trail and nothing else. */
[data-terp="page-breadcrumbs"] {
  display: flex;
  align-items: center;
  min-height: 2rem;
}
/* Title left, the actions slot right, wrapping rather than overflowing when a long
   title meets a wide action cluster. */
[data-terp="page-heading"] {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}
/* The single h1 of the view. margin: 0 is load-bearing — the browser default h1
   margin would otherwise fight the header's own gap. */
[data-terp="page-title"] {
  margin: 0;
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  letter-spacing: 0;
  color: var(--color-neutral-900);
  line-height: 1.3;
}

/* The sign-in screen ------------------------------------------------------- */
/* The one screen an unauthenticated user sees, and the only full-viewport page in
   the package: a 100vh grid centring one card. The reset layer's box-sizing note
   already names this page as the reason it exists — content-box plus 100vh plus
   padding overflows the viewport by exactly the padding, which is a phantom
   scrollbar on a page that fits.

   The buttons fill their group, and that is a rule on the GROUP rather than a prop
   on Button, because it has exactly one consumer in the package. Button declares
   width: fit-content, which is a definite width — so grid stretch does NOT do this
   for free, and dropping the declaration shrinks all four buttons to their labels.
   Two selectors at (0,2,0) against the button's own (0,1,0), same layer, so
   specificity settles it and source order never enters into it. A block prop on
   Button would be a new public API minted for one internal caller; the sheet can
   already reach the thing, which is the test stage 4 set when it deleted Menu's
   style props.

   The separator's ink moves from --color-neutral-500 to --color-fg-subtle, which is
   the rest of the migration ec36a2b started rather than a new decision: the two
   tokens are byte-identical in light and dark, and only fg-subtle has a declared
   pairing (subtle-on-surface) for the gate to measure. So the screenshot themes do
   not move and midnight and twilight get the value the gate has been measuring all
   along. The "or" is aria-hidden but it is visible text, so it is held to AA rather
   than treated as an ornament.

   The error line has no specimen and cannot have one: the error is internal state set
   only in a catch, and sso.error needs a real failed callback, which needs a URL the
   lane owns. Its ink is gated statically instead — danger-on-card, declared for this
   surface and measured in all five themes. */
[data-terp="login-view"] {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: var(--space-6);
  background: var(--color-neutral-50);
  font-family: var(--font-family-sans);
  color: var(--color-neutral-900);
}
[data-terp="login-card"] {
  width: 100%;
  max-width: 24rem;
  display: grid;
  gap: var(--space-4);
  padding: var(--space-6);
  background: var(--color-neutral-0);
  border: 1px solid var(--color-neutral-200);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
}
[data-terp="login-brand"] {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-neutral-900);
}
[data-terp="login-title"] {
  margin: 0;
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  letter-spacing: 0;
}
[data-terp="login-form"],
[data-terp="login-sso"] {
  display: grid;
  gap: var(--space-3);
}
[data-terp="login-separator"] {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg-subtle);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
[data-terp="login-separator-rule"] {
  flex: 1;
  border-block-start: 1px solid var(--color-neutral-200);
}
[data-terp="login-error"] {
  margin: 0;
  color: var(--color-status-danger);
  font-size: var(--font-size-sm);
}

/* The profile screen ------------------------------------------------------- */
/* The built-in /profile view: two cards, an avatar tile, and the identity lines.
   Its cards are its own rather than the Card component's — the same declarations on
   a different element — and folding the two together is a component decision, not a
   styling one, so it stays a follow-up rather than riding in on a migration whose
   whole contract is zero pixel movement.

   overflow-wrap on the address is real and unobservable: the workbench session is a
   fixed user whose address is short, so no specimen can paint the case it exists for
   (an address has no spaces to break at, so a long one widens the card past its own
   max-width instead of wrapping). Asserted in the unit test as the marker it keys on;
   there is no picture of it and cannot be until the mock session is variable. */
[data-terp="profile-card"] {
  display: grid;
  gap: var(--space-4);
  padding: var(--space-4);
  max-width: 32rem;
  background: var(--color-neutral-0);
  border: 1px solid var(--color-neutral-200);
  border-radius: var(--radius-lg);
}
/* The initials tile. It is aria-hidden, so axe skips it by design and the declared
   pairing is the only thing measuring its ink: brand-primary-contrast on
   brand-primary is primary-button-label, which the contrast gate holds at AA in all
   five themes. Exactly the shape of NavIcon's fallback tile, which failed at 1.60
   for as long as nothing declared it. */
[data-terp="profile-avatar"] {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 3.5rem;
  height: 3.5rem;
  flex-shrink: 0;
  border-radius: var(--radius-full);
  background: var(--color-brand-primary);
  color: var(--color-brand-primary-contrast);
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-medium);
}
[data-terp="profile-email"] {
  overflow-wrap: anywhere;
}
[data-terp="profile-role"] {
  margin: 0;
  color: var(--color-neutral-600);
}

/* The built-in admin screens ----------------------------------------------- */
/* The packaged /admin views. Three surfaces, and they were invisible to both
   ratchets for the entire migration — which is why they are here rather than in
   0.8.0. The worklist names files with NO marker at all, and every admin view
   rendered none, so it read as a view composition and was excluded on purpose. The
   ledger counts module-scope CSSProperties declarations, and these were four
   call-site literals plus one unannotated object. Neither gate was wrong; both were
   narrower than they looked, and the same commit widens the measure.

   The form box is ONE marker across two files, because UserCreate and GroupCreate
   constrain their form to the same measure — the same surface twice, not two
   surfaces that happen to agree today. */
[data-terp="admin-form"] {
  max-width: 32rem;
}
/* A section heading inside a detail screen: the members list, the permission
   grants. font-size-base rather than the UA default, which for an h2 is LARGER than
   the page's own h1 at font-size-lg — so without this a section outranks the view
   it sits in. */
[data-terp="admin-section-title"] {
  margin: 0;
  font-size: var(--font-size-base);
}
/* The audit event's JSON payload. No font-family: it is a <pre>, so the UA
   stylesheet's monospace already applies and the inline object set none either.

   font-size-sm loses the inline fallback the object carried (0.875rem) and no other
   rule in this sheet has one. The fallback could never fire — tokens.guard.test.ts
   refuses any var() in react-core naming a property the contract does not publish,
   so the token is always there. It recorded an author's doubt, not an option. */
[data-terp="admin-payload"] {
  margin: 0;
  padding: var(--space-3);
  background: var(--color-neutral-100);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  overflow-x: auto;
}

/* Hub cards --------------------------------------------------------------- */
/* This whole family was in terp.state, resting declarations and all, for the same
   reason the icon button's transition was: that is where the hover rules needing it
   live. The resting half belongs here — a layer above is a layer an app's own state
   rule has to out-rank for no reason.

   The hub grid. auto-fit with a min(16rem, 100%) track floor is what makes a hub
   reflow from four columns to one with no media query anywhere, and the min() rather
   than a bare 16rem is what stops a viewport narrower than the track overflowing.
   grid-auto-rows: 1fr with align-items: stretch is what makes every card in a row the
   same height — which is the entire reason HubCard renders placeholder rows, so those
   two decisions are one mechanism split across a rule and a component. */
[data-terp="hubpage-grid"] {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(16rem, 100%), 1fr));
  grid-auto-rows: 1fr;
  gap: var(--space-4);
  align-items: stretch;
  list-style: none;
  margin: 0;
  padding: 0;
}
/* The card is one link. text-decoration and colour are the load-bearing pair here; the
   display and the height are belt, and saying which is which took measuring the whole
   chain in a row taller than the body's floor.

   What actually equalises two cards is ONE declaration, and it is not in this rule:
   hubcard-body's height: 100%. Percentage heights resolve against the nearest block
   container and skip inline boxes, so the body reaches past this anchor to the <li> the
   grid stretched — which is why forcing this anchor to display: inline with height: auto
   changes nothing in either configuration measured (both cards at the 10rem floor, and a
   row stretched to 189px by a long description). Removing the BODY's height: 100% in that
   same stretched row is the one change that shows: the bare card drops to 160 while its
   neighbour stays at 189.

   So these two declarations are kept as documentation of the intent rather than as the
   mechanism, and the one configuration not measured is the router path, where this marker
   is a <span> wrapping the stack's own Link rather than being the anchor itself. */
[data-terp="hubcard-link"],
[data-terp="hubcard"] a {
  text-decoration: none;
  color: inherit;
  display: block;
  height: 100%;
  min-height: 0;
}
/* The card and its body. The visible edge is on the BODY, not on the card: the card is
   the outer <li> and has no border at all. That distinction is what made the hover
   accent edge dead for as long as it was — see the state rules.

   The body's height: 100% is the single declaration that makes two cards in a row the
   same height, and the only one: measured in a row stretched past the 10rem floor,
   removing it drops a bare card to 160 while its neighbour stays at 189, while removing
   the grid's align-items: stretch, its grid-auto-rows: 1fr, the card's own height: 100%
   or the link's display/height changes nothing. Those four restate a default or resolve
   through an ancestor. hub-card-bare is what catches this one, and only because its full
   card is deliberately long enough to set the row height.

   The transition splits three ways, and each half is declared where its property
   lives: box-shadow and transform animate on the card, border-color on the body,
   colour on the title. Two of those were already rules; the title's was inline until
   this commit, which means terp.motion could not reach it and a reduced-motion user
   watched it animate. All three are inside the block's reach now. */
[data-terp="hubcard"] {
  height: 100%;
  min-height: 0;
  transition:
    box-shadow var(--motion-duration-fast) var(--motion-easing-standard),
    transform var(--motion-duration-fast) var(--motion-easing-standard);
}
[data-terp="hubcard-body"] {
  display: grid;
  grid-template-rows: auto minmax(3rem, 1fr) auto;
  gap: var(--space-2);
  height: 100%;
  min-height: 10rem;
  padding: var(--space-4);
  border: 1px solid var(--color-neutral-200);
  border-radius: var(--radius-lg);
  background: var(--color-neutral-0);
  color: var(--color-neutral-900);
  box-sizing: border-box;
  transition: border-color var(--motion-duration-fast) var(--motion-easing-standard);
}
/* -heading, not -title: in this sheet a heading is the BOX holding a title
   (card-heading, dataview-card-heading) and a title is the text box itself
   (card-title, dialog-title, hubcard-title). This is the row. */
[data-terp="hubcard-heading"] {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
/* The icon tile. Its own marker rather than a structural hubcard-heading > span, and
   the reason is that the tile is CONDITIONAL while the title is not: a structural
   selector would move the tile's fill onto whatever else ends up first in that row the
   day the markup changes. fg-accent on brand-primary-soft measures 6.16 / 5.28 / 5.19 /
   5.29 / 7.98, so the glyph clears AA on its own tile in every theme. */
[data-terp="hubcard-icon"] {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  flex-shrink: 0;
  border-radius: var(--radius-md);
  background: var(--color-brand-primary-soft);
  color: var(--color-fg-accent);
}
[data-terp="hubcard-title"] {
  color: var(--color-neutral-900);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  transition: color var(--motion-duration-fast) var(--motion-easing-standard);
}
/* neutral-600 rather than fg-muted, and it is not the tinted-surface case: this text
   sits on the card's own neutral-0 and measures 7.58 / 7.94 / 7.50 / 7.60 / 18.42. */
[data-terp="hubcard-description"] {
  color: var(--color-neutral-600);
  font-size: var(--font-size-sm);
  line-height: 1.5;
}
[data-terp="hubcard-stat"] {
  color: var(--color-neutral-900);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
}
/* The placeholder rows. The span still renders, carrying a non-breaking space, so its
   grid row keeps its height and a bare card stays flush with a full one — but that is the
   MARKUP's doing, not this rule's. This rule is invisible to every lane and it is not an
   oversight: a non-breaking space paints nothing, so a hidden placeholder and a visible
   one are pixel-identical. Measured — width 557 and height 89 either way.

   Which leaves exactly one reason for the declaration, and it is the reason it must be
   visibility rather than opacity: visibility: hidden also removes the text from the
   accessibility tree. Without it a screen reader reaches a card and announces a blank
   row. No screenshot and no axe run can see that, so the gate is a text assertion.

   Two markers and one rule: the shape is identical and there is nothing true of the stat
   here that is not true of the description. */
[data-terp="hubcard-description"][data-empty="true"],
[data-terp="hubcard-stat"][data-empty="true"] {
  visibility: hidden;
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
  color: var(--color-fg-subtle);
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
  color: var(--color-fg-subtle);
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
   1.42-2.36:1 across the surfaces a bordered control sits on in four themes — below
   the 3:1 SC 1.4.11 asks of a control boundary. Still not fixed here, because a token
   clearing 3:1 repaints every bordered control in the package, but no longer only a
   sentence: control-boundary-on-surface and control-boundary-on-canvas are declared
   pairings held at their measured floors by BELOW_UI in tokens.contrast.test.js, so
   the debt can only shrink and emptying that table is the acceptance criterion. */
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
  color: var(--color-fg-subtle);
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
  color: var(--color-fg-subtle);
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

   The ink is --color-fg-muted rather than the --color-fg-subtle every other
   subdued surface in this sheet takes, and that is a contrast fix rather than a
   preference. A card's background is whichever soft tone getRowTone returned, and
   subtle fails WCAG AA against three of the six surfaces this text can land on:
   measured, light neutral-100 4.34, light info-soft 4.46 and light danger-soft
   4.35. fg-muted is 6.10 at its worst across all five themes, and carries the
   same value as --color-neutral-600 in every one of them, so this costs nothing
   but the name.

   Worth knowing HOW that was found, because the lesson is about the lane rather
   than the colour. The numbers in the next sentence are the raw
   --color-neutral-500 step this rule originally carried — four failures rather
   than three, because midnight's neutral-500 (#7d8590) sits below the fg-subtle
   its palette lifts it to (#8b949e) and took info-soft to 4.12. This layout had
   no specimen at all, so the pairing had never been rendered for axe to measure;
   the first card specimen failed immediately.
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
  color: var(--color-fg-subtle);
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
  color: var(--color-fg-subtle);
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
  color: var(--color-fg-subtle);
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

/* Resource list ------------------------------------------------------------ */
/* The plain listing screen: a write-gated create row, then the rows. The DataView is
   the same job at scale, and this one stays deliberately simple, so its rules are
   geometry plus two inks.

   The create row keeps its flex layout and the input keeps flex: 1 as a RULE rather
   than becoming a 1fr auto grid, and that is a move rather than a decision. With
   flex: 1 the input's basis is 0 so it may shrink below its intrinsic width; a 1fr
   track floors at min-content instead. The two agree at this list's 40rem cap, so
   swapping them would have changed nothing anybody could see until some narrower
   container found the difference — which is the kind of diff this migration exists
   not to introduce.

   Neither paragraph resets its margin, and that is verbatim rather than an
   oversight: both are <p> elements whose default margin is what separates them from
   the form above and the rows below. Adding margin: 0 here would move the rows. */
[data-terp="resource-list"] {
  display: grid;
  gap: var(--space-4);
  max-width: 40rem;
}
[data-terp="resource-list-create"] {
  display: flex;
  gap: var(--space-2);
}
[data-terp="resource-list-create"] > [data-terp="input"] {
  flex: 1;
}
[data-terp="resource-list-error"] {
  color: var(--color-status-danger);
}
[data-terp="resource-list-empty"] {
  color: var(--color-neutral-600);
}
[data-terp="resource-list-items"] {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-2);
}
[data-terp="resource-list-row"] {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-neutral-200);
  border-radius: var(--radius-md);
  background: var(--color-neutral-0);
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
  color: var(--color-fg-subtle);
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
  color: var(--color-fg-subtle);
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
  color: var(--color-fg-subtle);
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
  color: var(--color-fg-subtle);
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
  color: var(--color-fg-subtle);
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
  transition:
    background-color var(--motion-duration-fast) var(--motion-easing-standard),
    color var(--motion-duration-fast) var(--motion-easing-standard),
    box-shadow var(--motion-duration-fast) var(--motion-easing-standard);
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
  transition:
    background-color var(--motion-duration-fast) var(--motion-easing-standard),
    color var(--motion-duration-fast) var(--motion-easing-standard);
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
  color: var(--color-fg-subtle);
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

/* Icon-only buttons. Sixteen elements wear this marker and not one declares a
   transition inline, so this belongs in terp.base — it sat in terp.state only
   because that is where the hover rules needing it live. Same correction 817f572
   made for Tabs and Breadcrumbs. */
[data-terp="iconbutton"] {
  transition:
    background-color var(--motion-duration-fast) var(--motion-easing-standard),
    color var(--motion-duration-fast) var(--motion-easing-standard),
    box-shadow var(--motion-duration-fast) var(--motion-easing-standard);
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

   The arithmetic is no longer only recorded here. token-pairs.json now carries a
   nonTextPairs section, and the ring is measured in it at 3:1 in every theme, so it
   cannot silently return to what it was. One entry rather than two: focus-ring-on-canvas
   holds the accent against the canvas, while the ring on a card is the same pair of
   tokens as the TEXT pairing accent-on-surface, which already holds them to 4.5 and so
   would go red first. What stays prose is the halo: the box-shadow is reinforcement around the
   opaque outline rather than the indicator itself, and declaring a ratio WCAG does
   not ask for is how a data file teaches people to ignore it. */
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
/* A loading button IS disabled — the component sets both — so this has to sit here rather
   than in terp.base beside the other attribute-keyed button rules. In terp.base it would
   lose to the :disabled rule above on layer order and the cursor would silently stay
   not-allowed, which reads as "you may not" where the truth is "not yet". Declared after
   it so source order settles the tie the equal (0,2,0) specificity leaves.

   Neither cursor is visible to any lane: Playwright's screenshots do not paint a pointer.
   The computed lane asserts both. */
[data-terp="button"][data-loading="true"] {
  cursor: progress;
}

/* Icon-only buttons: the shell's two header toggles, four pagination arrows, the
   toast dismisser, the combobox's clear button, the calendar's two month arrows,
   the DataView's expand toggle, the view-options panel's two reorder arrows, and
   the DataView toolbar's clear-search button and two layout toggles.
   SIXTEEN SITES sharing a transition and nothing else — no shared SURFACE, because
   each is styled by where it sits. Sites rather than elements: the reorder arrows
   render twice per column row, so the element count is a function of how many
   columns a view has, while the list of places to check is fixed.

   The list matters because the escalations here retired per consumer, and an
   incomplete list is the input a future reader uses to decide whether a new one is
   needed. It is also the thing most likely to go stale, and it did: this count sat
   at eleven, then thirteen, while the toolbar added three wearers in a commit that
   updated none of the five places the number is written down. Grep for the number
   word before trusting it: a comment-stripped scan for the marker attribute itself is
   the only authority.

   THE HOVER PAIR NO LONGER SHOUTS, and the component that was why is the one that
   just migrated: AppShell's toggleStyle declared background and colour inline on the
   shell's two toggles, the last two elements wearing this marker able to out-rank a
   layered rule. Their resting look is a scoped base rule now
   ([data-terp="appshell-header"] > [data-terp="iconbutton"] and the drawer's brand row),
   so this rule wins on LAYER instead — terp.state over terp.base — whatever its
   specificity. These were the last two escalations in the sheet.

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

   Safe by enumeration rather than by hope: aria-pressed appears at exactly two
   sites in the whole package, and both of them ARE these toggles — no header toggle,
   pager arrow, month arrow, reorder arrow, toast dismisser or combobox clear button
   carries it, so every other element wearing this marker keeps its hover unchanged.
   It was three until the search-scope control stopped claiming to be a toggle button
   when what it actually does is swap its label. That the enumeration got smaller
   rather than larger is the useful direction: this guard is safe for a reason that
   has to be re-derived whenever a component gains the attribute.

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
  background: var(--color-neutral-100);
  color: var(--color-neutral-900);
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
  color: var(--color-fg-subtle);
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
  color: var(--color-fg-subtle);
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
  color: var(--color-fg-subtle);
}

/* Sidebar navigation links (from the shell or any app-provided <a>).

   THE LAST TWO NAV ESCALATIONS ARE GONE. Their consumer was NAV_LINK_STYLE, the
   CSSProperties object AppShell exported for every router's link renderer to spread onto
   its own link element — colour and background inline on the very elements this selector
   matches, so nothing but !important could reach them. The resting look is a base rule
   now and the exported constants no longer exist.

   The hover skips the active route (aria-current="page") so the brand-soft active
   highlight is not washed out on hover, and that same attribute is what carries the
   active look at all now that NAV_LINK_ACTIVE_STYLE is gone. It is not a shell attribute:
   every router sets it on the link it considers current, which is exactly the kind of
   reuse the breadcrumb case sanctions — the caller owns the element and the attribute, and
   the shell owns only where it sits.

   The rail's scrollbar suppression moved from an attribute on the nav to the sidebar's,
   because collapsed is one fact and it now has one owner. */
[data-terp="appshell-nav"] a:hover:not([aria-current="page"]) {
  background: var(--color-neutral-100);
  color: var(--color-neutral-900);
}
[data-terp="appshell-nav"] a[aria-current="page"] {
  background: var(--color-brand-primary-soft);
  color: var(--color-fg-accent);
  font-weight: var(--font-weight-semibold);
}
[data-terp="appshell-sidebar"][data-collapsed="true"] [data-terp="appshell-nav"] {
  overflow-x: hidden;
  scrollbar-width: none;
}
[data-terp="appshell-sidebar"][data-collapsed="true"] [data-terp="appshell-nav"]::-webkit-scrollbar {
  width: 0;
  height: 0;
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

/* Module navigation ------------------------------------------------------- */
/* Which sub-page you are on, here for the same reason the selected tab is: the
   accent edge and the darker ink have to beat the resting pair.

   Keyed on data-active, which ModuleNav writes, and deliberately NOT on the
   aria-current the same element also carries. That attribute has a second author:
   TanStack's link props spread the router's own active props LAST, after the
   caller's, so on a Link the router has the final word on aria-current. This is
   the breadcrumb lesson in its exact form — reuse a semantic only where the
   component is its sole author.

   The two notions of "active" are not the same predicate, and they diverge in BOTH
   directions, which is worth knowing before touching either. activeOptions
   .includeSearch defaults to true, so the router additionally demands an exact
   query-string match that ModuleNav does not — the router is narrower there. And
   with exact matching the router compares through exactPathTest, which is
   removeTrailingSlash(a) === removeTrailingSlash(b), while ModuleNav compares
   pathname === item.to raw — so on a path with a trailing slash the ROUTER is
   active and ModuleNav is not, and this rule withholds the accent edge from a tab
   the router considers current. That second case is a real defect and it is older
   than this rule: the inline styling it replaced read the same isActive, so the
   behaviour is unchanged and only the reasoning was wrong. Fixing the predicate
   belongs with the navigation model, because that is what decides what "active"
   should mean. */
[data-terp="module-nav-link"][data-active="true"] {
  color: var(--color-neutral-900);
  border-block-end-color: var(--color-fg-accent);
}

/* Hub cards --------------------------------------------------------------- */
/* The hover edge recolours hubcard-BODY, not the card.

   The rule here used to set border-color on [data-terp="hubcard"], which is the outer <li>
   and has no border: HubPage puts the visible edge on the inner hubcard-body span. So the
   accent edge — clearly the intent, since the title goes accent and the card lifts and gains
   a shadow at the same moment — never painted. Measured in a browser rather than reasoned
   about, because no baseline captures a hover: the li computed border 0px none at rest and
   0px none in the accent colour on hover, while the shadow and the transform did apply.

   BOTH ESCALATIONS ARE GONE, and this file was the condition for both. hubcard-body's
   border and hubcard-title's colour were declared inline in HubPage, on the very elements
   these two selectors match, so no layered rule could reach them at any specificity. Both
   surfaces take their base from terp.base now, so layer order alone is enough. Two of the
   seven, and neither could have retired one commit earlier. */
[data-terp="hubcard"]:hover {
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}
[data-terp="hubcard"]:hover [data-terp="hubcard-body"] {
  border-color: var(--color-fg-accent);
}
[data-terp="hubcard"]:hover [data-terp="hubcard-title"] {
  color: var(--color-fg-accent);
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
   NON-TEXT pairing, and token-pairs.json now has a section for it: active-toggle-border
   holds the accent against the neutral-100 fill at 3:1 in every theme. The border against
   the BAND is not a second entry — those are the same two tokens as the text pairing
   accent-on-surface, held there to 4.5, so the numbers above are one pairing seen from two
   sides and the stricter side already gates it. The 1.10 fill is deliberately not declared,
   for the same reason the focus halo is not.

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
   rule above: of the sixteen sites wearing that marker only six can be disabled at
   all — these four and the view-options panel's two reorder arrows, which carry
   their own scoped ink below for the same reason — and giving the shared rule a
   colour would change how a disabled calendar arrow looks the day one becomes
   disableable. The shared rule supplies the opacity and the cursor; this supplies
   the ink the pager had inline. */
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
  transition: background-color var(--motion-duration-fast) var(--motion-easing-standard);
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
   it. Breadcrumb links are such a case and are listed, and so are the shell's
   nav links, whose element belongs to the caller's router.

   THE LAST ESCALATION IN THE SHEET IS GONE, and it was the widest. Its
   consumers were the three inline transitions left in the package: the shell's
   nav-link transition (NAV_LINK_STYLE), the hub card title's (titleTextStyle)
   and the sidebar's own transition: width. The first two are rules now; the
   third was the documented escape — the aside carried no marker, so nothing
   here matched it and a reduced-motion user watched the rail animate — and it
   is closed by the sidebar taking a marker and its width becoming a rule. With
   no style attribute left to out-shout, layer order alone wins: terp.motion
   sits above terp.base and terp.state, so transition: none needs nothing
   shouted. Measured, not assumed: under prefers-reduced-motion the sidebar,
   a nav link and a hub card title all compute transition-duration 0s. */
@media (prefers-reduced-motion: reduce) {
  [data-terp],
  [data-terp="appshell-nav"] a,
  [data-terp="breadcrumbs"] a,
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
