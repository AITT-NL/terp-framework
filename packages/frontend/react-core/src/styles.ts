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

import { WIDE_VIEWPORT_QUERY } from "./breakpoints";

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
/* The comfortable island, which ADR 0094 deferred "until something asks" — and the shell
   taking a density of its own is what asked. DataView's own docstring names the gap: inside an
   already-compact subtree, density="comfortable" did not make anything comfortable, because
   comfortable was the ABSENCE of an attribute and absence cannot override an ancestor.
   That was fine while nothing could put a DataView inside a compact subtree. With
   AppShell density="compact" it becomes a legal prop combination that silently does nothing —
   the shape this phase keeps refusing, most recently in Select's options union. (A running tally
   lived here and in four other places, and two of them said three. A citation keeps.)
   The mechanism is the compact rule mirrored, and it works through INHERITANCE rather than
   specificity: the nearest ancestor carrying either attribute sets the live tokens for its
   subtree, so an island simply re-sets them. The two selectors never match the same element,
   so they never compete. Unlayered for the compact rule's reason — inside a layer it would
   tie with the contract's own unlayered :root values whenever the attribute lands on <html>,
   which is what the :root-qualified copies below settle.
   The values are the :root values by construction, so stamping comfortable where nothing is
   compact computes exactly what it computed before: provably zero-diff. */
/* Each selector is written twice, and the :root-qualified copy is the load-bearing one. The
   contract declares these same custom properties on :root, unlayered, at (0,1,0) — and a
   bare [data-density="..."] on <html> is ALSO (0,1,0), so the two tied and only the order
   the two sheets happened to load decided the winner. A production build extracts tokens.css
   to a <link> that precedes the injected sheet, so react-core won by construction and the
   exposure was the dev server and any host loading the tokens late. :root[data-density] is
   (0,2,0) and wins outright; the unqualified copy stays for a density island on a subtree,
   where there is no :root to qualify and nothing to compete with. */
:root[data-density="comfortable"],
[data-density="comfortable"] {
  --density-control-min-height: var(--density-comfortable-control-min-height);
  --density-cell-pad-y: var(--density-comfortable-cell-pad-y);
  --density-cell-pad-x: var(--density-comfortable-cell-pad-x);
}
:root[data-density="compact"],
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
  /* The list reset both of these primitives document a use for and neither had. as="ul" is
     offered by Stack and Grid alike, and a <ul> arrives with a 40px inline padding and a
     marker per child from the UA sheet — so the documented use rendered bulleted and indented.
     hubpage-grid and resource-list-items already carry exactly this, because both are always
     lists; these two are lists only when asked, which is why it was missed. A no-op on a div,
     and the data-padding rules outweigh it at (0,2,0) when an inset is asked for. */
  padding: 0;
  list-style: none;
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
/* Padding, the dimension Stack did not have — which is why a padded region was reachable
   only through a Card, whose border and background came along whether or not they were
   wanted. A step on the same token scale as gap, so there are no arbitrary insets. */
[data-terp="stack"][data-padding="0"] { padding: var(--space-0); }
[data-terp="stack"][data-padding="1"] { padding: var(--space-1); }
[data-terp="stack"][data-padding="2"] { padding: var(--space-2); }
[data-terp="stack"][data-padding="3"] { padding: var(--space-3); }
[data-terp="stack"][data-padding="4"] { padding: var(--space-4); }
[data-terp="stack"][data-padding="6"] { padding: var(--space-6); }
[data-terp="stack"][data-padding="8"] { padding: var(--space-8); }
/* The wide half of a responsive Stack. This block must stay AFTER the rules above and not
   merely above the Grid family: a stack with direction {narrow: "row", wide: "column"}
   carries both data-direction="row" and data-direction-wide="column", and the two selectors
   weigh the same (0,2,0), so nothing but source order decides which wins above the cutover.
   Same for every gap pair. styles.test.ts pins the order, because getting it backwards
   renders the narrow value at every width and looks like the prop not working.

   The query is INTERPOLATED from ./breakpoints, which is the one \${…} in this sheet and is
   deliberate rather than a slip: it is the complement of the exact string AppShell and
   DataView hand to matchMedia, so the two halves of the cutover partition the viewport by
   construction. Written out here they would be two literals that agree until someone edits
   one. (The convention of grepping this literal for \${ still holds — there should be
   exactly this one.) */
@media ${WIDE_VIEWPORT_QUERY} {
  [data-terp="stack"][data-direction-wide="column"] { flex-direction: column; }
  [data-terp="stack"][data-direction-wide="row"] { flex-direction: row; }
  [data-terp="stack"][data-gap-wide="0"] { gap: var(--space-0); }
  [data-terp="stack"][data-gap-wide="1"] { gap: var(--space-1); }
  [data-terp="stack"][data-gap-wide="2"] { gap: var(--space-2); }
  [data-terp="stack"][data-gap-wide="3"] { gap: var(--space-3); }
  [data-terp="stack"][data-gap-wide="4"] { gap: var(--space-4); }
  [data-terp="stack"][data-gap-wide="6"] { gap: var(--space-6); }
  [data-terp="stack"][data-gap-wide="8"] { gap: var(--space-8); }
  /* The split's two columns, at the one cutover the chrome around it already uses.
     Three list tracks, three rules, no length ever handed in as a style — the listWidth
     prop is a step for the reason Grid's minColumn is (ADR 0097 §4). The detail track is
     minmax(0, 1fr) so it takes the remainder and still lets a wide table scroll inside
     itself rather than widening the row. */
  [data-terp="splitpage-panes"][data-list-width="sm"] {
    grid-template-columns: minmax(0, 18rem) minmax(0, 1fr);
  }
  [data-terp="splitpage-panes"][data-list-width="md"] {
    grid-template-columns: minmax(0, 24rem) minmax(0, 1fr);
  }
  [data-terp="splitpage-panes"][data-list-width="lg"] {
    grid-template-columns: minmax(0, 32rem) minmax(0, 1fr);
  }
  /* DetailList's multi-column half. Mobile-first, like SplitPage's panes above: the narrow
     shape is one column with the term as a block above its value, which is the BASE rule and
     therefore needs no query at all — this block is only the widths at which a shared label
     column, or two pairs per row, fit.

     They ran at every width before, and 430px is where that showed: four tracks in ~370px, and
     detail-list-value's overflow-wrap: anywhere then broke words mid-token rather than letting
     a value have its own line. The anywhere is right — it is what stops an unbreakable digest
     overflowing its column — so the fix is to stop asking a phone to hold four tracks.

     Why a viewport query and not a container query, which would be the more nearly right
     instrument: container queries appear nowhere in this sheet, so introducing one for a single
     component is a mechanism change that wants its own record rather than a line in a defect
     fix, and the cutover the framework already has covers the width the failure was measured
     at. It is also why DetailList reflows itself while Grid deliberately refuses to for a fixed
     column count — Grid publishes columns="auto" as its responsive answer, and DetailList's
     closed one-or-two has no such escape, so the reflow has to be the component's own.

     PLACEMENT: the detail-list base rules are declared ~100 lines BELOW this block, so source
     order cannot settle these. Specificity does, and deliberately: every selector here carries
     the marker plus at least one attribute (0,2,0) against the base rule's (0,1,0). That is
     exactly how splitpage-panes above already wins over its own base rule further down, and
     styles.test.ts pins the property, because a reader cannot see it from the rule. The one
     thing this block must NOT declare is row-gap: that belongs to the gap prop, whose roll-call
     weighs the same (0,2,0) and is therefore declared later on purpose. */
  [data-terp="detail-list"][data-columns="2"] {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    column-gap: var(--space-4);
  }
  /* minmax(0, max-content) rather than a bare auto for the label track. An auto track floors
     at min-content, which makes it the one track in this component that was never floored at
     zero — so a label with nothing to break on widened the column and pushed the list past its
     container, the same failure the value track's minmax(0, 1fr) was written to stop. Capping at
     max-content also stops the label column claiming width no label is using: measured in a
     565px card, two independently-sized auto label tracks left a value track of ~400px holding
     ~60px of text. */
  [data-terp="detail-list"][data-layout="aligned"] {
    grid-template-columns: minmax(0, max-content) minmax(0, 1fr);
    column-gap: var(--space-3);
  }
  [data-terp="detail-list"][data-layout="aligned"][data-columns="2"] {
    grid-template-columns: repeat(2, minmax(0, max-content) minmax(0, 1fr));
  }
  /* display: contents is what makes the dt and dd grid items of the dl itself, so labels align
     ACROSS rows without a DOM change — and it belongs in here rather than in the base rules
     because it is the mechanism of the shared column, which exists only above the cutover.
     Narrow, the row wrapper stays a block and each pair reads as two lines. */
  [data-terp="detail-list"][data-layout="aligned"] [data-terp="detail-list-row"] {
    display: contents;
  }
}

/* Grids -------------------------------------------------------------------- */
/* The two-dimensional primitive. The base rule is the DEFAULT shape — auto-fit at the
   sm track floor, stretched cells — so the three defaults match no attribute, exactly
   as density's "comfortable" and Button's md do.

   min(16rem, 100%) rather than a bare 16rem, and the min() is load-bearing rather than
   defensive: a bare floor wider than the container makes the single track overflow it,
   so a grid in a narrow panel would scroll sideways instead of going one-column. Same
   mechanism the hub grid uses, and the same 16rem, so the two agree by construction
   rather than by coincidence.

   The four floors are rem literals rather than tokens on purpose. They are a design
   scale with exactly one consumer today, and vocabulary published before something
   reads it gets retired here — the four density cell tokens were deleted for precisely
   that and came back with their readers. They become tokens the day an app asks to move
   them, which is also when a compact counterpart would have to be decided. */
[data-terp="grid"] {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(16rem, 100%), 1fr));
  gap: var(--space-4);
  align-items: stretch;
  min-width: 0;
  margin: 0;
  /* See the note on stack above: the same reset, for the same documented as="ul". */
  padding: 0;
  list-style: none;
}
[data-terp="grid"][data-min-column="xs"] {
  grid-template-columns: repeat(auto-fit, minmax(min(10rem, 100%), 1fr));
}
[data-terp="grid"][data-min-column="md"] {
  grid-template-columns: repeat(auto-fit, minmax(min(20rem, 100%), 1fr));
}
[data-terp="grid"][data-min-column="lg"] {
  grid-template-columns: repeat(auto-fit, minmax(min(26rem, 100%), 1fr));
}
/* A fixed count. minmax(0, 1fr) rather than a bare 1fr, because 1fr floors at the
   track's min-content size — so one long unbroken word in a cell widens its column and
   the grid overflows its container, which is the failure a two-column form of long field
   labels walks straight into. */
[data-terp="grid"][data-columns="1"] { grid-template-columns: minmax(0, 1fr); }
[data-terp="grid"][data-columns="2"] { grid-template-columns: repeat(2, minmax(0, 1fr)); }
[data-terp="grid"][data-columns="3"] { grid-template-columns: repeat(3, minmax(0, 1fr)); }
[data-terp="grid"][data-columns="4"] { grid-template-columns: repeat(4, minmax(0, 1fr)); }
[data-terp="grid"][data-gap="0"] { gap: var(--space-0); }
[data-terp="grid"][data-gap="1"] { gap: var(--space-1); }
[data-terp="grid"][data-gap="2"] { gap: var(--space-2); }
[data-terp="grid"][data-gap="3"] { gap: var(--space-3); }
[data-terp="grid"][data-gap="4"] { gap: var(--space-4); }
[data-terp="grid"][data-gap="6"] { gap: var(--space-6); }
[data-terp="grid"][data-gap="8"] { gap: var(--space-8); }
[data-terp="grid"][data-align="start"] { align-items: start; }
[data-terp="grid"][data-align="center"] { align-items: center; }
[data-terp="grid"][data-align="end"] { align-items: end; }
[data-terp="grid"][data-padding="0"] { padding: var(--space-0); }
[data-terp="grid"][data-padding="1"] { padding: var(--space-1); }
[data-terp="grid"][data-padding="2"] { padding: var(--space-2); }
[data-terp="grid"][data-padding="3"] { padding: var(--space-3); }
[data-terp="grid"][data-padding="4"] { padding: var(--space-4); }
[data-terp="grid"][data-padding="6"] { padding: var(--space-6); }
[data-terp="grid"][data-padding="8"] { padding: var(--space-8); }

/* Detail lists ------------------------------------------------------------- */
/* The term and value are inline boxes inside a block row, which is what makes
   "Label: value" read as one line and wrap as one paragraph. */
[data-terp="detail-list"] {
  margin: 0;
  display: grid;
  gap: var(--space-1);
  grid-template-columns: minmax(0, 1fr);
}
[data-terp="detail-list-row"] {
  min-width: 0;
}
[data-terp="detail-list-term"] {
  display: inline;
  font-weight: var(--font-weight-medium);
}
/* The colon belongs to the inline layout alone, so it is a rule rather than a text node —
   aligned and stacked must not have one, and no rule can withdraw a text node. Decorative
   either way: the dt/dd pairing is what carries the relationship to assistive tech. */
[data-terp="detail-list"]:not([data-layout]) [data-terp="detail-list-term"]::after {
  content: ": ";
  white-space: pre;
}
[data-terp="detail-list-value"] {
  display: inline;
  margin: 0;
  min-width: 0;
  /* Flooring the track at 0 is not enough on its own, and the specimen is what showed it: a
     64-character digest has nothing to break at, so it overflows the column whatever the
     column's floor. This is the declaration that makes it wrap. Same answer profile-email
     already uses for a long address — where it is noted as unobservable, because that
     screen's session is a fixed short one; detail-list-long-value is the first picture of
     the mechanism anywhere in the suite. */
  overflow-wrap: anywhere;
}
/* The tracks for two pairs per row, and for aligned, live in the wide-viewport block above
   rather than here: one column is the narrow shape and therefore the base. What stays here is
   everything that holds at every width.

   Both non-inline layouts open their rows to --space-3. At the base --space-1 the distance
   WITHIN a pair and the distance BETWEEN pairs were the same 4px, so a card of five labelled
   values had nothing grouping it — five pairs read as ten equally-spaced lines. inline keeps
   --space-1, because there a pair IS one line of a paragraph and 4px is the leading between
   lines of one block; opening it would space out a run of sentences.

   row-gap rather than gap, and the distinction is load-bearing: the column gap in aligned is
   the label-to-value distance, and at two pairs per row it is the space between pair groups —
   both owned by the rules in the wide block. A shorthand here would silently reset them. */
[data-terp="detail-list"][data-layout="aligned"],
[data-terp="detail-list"][data-layout="stacked"] {
  row-gap: var(--space-3);
}
[data-terp="detail-list"][data-layout="aligned"] [data-terp="detail-list-term"],
[data-terp="detail-list"][data-layout="aligned"] [data-terp="detail-list-value"],
[data-terp="detail-list"][data-layout="stacked"] [data-terp="detail-list-term"],
[data-terp="detail-list"][data-layout="stacked"] [data-terp="detail-list-value"] {
  display: block;
}
/* The label takes the muted, smaller, regular step so a pair reads as one unit rather than two
   lines of equal weight — and aligned shares the rule rather than getting a second treatment
   of its own. It did not, and that was the defect: an aligned term measured 16px / weight 500 /
   near-black, which is the value's own typography, so a card of five labelled values rendered
   as a wall of bold text with nothing telling a reader which half to read first.

   inline is deliberately NOT here. There the term is half a sentence — the colon comes from
   the ::after above — and muting half a sentence is a different defect from the one this fixes.
   Two layouts diverging was the bug; three converging would be another. */
[data-terp="detail-list"][data-layout="aligned"] [data-terp="detail-list-term"],
[data-terp="detail-list"][data-layout="stacked"] [data-terp="detail-list-term"] {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-normal);
  color: var(--color-fg-muted);
}
/* The gap prop, and this block must stay AFTER the layout rules above. Both
   [data-terp="detail-list"][data-gap="3"] and [data-terp="detail-list"][data-layout="aligned"]
   weigh (0,2,0), so nothing but source order decides which row-gap a list carrying both
   attributes renders — backwards, the prop silently does nothing, which looks like the prop not
   working rather than like a cascade mistake. The same tie the responsive Stack rules turn on,
   pinned the same way in styles.test.ts.

   row-gap only, for the reason the layout rules above give. The prop is documented as the
   distance BETWEEN pairs, and the column gap stays the layout's. */
[data-terp="detail-list"][data-gap="0"] { row-gap: var(--space-0); }
[data-terp="detail-list"][data-gap="1"] { row-gap: var(--space-1); }
[data-terp="detail-list"][data-gap="2"] { row-gap: var(--space-2); }
[data-terp="detail-list"][data-gap="3"] { row-gap: var(--space-3); }
[data-terp="detail-list"][data-gap="4"] { row-gap: var(--space-4); }
[data-terp="detail-list"][data-gap="6"] { row-gap: var(--space-6); }
[data-terp="detail-list"][data-gap="8"] { row-gap: var(--space-8); }

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
/* start rather than center once there is a description, and the condition is the whole point.
   With a title alone, center is right: the actions slot is a control, so its box is
   --density-control-min-height tall against a single line box, and start would leave the title
   riding above it. With two or three lines of description the same declaration floats the
   control in the middle of the block instead of beside the title it belongs to.

   :has() rather than an attribute Card could stamp, for the reason control-label's disabled
   states use it (see the note there): the header has no idea what its heading holds, and the
   alternative is a prop describing the DOM back to the sheet. Specificity (0,2,0) beats the
   base rule above, so this does not depend on its position. */
[data-terp="card-header"]:has([data-terp="card-description"]) {
  align-items: start;
}
/* flex: 1 1 0, and the base size is the load-bearing half. Left at the initial 0 1 auto, the
   heading's hypothetical main size is the max-content width of a block holding a title AND a
   sentence of description — and flex breaks lines on hypothetical main sizes BEFORE it shrinks
   anything, so with flex-wrap above the heading claimed the whole line and the actions slot
   wrapped underneath it. Measured: a 103px header with the button below the description, where
   the same component with no description rendered inline at 48px. Same prop, two results,
   depending on whether a sibling prop was set.

   A base size of 0 means both items fit on one line by construction, and the heading then grows
   into whatever the actions slot does not use. min-width: 0 stays for the other half of that
   story: a flex item's automatic minimum size is its content's, so a long unbreakable word in a
   title would otherwise refuse to shrink past it. */
[data-terp="card-heading"] {
  flex: 1 1 0;
  min-width: 0;
}
/* Chrome off, heading kept. Three declarations removed rather than a second component
   with six markers of its own describing the same DOM: a titled region inside something
   that is already a surface wants no second border, and the commonest instance is a
   section whose body is a DataView — boxed, the table gets a border inside a border and
   loses the full width its own scroll container gives it.

   padding: 0 rather than dropping the declaration, because the base rule sets it and an
   absent value inherits nothing useful. */
[data-terp="card"][data-variant="plain"] {
  background: none;
  border-color: transparent;
  padding: 0;
}

/* Prose --------------------------------------------------------------------- */
/* The first readers of the published type scale. --font-line-height-* and
   --font-letter-spacing-* shipped in 0.7.0 with nothing reading them, and unlike the
   motion family they could not simply be wired in: this sheet writes line heights of
   1.2, 1.25, 1.3, 1.4 and 1.5, and the scale offers 1.2, 1.35, 1.5 and 1.7 — so only 8
   of 32 literals map, and converting the rest would change rendered line heights across
   a dozen components. That is a typography pass with its own baselines. New components
   have nothing depending on their metrics, so they take the published scale and the
   family gets honest consumers; tokens.guard.test.ts tracks what is still unread.

   Headings carry no colour: they inherit the page's ink, so a heading inside a tinted
   surface stays legible without a rule per surface. margin: 0 because the browser
   default fights the parent's gap, which is the same reason page-title and card-title
   both declare it. */
[data-terp="heading"] {
  margin: 0;
  font-family: var(--font-family-sans);
  font-weight: var(--font-weight-semibold);
  line-height: var(--font-line-height-tight);
  letter-spacing: var(--font-letter-spacing-tight);
}
[data-terp="heading"][data-size="sm"] {
  font-size: var(--font-size-sm);
  line-height: var(--font-line-height-snug);
  letter-spacing: var(--font-letter-spacing-base);
}
[data-terp="heading"][data-size="base"] {
  font-size: var(--font-size-base);
  line-height: var(--font-line-height-snug);
  letter-spacing: var(--font-letter-spacing-base);
}
[data-terp="heading"][data-size="lg"] { font-size: var(--font-size-lg); }
[data-terp="heading"][data-size="xl"] { font-size: var(--font-size-xl); }

/* Body copy. The base rule is the default tone and step, so neither stamps an
   attribute. A measure is capped in ch rather than rem, because the readable line
   length is a count of characters and follows the font size — in rem it would stop
   being a measure the moment an app changed the type scale. */
[data-terp="text"] {
  margin: 0;
  font-family: var(--font-family-sans);
  font-size: var(--font-size-base);
  line-height: var(--font-line-height-base);
  color: var(--color-fg-default);
}
[data-terp="text"][data-size="xs"] { font-size: var(--font-size-xs); }
[data-terp="text"][data-size="sm"] { font-size: var(--font-size-sm); }
[data-terp="text"][data-size="lg"] {
  font-size: var(--font-size-lg);
  line-height: var(--font-line-height-relaxed);
}
[data-terp="text"][data-tone="muted"] { color: var(--color-fg-muted); }
[data-terp="text"][data-tone="subtle"] { color: var(--color-fg-subtle); }
[data-terp="text"][data-measure="narrow"] { max-width: 48ch; }
[data-terp="text"][data-measure="base"] { max-width: 72ch; }

/* Code. The inline form takes a tinted chip so an identifier reads as one inside a
   sentence; the block form drops the chip — a bordered box around a bordered box again —
   and keeps the border on the <pre>. overflow-x on the block is what makes a long line
   scroll rather than widen the page, and it is the reason the <pre> is focusable: a
   scroll container a keyboard cannot reach cannot be scrolled at all (SC 2.1.1). */
[data-terp="code"] {
  font-family: var(--font-family-mono);
  font-size: 0.875em;
  padding: 0.1em 0.32em;
  border-radius: var(--radius-sm);
  background: var(--color-neutral-100);
  color: var(--color-fg-default);
}
[data-terp="code-block"] {
  margin: 0;
  padding: var(--space-3);
  border: 1px solid var(--color-neutral-200);
  border-radius: var(--radius-md);
  background: var(--color-neutral-50);
  overflow-x: auto;
  font-size: var(--font-size-sm);
  line-height: var(--font-line-height-base);
}
[data-terp="code-block"] [data-terp="code"] {
  padding: 0;
  background: none;
  border-radius: 0;
  font-size: inherit;
}

/* Links. Two selector shapes for one marker, because an in-app link's marker lands on a
   wrapper: navLink accepts { to, children } and nothing else, so the router's own Link
   cannot be handed an attribute. The external case marks the anchor itself. Same shape
   HubCard already uses, for the same reason. */
[data-terp="link"],
[data-terp="link"] a {
  color: var(--color-fg-accent);
  text-decoration: underline;
  text-underline-offset: 2px;
  border-radius: var(--radius-sm);
}

/* Dividers ----------------------------------------------------------------- */
/* An <hr>, so the separation reaches the accessibility tree and not only the pixels.
   Its own border reset first: a bare <hr> comes with a browser border and margin that
   differ between engines, which is most of why a module reaches for a bordered div.

   The vertical form takes its height from its flex or grid line rather than inventing
   one, so it works between the items of a row Stack and is zero-height in a block
   parent. That is worth knowing before reaching for it, and it is why its specimen
   renders inside a fixed-height row — with equal-height siblings there would be nothing
   to see either way. */
[data-terp="divider"] {
  border: 0;
  margin: 0;
  align-self: stretch;
  background: var(--color-neutral-200);
  block-size: 1px;
  inline-size: auto;
}
[data-terp="divider"][data-orientation="vertical"] {
  block-size: auto;
  inline-size: 1px;
}

[data-terp="card-actions"] {
  flex-shrink: 0;
}
/* lg, the step below the page title, for the same reason page-title moved up: at base a
   section heading was typographically indistinguishable from the prose underneath it. */
[data-terp="card-title"] {
  margin: 0;
  font-size: var(--font-size-lg);
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
   is what AppShellLinkContext.style and RenderBrandLink's style param used to be.

   The sidebar paints from its OWN colour family now — --color-sidebar-bg / -fg / -muted /
   -accent / -border — rather than from the neutral ramp. Those five were declared in all five
   themes and read by NOTHING, which is exactly the offence --color-fg-on-brand was deleted
   for; the difference is that here the vocabulary is right and the readers were missing, so
   wiring is the fix and deleting would have been the mistake. It went unnoticed for four
   releases because tokens.guard.test.ts tracked three families and --color- was not one.

   Mostly inert, and recounted rather than estimated: of the twenty-five declarations, FIFTEEN
   already equalled the neutral the sheet was reading — background, foreground and border agree
   in every theme except the light background. Ten move, in three groups.

   The light sidebar goes #ffffff -> #f8fafc, a faint separation from the canvas that the dark
   themes always had and light never did. The nav link's resting ink dims in every theme (light
   #334155 -> #475569, dark #e2e8f0 -> #b4c0d0), which is the deliberate half: a sidebar's
   resting links are secondary to the page and the active one should carry the weight. And the
   hover wash changes in four themes — every one but light, where the two values agree — which
   an earlier version of this comment did not mention at all, because it counted the resting
   declarations and forgot that accent is one of the five.

   Every text pairing was checked before being wired, not after: 7.24:1 light, 7.94 dark, 7.50
   midnight, 7.60 twilight, and 18.42 for contrast against its AAA floor. */
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
  width: var(--shell-sidebar-width-expanded);
  background: var(--color-sidebar-bg);
  border-inline-end: 1px solid var(--color-sidebar-border);
  transition: width var(--motion-duration-fast) var(--motion-easing-standard);
}
[data-terp="appshell-sidebar"][data-collapsed="true"] {
  width: var(--shell-sidebar-width-collapsed);
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
  color: var(--color-sidebar-fg);
  text-decoration: none;
  border-radius: var(--radius-md);
  box-sizing: border-box;
  transition: background-color var(--motion-duration-fast) var(--motion-easing-standard);
}
[data-terp="appshell-sidebar"][data-collapsed="true"] [data-terp="appshell-brand"] {
  justify-content: center;
  padding-inline: 0;
}
/* The brand mark's box (ADR 0098 §9). The brand link used to hand whatever it was given
   straight into a flex row, so an app's asset sized itself and an oversized one was clipped by
   the aside's overflow-x: hidden with nothing to say so — in the 4rem rail, which is exactly
   where a brand most needs to survive. One declared size, published as --shell-brand-size, caps
   it in every placement, and the descendant rule catches the img or svg inside a wrapper rather
   than only a direct child.
   Zero-diff for every shell shipped so far: the default TerpMark is 28px and the token is
   1.75rem, so the box is exactly the size of the thing that used to be the flex item. */
[data-terp="appshell-mark"] {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: var(--shell-brand-size);
  height: var(--shell-brand-size);
}
[data-terp="appshell-mark"] * {
  max-width: 100%;
  max-height: 100%;
}
/* The light/dark pair, and the switch is a token because the alternative rots. The framework
   ships five themes and three of them are dark; a company mark with dark ink is invisible on
   those three, and the bundled icons' currentColor answer is not available to a brand asset.
   Enumerating the dark themes HERE would be a list that goes stale the first time one is added,
   so the token build emits --appearance-show-light / --appearance-show-dark from each theme's
   declared appearance — the same field it already emits color-scheme from, and one
   themes.json requires. A sixth theme cannot forget to answer.
   The values are block / none rather than this rule's own display type, so a theme never has
   to know what layout the shell uses: the box above does the centring, not the mark. */
[data-terp="appshell-mark"] > [data-appearance="light"] {
  display: var(--appearance-show-light);
}
[data-terp="appshell-mark"] > [data-appearance="dark"] {
  display: var(--appearance-show-dark);
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
  color: var(--color-sidebar-fg);
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
/* Navigation groups. The wrapper itself declares nothing in the sidebar: it is a plain block
   containing the same list, which is what makes adding it to the ungrouped case free.

   The separation is on the ADJACENT SIBLING, and these two rules are the first + combinators in
   this sheet. That is deliberate rather than careless: what is wanted is a separation BETWEEN
   siblings, which is exactly what + expresses, and the alternatives are worse here. A gap on the
   nav would make the nav a grid or flex container, and a stretched single row would then resize
   the one group every app has today. A margin on every group would need a :first-child to undo
   it, which is a positional selector where a sibling one says the thing directly. With one group
   neither rule matches at all, so the flat sidebar is untouched to the pixel.

   SCOPED TO THE SIDEBAR, and that scope is load-bearing. In header placement the nav is a flex
   ROW (below), where margin-block-start is a CROSS-axis margin — never collapsed, applied to a
   flex item — so an unscoped rule would push every group after the first down by 1rem and grow
   the sticky header with it. The mobile drawer is the same aside carrying the same marker, so it
   keeps this rule, which is correct: the drawer stacks. */
[data-terp="appshell-sidebar"] [data-terp="appshell-nav-group"] + [data-terp="appshell-nav-group"] {
  margin-block-start: var(--space-4);
}
/* The group label. Not a heading element — see the AppShell render for why the outline is the
   binding constraint and why axe cannot see it.

   The horizontal padding matches the nav link's own (var(--space-3)), so the label sits on the
   same left edge as the icons under it rather than floating in the rail's gutter.

   letter-spacing comes from the published scale rather than a bare literal, and this is the rule
   the scale was waiting for: tokens.guard.test.ts records --font-letter-spacing-wide as unread
   with the comment "for the uppercase-label treatment nothing in the package uses". This is that
   treatment, so the token gets its first reader and leaves the unread list. font-weight is our
   own choice and not inherited from the login separator, which declares none — a group label
   competing with the links under it needs the weight to read as a header rather than as a
   disabled item. */
[data-terp="appshell-nav-group-label"] {
  display: block;
  padding: var(--space-1) var(--space-3);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  letter-spacing: var(--font-letter-spacing-wide);
  text-transform: uppercase;
  color: var(--color-sidebar-muted);
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
  color: var(--color-sidebar-muted);
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
/* Visually hidden, five elements, one rule. One is the skip link, which is the whole point of
   the block for it: hidden at rest and un-hidden by a rule in terp.state. Two are the drawer's
   focus sentinels, which
   must stay focusable and so cannot be display: none. The other two are the brand title
   and the nav labels in the icon rail, which were a style-object TERNARY before this —
   the component picked between two objects per render, and the collapsed branch was
   painted by nothing, because the rail state was internal and no specimen could reach it.
   That is what defaultCollapsed is for. */
[data-terp="appshell-skip-link"],
[data-terp="drawer-focus-start"],
[data-terp="drawer-focus-end"],
[data-terp="appshell-sidebar"][data-collapsed="true"] [data-terp="appshell-brand-title"],
[data-terp="appshell-sidebar"][data-collapsed="true"] [data-terp="appshell-nav-label"],
[data-terp="appshell-sidebar"][data-collapsed="true"] [data-terp="appshell-nav-group-label"] {
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
/* The header's INLINE padding is the content column's gutter, and it is a shared measure
   rather than a value this rule is free to pick. Three boxes stack in the column — this
   header, appshell-main and appshell-footer — and whatever the topmost thing in the page
   is starts at main's padding edge. On a routed view that thing is the breadcrumb trail,
   which is the first child of Page's header, so the trail's left edge IS main's gutter.

   It was var(--space-4) here against var(--space-6) on main and on the footer, which put
   the trail 0.5rem right of the header's own toggle on every desktop shell and lined it up
   with nothing: two of the three boxes already agreed and the header was the outlier. Not a
   clean indent either, which is why it read as broken rather than deliberate — the toggle
   is a 2.25rem box centring a 1em glyph at font-size-sm, so its BOX sat 8px left of the
   trail while its GLYPH sat 3px right of it. On mobile it happened to be correct, because
   main steps down to var(--space-4) there and met the header's fixed value by accident.

   So the two agree at both variants now, deliberately: var(--space-6) here and the mobile
   override below, mirroring main's own base-plus-variant pair. The block padding is
   untouched and stays var(--space-2) under the min-height floor.

   Not unified into one custom property, which was tried first: tokens.guard.test.ts refuses
   a fallback-less var() against anything tokens.css does not declare, so --shell-gutter
   would have to be published as a contract token. That is shell geometry under ADR 0097 §1
   and a new public knob, so it is a decision with a record rather than the fix for this. The
   three values are held equal by a test instead — styles.test.ts, "keeps the content
   column's gutter one measure" — which is what was missing rather than the abstraction.

   No backticks anywhere above, and that is not a style preference: one here terminates
   TERP_STYLES_CSS and the parse then fails somewhere else entirely with "try inserting a
   semicolon". This comment cost that mistake once too, which is twice in one sheet. */
[data-terp="appshell-header"] {
  position: sticky;
  top: 0;
  z-index: var(--z-index-sticky);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-6);
  min-height: var(--shell-header-height);
  box-sizing: border-box;
  background: var(--color-neutral-0);
  border-block-end: 1px solid var(--color-neutral-200);
}
/* The mobile half of that pair. padding-inline only — the block padding is the same at both
   variants, and restating it here would be a second owner for a value that never varies. */
[data-terp="appshell"][data-variant="mobile"] [data-terp="appshell-header"] {
  padding-inline: var(--space-4);
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
/* The drawer's close button sits INSIDE the sidebar, so its INK comes from the sidebar family
   and not from the header toggle's neutral. Everything else it shares with the toggle above —
   both are icon buttons in shell chrome, and only the colour depends on which chrome.
   Wiring the sidebar family without this left two adjacent controls in the same drawer on two
   different ramps: in dark a nav link hovering to #334155 beside a close button hovering to
   #263449, and in contrast a blue wash beside a grey one.
   An override, NOT a split of the rule above. Splitting it was the first attempt and it moved
   the shared declarations into this selector, so the header toggle lost its background, border,
   radius, cursor and type — visible immediately as ~1,160 repainted pixels on every shell
   specimen, which is how a one-line edit to a grouped selector announces itself. */
[data-terp="appshell-brand-row"] > [data-terp="iconbutton"] {
  color: var(--color-sidebar-muted);
}
/* Main and the footer below carry the same inline gutter as the header — see that rule for
   why the three are one measure. Moving this one without moving those two is what put the
   breadcrumb trail 0.5rem off the header for every desktop shell. */
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
/* The header placement (ADR 0098 §8): the nav moves into the header and the sidebar is not
   rendered at all. Three rules, and the attribute is stamped only on desktop and only when the
   prop asked for it, so none of them needs a [data-variant] guard and no existing shell is in
   scope of any of them.

   The header BECOMES the sidebar surface, which is one declaration doing the work of six.
   Every part of the navigation — the brand, its title, the resting link, the hover wash, the
   active link — already reads --color-sidebar-*, so moving the surface carries the whole family
   with it and not one property is overridden here. It is also the only reading that survives
   theming: an app that paints its sidebar navy gets a navy header with the same legible ink,
   where per-property overrides would have given it navy ink on a white header. The declared
   sidebar pairings are therefore still exactly the pairings in play and the contrast gate needs
   nothing new — which is the check that the mechanism is right rather than merely short.

   In the shipped themes this moves almost nothing: --color-sidebar-bg equals
   --color-neutral-0 in four of the five, and in light it is the same #f8fafc the sidebar
   already uses. The rule is load-bearing for an app's theme, not for ours. */
[data-terp="appshell"][data-nav-placement="header"] [data-terp="appshell-header"] {
  background: var(--color-sidebar-bg);
  border-block-end-color: var(--color-sidebar-border);
}
/* The list turns horizontal. Flex rather than a row of grid columns, because the header is
   already a wrapping row: a nav with more items than fit takes a second line and the header
   grows, instead of overflowing to somewhere no pointer can reach. */
[data-terp="appshell"][data-nav-placement="header"] [data-terp="appshell-nav-list"] {
  display: flex;
  flex-wrap: wrap;
}
/* The nav keeps its flex-grow from the sidebar rule, which here takes the slack between the
   brand and the header group and pins the controls right with no margin of its own.
   overflow is a FIX rather than a reset: the sidebar's nav is a vertical scroll container, and
   a computed overflow-y of auto forces overflow-x to auto as well, so in a header — where the
   box is exactly one link tall — a focused link's 2px outline and 3px ring would be clipped on
   both edges by a scroller that can never scroll. */
[data-terp="appshell"][data-nav-placement="header"] [data-terp="appshell-nav"] {
  overflow: visible;
  /* The groups are a ROW here, not a column. Without this each group wrapper is a block and a
     two-group header renders one stacked list per group — a nav placed in the header to avoid
     permanent chrome, growing the header instead.

     The row lives on the NAV rather than on the wrappers because the wrappers are what has to
     line up, and it is why the stacking margin above is scoped away from this placement: a
     block-start margin on a flex item is a cross-axis margin and is never collapsed.

     With one group this changes nothing measurable. The single wrapper becomes a flex item
     sized to its content instead of a full-width block, and its list is laid out from the same
     left edge either way; the existing app-shell-header-nav baseline is what says so. */
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-5);
}
/* A group in the header: its label sits beside its links rather than above them, since a header
   row has no second line to put it on. The gap is the label-to-list separation and nothing
   else — the list keeps its own var(--space-1) between links. */
[data-terp="appshell"][data-nav-placement="header"] [data-terp="appshell-nav-group"] {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
/* The label's block padding is the sidebar's, where it separates the label from the links BELOW
   it. In a row that padding is on the wrong axis: it adds to the group gap and pushes the label
   off the links' centre line. Zeroed to the inline axis only, so the label keeps the horizontal
   rhythm and loses the vertical. */
[data-terp="appshell"][data-nav-placement="header"] [data-terp="appshell-nav-group-label"] {
  padding-block: 0;
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
/* The narrow frame: a form or a settings screen, capped header and all.
   32rem is not a new number. It is exactly what admin-form declares on the two packaged create
   screens and what ProfileView's card carries, and 4b already named that card as a page measure
   wearing a card's clothes. So this is the mechanism those three were each hand-rolling, and
   folding them into it is the follow-up rather than part of shipping it.
   max-width on the ARTICLE, not width on its children, which is the opposite of the shell's
   content measure one rule above. Two reasons. The header is meant to be capped here — a Save
   button a screen-width from its field is worse than one over it — so there is nothing to
   exempt and no :not() to write. And capping the article composes with the shell measure by
   construction instead of competing with it: the article is already at most the shell's measure,
   and this takes it narrower still. */
[data-terp="page"][data-measure="narrow"] {
  max-width: 32rem;
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
/* xl, not lg, and the scale is the reason. At lg the single h1 of a view rendered 18px
   against a 16px card title and 16px body copy — one step from a section heading, and a
   section heading the same size as prose. --font-size-xl (24px) was published with one
   reader (heading[data-size="xl"]), so the top of the scale existed and the page that most
   needs it was not using it. 24 / 18 / 16 / 14 is a scale; 18 / 16 / 16 / 14 is a list.

   No prop, and no per-app knob: an app that wants otherwise redefines the marker from its
   own unlayered theme.css, which is what the cascade-layer architecture is for (ADR 0094 —
   this sheet carries no !important, so the app wins without one). */
[data-terp="page-title"] {
  margin: 0;
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
  letter-spacing: 0;
  color: var(--color-neutral-900);
  line-height: 1.3;
}
/* The content measure, and the subheader band, which are ONE declaration rather than two
   features (ADR 0097 §2). A full-width band only means anything once the column beside it is
   constrained, and constraining the column is what leaves the header spanning the full track.

   No new element and no portal, and both were considered rather than assumed. A wrapper
   around the body — display: contents included — becomes the sole child of article.children
   and fails every governed page closed, because that slot check is a DOM traversal and sees
   the node whether or not it generates a box. A portal leaves no node and survives that, but
   createPortal needs a container that exists when the child renders and the shell can only
   publish one through state: first commit local, second commit in the band, a one-frame jump
   on every navigation traded for nothing.

   Neither is needed, because [data-terp="page"] is ALREADY a single-column grid. The header
   keeps the track; every other child takes the measure. So the band is the header that was
   always there.

   The exemption is keyed on the page-header MARKER rather than on the header TAG, and that
   distinction is a fix rather than a detail. A :not(header) exempts every <header> that happens
   to be a direct child, so a bespoke screen writing
   <Page><header>section head</header><DataView/></Page> — legal, since the plain Page is
   deliberately unconstrained by the layout contract — would get a second full-width band it
   never asked for, silently. The frame's own header is the only thing meant to span the track,
   and the marker says so. (The layout contract's runtime check still drops the header by TAG
   name, because that check runs where no marker is guaranteed; the two mechanisms answer
   different questions and only this one is a style.)

   And no backticks in this block, which is not a style note: a backtick here TERMINATES
   TERP_STYLES_CSS and the parse fails somewhere else entirely with "try inserting a
   semicolon". This comment cost that mistake once while being written.

   Gated on an attribute the SHELL stamps, so nothing moves for any app today: with
   data-content-width absent this rule matches nothing at all. And "full width" means the full
   width of the article's own track — appshell-main's padding is outside it, so this is a
   measure within the content column rather than a bleed to the window edge, which would need
   a negative margin and therefore an inline site.

   WIDTH, not max-width, and that is the whole correctness of the rule rather than a
   preference. This selector weighs (0,4,0) — four attribute selectors, three of them here and
   one inside :not(), and the universal contributes nothing — so as a max-width it OUTRANKS
   every component that declares a narrower one, and
   five of them are legal children of a governed body: resource-list (40rem), admin-form
   (32rem), dialog (26rem) and text[data-measure] at 48ch and 72ch. Measured before it was
   fixed: an admin-form inside a measured shell computed max-width 1280px instead of 512px,
   so the packaged provisioning form rendered two and a half times too wide. The shell would
   have been WIDENING the very components that already carry their own measure — including the
   Text prop this mechanism was modelled on.

   As a width it composes instead of competing, because CSS resolves max-width AFTER width:
   min(100%, measure) caps a child that has no measure of its own, and a child that has one
   still wins with it. min() rather than a bare token so a track narrower than the measure is
   untouched rather than overflowing. */
[data-terp="appshell"][data-content-width="measured"]
  [data-terp="page"] > *:not([data-terp="page-header"]) {
  width: min(100%, var(--shell-content-max-width));
}
/* The reach-through, for the one body child that generates no box of its own. Markdown is
   display: contents (see its rule, which used to claim no child-star selector existed in this
   sheet — the one above is exactly that selector, and the claim is corrected there). The rule
   above therefore MATCHES the markdown wrapper and then has nothing to apply a width to, since
   a non-inherited property on a boxless element is dropped. The result was prose running the
   full width of a measured shell, which is the one thing that mechanism exists to prevent, on
   the one component whose whole purpose is long-form text. Capping its blocks instead reaches
   the boxes the wrapper stands in for. */
[data-terp="appshell"][data-content-width="measured"]
  [data-terp="page"] > [data-terp="markdown"] > * {
  width: min(100%, var(--shell-content-max-width));
}

/* The split archetype ------------------------------------------------------ */
/* A list beside the record it selects. Mobile-first: one column, list first, so the tab
   sequence is the reading order in both layouts and the stacked case needs no rule at all.
   The two-column form lives in the sheet's ONE existing wide-viewport block further down,
   rather than opening a second @media — same reason Stack's responsive rules went there.

   align-items: start so a short detail pane does not stretch to the list's height, which is
   what makes the two read as panes rather than as table cells. */
[data-terp="splitpage-panes"] {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-4);
  align-items: start;
  min-width: 0;
}
/* Each pane is a min-width: 0 grid item, or a wide DataView inside one refuses to shrink and
   pushes the row past its track — the same floor Grid's cells carry, for the same reason. */
[data-terp="splitpane"] {
  min-width: 0;
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
/* The initials tile, once. This was two rules — profile-avatar and user-menu-avatar —
   of eleven declarations each, identical but for a width, a height and a font size,
   which is a component the framework happened to ship twice under two names.

   It is aria-hidden, so axe skips it by design and the declared pairing is the only
   thing measuring its ink: brand-primary-contrast on brand-primary is
   primary-button-label, which the contrast gate holds at AA in all five themes.
   Exactly the shape of NavIcon's fallback tile, which failed at 1.60 for as long as
   nothing declared it.

   md carries no attribute of its own, the way every other sized component here works:
   the base rule IS the default, and a data-size="md" rule would leave two places
   describing the same tile. */
[data-terp="avatar"] {
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
[data-terp="avatar"][data-size="sm"] {
  width: 2rem;
  height: 2rem;
  font-size: var(--font-size-sm);
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
/* The full variant's surface belongs to the TABLE, not to the whole view.
   It used to wrap everything: one card holding the toolbar, the table and the
   pagination, divided internally by a border under the toolbar and over the
   pagination. That reads as three bands of one object, and it costs twice — the
   table's cells are then flush against the outer frame (nothing between the first
   column's text and the card edge but cell padding), and the toolbar's controls sit
   inside a surface they do not belong to.

   So the surface moves down one level, onto whatever occupies the table's slot, and
   the toolbar and the pagination float on the page background instead. The table
   becomes the object; the controls above and below it become controls. That also
   dissolves the flush-to-the-edge problem rather than padding around it: the table's
   own frame is the edge now, and --density-cell-pad-x is already the inset from it.

   The alternative considered was keeping the outer card and adding inline padding to
   the table inside it. Rejected: it fixes the symptom by making the card thicker,
   leaves the toolbar inside a surface, and leaves two nested frames whenever the view
   is empty (the empty state's dashed frame inside the card's solid one).

   Keyed on [data-variant="full"] rather than the bare marker for the reason the
   previous rule gave and which still holds: [data-variant="embedded"] must declare
   nothing, and un-declaring a surface with background: transparent / border: 0 is the
   shape ADR 0094 exists to avoid. */
[data-terp="dataview"][data-variant="full"] > [data-terp="dataview-scroll"],
[data-terp="dataview"][data-variant="full"] > [data-terp="dataview-error"],
[data-terp="dataview"][data-variant="full"] > [data-terp="dataview-skeleton"] {
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
/* Floating: no background, no divider, and no inline padding. The divider was the
   seam between two bands of one card and there is no card now — a border under a strip
   that sits on the page background is a line drawn across nothing. Dropping the inline
   padding aligns the controls with the table's OUTER edge (its frame) rather than with
   its cell text, which is the alignment a floating control row wants: the eye follows
   the frame, and a control indented to meet the first column's text reads as belonging
   inside the table.

   The background's previous justification is worth answering rather than deleting: it
   was there for the EMBEDDED variant, whose root declares nothing but a display, so that
   the band would not show the page canvas through it. That is now the intent in both
   variants. A floating strip shows whatever is behind it — the page in the full variant,
   the app's own card in the embedded one — and in neither case is a neutral-0 rectangle
   under the controls something the design asks for. dataview-toolbar-bare still renders
   on a neutral-50 host, so the difference is visible in a baseline either way. */
[data-terp="dataview-toolbar"] {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  padding-block: var(--space-2);
  min-height: 3rem;
}
/* Selection mode. A resting surface rather than an interaction state, so
   terp.base — and (0,2,0) against the base's (0,1,0) means it wins on
   specificity alone, needing no :not() and no source-order dependency. */
[data-terp="dataview-toolbar"][data-variant="selection"] {
  /* Still a filled surface, because it marks a MODE and losing that would make
     selection invisible — but now it is a surface of its own rather than a band of the
     card, so it takes the padding and radius that make it read as one. */
  padding-inline: var(--density-cell-pad-x);
  border-radius: var(--radius-md);
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
/* The password field's reveal toggle, built on the search box above rather than beside
   it: same positioning context, same absolutely-placed control, same specificity
   argument. Only type="password" wraps, so every other input is still a bare element
   and the two child selectors in this sheet that reach for data-terp="input" — the
   toolbar search and the resource-list create field — can never meet a wrapper. */
[data-terp="input-password"] {
  position: relative;
  display: inline-flex;
  align-items: center;
}
/* Room for the toggle. It must out-rank input[data-terp="input"] { padding: 0
   var(--space-3) } and does so on SPECIFICITY — two attributes (0,2,0) against an
   attribute plus a type (0,1,1) — the same trap and the same escape the search field
   documents above. Asymmetric on purpose: the glyph sits at the end, and reserving room
   at both ends would indent the value for nothing. */
[data-terp="input-password"] > [data-terp="input"] {
  padding-inline-end: var(--space-6);
  width: 100%;
}
/* The toggle itself, the seventeenth element wearing the iconbutton marker. It takes
   that marker rather than one of its own because it is one: the shared rule already
   carries its transition, its hover wash and its disabled treatment, and duplicating
   those under a new name to avoid editing one enumeration would be the wrong trade. */
/* Edge ships its own reveal control inside every password field, so without this the user gets
   two: the native eye sitting on top of ours, in a box sized for one glyph. Same class of fix as
   the number stepper this sheet already suppresses -- an unthemeable browser affordance the
   framework replaces rather than competes with. */
input[data-terp="input"][type="password"]::-ms-reveal {
  display: none;
}
[data-terp="input-password"] > [data-terp="iconbutton"] {
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
/* A column's declared track. A MINIMUM rather than a width, because a specified width is only a
   preference under table-layout: auto and the algorithm shrinks it to fit — which is why the pixel
   hint this replaces did nothing at all, measured in the workbench at three columns asking for
   700px each and fitting the box exactly. What auto layout cannot take away is a minimum.

   Three steps, and no more: these are the three bands the framework's own tables declare, and a
   step is additive to add and breaking to remove. In rem, so a declared track follows the root
   font size; the system columns below keep their pixels on purpose, being chrome rather than
   content, and converting them is a density pass with its own baselines.

   Nothing here ever meets an inline width. A resized column stops emitting the attribute, so the
   user's own drag replaces the declared track instead of losing to it — the minimum would win the
   cascade, and a column springing back from a drag reads as a broken resizer. */
[data-terp="dataview-table"] > thead > tr > th[data-width="xs"] {
  min-inline-size: 5rem;
}
[data-terp="dataview-table"] > thead > tr > th[data-width="sm"] {
  min-inline-size: 6.5rem;
}
[data-terp="dataview-table"] > thead > tr > th[data-width="md"] {
  min-inline-size: 9.5rem;
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
/* The last row draws no bottom border, which fixes two things the full variant's own
   comment had already named and deferred. The container carries a 1px border and a
   radius, so the last row's border sat a pixel inside it as a DOUBLE line, and with no
   overflow: hidden it also ran straight across the rounded bottom corners. Dropping the
   border is the fix rather than clipping the container: overflow: hidden here would trap
   the horizontal scroll container and any overlay a cell renders, which is why that
   comment refused it. tbody's last row, not the table's — a footer row would want its
   own rule. */
[data-terp="dataview-row"]:last-child > td {
  border-bottom: none;
}
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
/* font: inherit is not enough, and the gap it leaves split the header row in two.
   The font shorthand carries no text-transform and no letter-spacing, and the UA
   stylesheet resets both on form controls — so in any table mixing sortable and
   non-sortable columns the plain th rendered uppercase with 0.04em tracking while
   the sortable one rendered sentence case with none, side by side in one row. Both
   are named explicitly because inheritance is what the UA overrode.

   The block padding mirrors the th's so the button fills the cell it sits in,
   pulled back out by the negative margin. The control was a 17px-tall target inside
   a 34px cell — half the cell unused, and the most-used control in a data app
   clearing WCAG 2.5.8 only through the spacing exception. Filling the cell costs
   nothing and changes no layout: the button's box grows into padding the th
   already reserved. */
[data-terp="dataview-column-sort"] {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font: inherit;
  text-transform: inherit;
  letter-spacing: inherit;
  color: inherit;
  background: transparent;
  border: none;
  padding: var(--space-2) 0;
  margin-block: calc(-1 * var(--space-2));
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
  padding-block: var(--space-2);
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
/* Compact: a section's emptiness rather than the page's. Same frame and same words,
   laid out as a row — the glyph beside the text instead of above it — so two of
   these stacked read as two quiet sections rather than 480px of repeated poster. */
[data-terp="empty-state"][data-size="compact"] {
  grid-template-columns: auto 1fr;
  justify-items: start;
  align-items: center;
  gap: var(--space-2) var(--space-3);
  padding: var(--space-3) var(--space-4);
  text-align: start;
}
[data-terp="empty-state"][data-size="compact"] > [data-terp="empty-state-title"] {
  font-size: var(--font-size-sm);
}
[data-terp="empty-state"][data-size="compact"] > [data-terp="empty-state-description"],
[data-terp="empty-state"][data-size="compact"] > :not([data-terp="empty-state-icon"]):not([data-terp="empty-state-title"]) {
  grid-column: 2;
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
/* Multiple: the tokens share the field's box with the input, wrapping onto as many rows
   as the selection needs. A fixed-height field would either clip the third token or
   reserve room for tokens nobody has chosen — and a set-valued field whose height never
   changes is lying about how much is in it.

   The input keeps a minimum inline size so a filter is still typeable when the tokens have
   taken most of a row, and flex-basis 0 so it yields to them rather than pushing the last
   token out of the box. */
[data-terp="combobox-field"][data-multiple="true"] {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1);
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-md);
  background: var(--color-neutral-0);
}
[data-terp="combobox-field"][data-multiple="true"] > [data-terp="input"] {
  flex: 1 1 0;
  min-inline-size: 6rem;
  border: none;
  background: transparent;
  padding-inline: var(--space-1);
}
[data-terp="combobox-token"] {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding-block: 0;
  padding-inline: var(--space-2);
  font-size: var(--font-size-sm);
  color: var(--color-neutral-900);
  background: var(--color-neutral-100);
  border: 1px solid var(--color-neutral-200);
  border-radius: var(--radius-sm);
  /* Matches the control height a token sits beside, so a row of tokens and the input
     share one baseline instead of the tokens riding high. */
  min-block-size: calc(var(--density-control-min-height) - var(--space-2));
}
/* The remove control is a real button and a real tab stop, which is the accessible half of
   the Backspace shortcut rather than a duplicate of it: the shortcut is discoverable only if
   you already know it, and a token nobody can reach by keyboard cannot be removed by one. */
[data-terp="combobox-token-remove"] {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-inline-size: var(--space-4);
  min-block-size: var(--space-4);
  padding: 0;
  color: var(--color-neutral-600);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  line-height: 1;
}
[data-terp="combobox-token-remove"]:hover:not(:disabled) {
  color: var(--color-neutral-900);
  background: var(--color-neutral-200);
}
[data-terp="combobox-token-remove"]:disabled {
  cursor: not-allowed;
  opacity: 0.5;
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
  z-index: var(--z-index-tooltip);
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
  /* No pointer-events: none. It was here, and it makes WCAG 1.4.13's Hoverable clause
     impossible by construction: a bubble the pointer cannot reach is a bubble nobody
     tracking with a pointer, or reading under magnification, can finish reading. The
     component keeps it open across the gap with a short close delay instead. */
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
  /* The sidebar family, not the neutral one. This row renders inside the sidebar (and inside the
     header group under navPlacement="header", which takes the sidebar surface), so its ink and
     that background are a pairing in play — and the contrast gate can only measure a pairing it
     can name. Provably zero-diff: --color-neutral-900 and --color-sidebar-fg are byte-equal in
     all five themes. */
  color: var(--color-sidebar-fg);
  border-color: transparent;
  min-height: 0;
}
/* Icon-rail mode: the avatar alone, centred, with nothing around it. */
[data-terp="user-menu"][data-variant="collapsed"] [data-terp="menu-trigger"] {
  justify-content: center;
  gap: 0;
  padding: 0;
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
/* Two surfaces, one marker. UserMenu renders this span in the trigger AND in the portalled
   panel, and only the first sits on the sidebar — the panel is in document.body, where the
   sidebar palette does not apply. So the sidebar copy is scoped (the portal puts the panel
   outside this selector by construction) and the panel keeps the neutral. The sheet already
   argues this exact split for the drawer close button. */
[data-terp="user-menu-role"] {
  color: var(--color-neutral-600);
}
[data-terp="user-menu"] [data-terp="user-menu-role"] {
  color: var(--color-sidebar-muted);
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
   this wrapper rather than the blocks.

   That last sentence used to end "Nothing in this sheet uses one, which is why the
   wrapper is free today", and it stopped being true when the measured content width
   shipped: that rule is a child-star selector on the page's body children. It matched it,
   found no box to give a width to, and let prose run full-bleed in a measured shell.
   The reach-through beside that rule is the fix; this wrapper is free of everything
   else.

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

/* Icon-only buttons. Seventeen elements wear this marker and not one declares a
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
   unread. That is finished: AppShell reads --z-index-drawer, --z-index-backdrop
   and --z-index-sticky, the skip link reads --z-index-skip-link, and the toast
   viewport reads --z-index-toast. (This paragraph said "AppShell still writes
   50/40/30 ... and comes right with its own migration" for a release after that
   migration landed, which is the shape of stale comment worth naming: it read as
   a known gap rather than as a finished one.) Tooltip's z-index WAS 1 on the
   reasoning that the tooltip is absolutely positioned inside its own anchor, so 1
   is a local lift within a stacking context rather than a place in the app-wide
   order. That is sound about the anchor and wrong about the page:
   [data-terp="tooltip-anchor"] is only position: relative, which does NOT create a
   stacking context, so the 1 competed in the ROOT context — against a sticky header
   at 30 and an open popover at 60 — and lost. Reported as a tooltip that renders
   below content "sometimes, not always", which is exactly what a level that depends
   on whatever ancestor happens to establish a context looks like. It reads
   --z-index-tooltip (70) now, the level published for it.

   Still true, and NOT fixed by this: an ancestor with overflow: hidden clips an
   absolutely positioned tooltip whatever its level. The fix for that is the one
   [data-terp="popover-panel"] already uses — position: fixed with measured
   coordinates — and it is a change to the component rather than to this sheet. */
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
   the DataView's expand toggle, the view-options panel's two reorder arrows, the
   DataView toolbar's clear-search button and two layout toggles, and the password
   field's reveal toggle.
   SEVENTEEN SITES sharing a transition and nothing else — no shared SURFACE, because
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
   this selector matches still beat it" — so: which of the seventeen can carry the
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
[data-terp="iconbutton"]:disabled,
[data-terp="iconbutton"][aria-disabled="true"] {
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
/* The invalid exclusion is not tidying. This selector weighs (0,4,0) and the danger border below
   weighs (0,2,0), both unlayered against each other inside terp.state — so without the third
   :not() a pointer resting on a field that has just failed validation repaints its border from
   the danger token to a neutral grey, and the error state disappears for exactly as long as the
   user is pointing at the thing they need to fix. Narrowing the aggressor rather than adding a
   competing [aria-invalid="true"]:hover rule is this sheet's convention. */
[data-terp="input"]:hover:not(:disabled):not(:focus):not([aria-invalid="true"]) {
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
  background: var(--color-sidebar-accent);
  color: var(--color-sidebar-fg);
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
/* The rail's group separation. The label is visually hidden here (it joins the block above), so
   without this the groups are a single undifferentiated column of icons and the structure the
   expanded sidebar shows simply disappears at 4rem. A rule the LINE has to carry, because the
   label cannot: the divider is what is left of the label once the text is gone.

   It replaces rather than adds to the expanded margin — same specificity family, one attribute
   more — so the rail does not pay 1rem per group in a column that is already scrolling. */
[data-terp="appshell-sidebar"][data-collapsed="true"] [data-terp="appshell-nav-group"] + [data-terp="appshell-nav-group"] {
  margin-block-start: var(--space-2);
  padding-block-start: var(--space-2);
  border-block-start: 1px solid var(--color-sidebar-border);
}
[data-terp="appshell-sidebar"][data-collapsed="true"] [data-terp="appshell-nav"]::-webkit-scrollbar {
  width: 0;
  height: 0;
}
[data-terp="appshell-brand"]:hover {
  background: var(--color-sidebar-accent);
}
/* And its hover, for the same reason: the shared iconbutton hover wash is a neutral, which is
   the header toggle's context and not this one's. */
[data-terp="appshell-brand-row"] > [data-terp="iconbutton"]:hover {
  background: var(--color-sidebar-accent);
  color: var(--color-sidebar-fg);
}
/* The skip link, visible only while focused.
   In terp.state, and that is not filing: the resting half is the shared visually-hidden block
   in terp.base, which sets position, a 1px box and clip, and un-hiding has to beat all of it.
   On specificity it would not — a selector list takes the specificity of the member that
   MATCHES, and for this element that member is [data-terp="appshell-skip-link"] at (0,1,0),
   the same weight as this rule. (An earlier version of this comment cited the list's (0,3,0)
   member, which is the collapsed-rail selector and never matches a skip link; that reading
   would have made the rules a source-order coin flip rather than a layer decision.) Layer
   order settles it with nothing to reason about.
   :focus-visible rather than :focus, matching the sheet's shared ring: a skip link reached by
   pointer is a link nobody asked to see.
   Above the sticky header (30) and its backdrop (40) so it is not painted under the chrome it
   sits over; below the drawer (50) because nothing should paint over an open modal. Stacking
   order does NOT keep it out of the drawer's focus trap and this comment used to say it did —
   z-index has no bearing on tab order. The link is simply not RENDERED while the drawer is
   open; see AppShell. */
/* The skip link's target takes focus and must NOT paint the shared ring.
   The main element carries a data-terp marker and now a tabIndex of -1, which together put it
   in scope of the shared [data-terp]:focus-visible ring — so activating the skip link outlined
   the entire content column, header to footer, plus a 3px halo. Measured: it matches
   :focus-visible, with a 2px solid outline and rgba(37,99,235,0.35) 0 0 0 3px. The ring exists
   to say which CONTROL will take the next keystroke; a scroll target that was focused
   programmatically is not one, and the visible result of following a skip link should be the
   content rather than a box drawn around it.
   Scoped to this marker rather than to tabindex=-1 in general: other elements take -1 for other
   reasons and some of them are controls. */
[data-terp="appshell-main"]:focus-visible {
  outline: none;
  box-shadow: none;
}
[data-terp="appshell-skip-link"]:focus-visible {
  position: fixed;
  top: var(--space-2);
  inset-inline-start: var(--space-2);
  z-index: var(--z-index-skip-link);
  width: auto;
  height: auto;
  margin: 0;
  padding: var(--space-2) var(--space-3);
  clip: auto;
  overflow: visible;
  background: var(--color-neutral-0);
  color: var(--color-fg-accent);
  border: var(--border-width-thin) solid var(--color-fg-accent);
  border-radius: var(--radius-md);
  font-family: var(--font-family-sans);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  text-decoration: none;
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
   rule above: of the seventeen sites wearing that marker only six can be disabled at
   all — these four and the view-options panel's two reorder arrows, which carry
   their own scoped ink below for the same reason — and giving the shared rule a
   colour would change how a disabled calendar arrow looks the day one becomes
   disableable. The shared rule supplies the opacity and the cursor; this supplies
   the ink the pager had inline. */
[data-terp="dataview-pager"] > [data-terp="iconbutton"]:disabled,
[data-terp="dataview-pager"] > [data-terp="iconbutton"][aria-disabled="true"] {
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
/* Both halves carry the data-clickable guard, and the card half did not. A card list stamps
   data-clickable only when onRowClick is set, but renders the selection checkbox on
   selectionEnabled alone — so in a selectable-but-not-clickable list, focusing a checkbox
   washed the whole card in brand-soft and buried its data-tone. Focus is not selection, and
   a card that does nothing when clicked has no "activate me" state to advertise. */
[data-terp="dataview-row"][data-clickable="true"]:focus-within td,
[data-terp="dataview-card"][data-clickable="true"]:focus-within {
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
 * The property stamped on the constructed sheet so a second call recognises it.
 *
 * On the sheet object rather than on an element or a `data-` attribute: the sheet
 * lives on the `document`, so the mark is document-scoped exactly like the old
 * element-id check was, and it cannot collide with the `data-terp*` selectors
 * this very stylesheet declares.
 */
const ADOPTED_MARKER = "__terpStylesId";

/** A constructed sheet plus the mark identifying it as ours. */
type MarkedSheet = CSSStyleSheet & { [ADOPTED_MARKER]?: string };

/**
 * `document.adoptedStyleSheets` is absent in jsdom, so the property is read
 * through a type that admits that. Cast via `unknown` rather than intersected
 * with `Document`, because the DOM lib declares the property as always present
 * and an intersection would keep that stricter declaration.
 */
type AdoptableDocument = { adoptedStyleSheets?: MarkedSheet[] };

/**
 * Inject the react-core interaction-state stylesheet once per document.
 *
 * Prefers a **constructable stylesheet** (`new CSSStyleSheet()` +
 * `document.adoptedStyleSheets`), because that is the only injection route a
 * Content-Security-Policy does not have to widen for. A `<style>` element's
 * rules are inline styles as far as CSP is concerned, so shipping them obliged
 * every generated app to serve `style-src 'unsafe-inline'` — a keyword that,
 * once present, also permits every *other* inline stylesheet on the page,
 * including one an injection managed to introduce. Measured in Chromium: an
 * adopted sheet applies cleanly under `style-src 'self'` while a `<style>`
 * element is reported as a `style-src-elem` violation and its rules dropped.
 *
 * The `<style>` element remains the fallback, because a browser without
 * constructable stylesheets would otherwise render the chrome unstyled. Under a
 * strict policy those browsers get no styling either way, so the fallback only
 * ever helps.
 *
 * SSR-safe: no-op when `document` is undefined. Idempotent by either route — the
 * adopted sheet carries {@link ADOPTED_MARKER}, the element is keyed by
 * {@link TERP_STYLES_ID} — so repeated calls from any component's module scope
 * attach the rules exactly once. Neither route touches an HTML sink: the element
 * path sets `textContent`, never `innerHTML`, and `replaceSync` parses CSS only.
 */
export function injectTerpStyles(): void {
  if (typeof document === "undefined") {
    return;
  }
  if (document.getElementById(TERP_STYLES_ID) !== null) {
    return;
  }

  const adopted = (document as unknown as AdoptableDocument).adoptedStyleSheets;
  if (adopted !== undefined && typeof CSSStyleSheet === "function") {
    if (adopted.some((sheet) => sheet[ADOPTED_MARKER] === TERP_STYLES_ID)) {
      return;
    }
    try {
      const sheet: MarkedSheet = new CSSStyleSheet();
      sheet.replaceSync(TERP_STYLES_CSS);
      sheet[ADOPTED_MARKER] = TERP_STYLES_ID;
      (document as unknown as AdoptableDocument).adoptedStyleSheets = [...adopted, sheet];
      return;
    } catch {
      // A browser that exposes the API but refuses this sheet still gets styling.
    }
  }

  const el = document.createElement("style");
  el.id = TERP_STYLES_ID;
  el.textContent = TERP_STYLES_CSS;
  document.head.appendChild(el);
}
