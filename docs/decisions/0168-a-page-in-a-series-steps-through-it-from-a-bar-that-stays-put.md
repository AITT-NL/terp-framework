# 0168 — A page in a series steps through it from a bar that stays put

- **Status:** Accepted and implemented. `Page` — and with it every archetype built on it — takes
  `sequence`, rendered as a `nav` after the page's article that sticks to the bottom of the
  viewport. Held by `Page.test.tsx`, `layoutContract.test.tsx` and `markers.test.ts` in
  `@terpjs/react-core`, by the workbench's `page-sequence` and `app-shell-sequence` specimens,
  and by two `computed.spec.ts` cases that measure where the bar sits.
- **Date:** 2026-10-02
- **Relates:** [ADR 0079](0079-slot-typed-layout-contracts.md) (the slot check that reads the
  article's children as body, which decides where the bar may live),
  [ADR 0097](0097-shell-parameters-and-ordered-navigation.md) (the band and the gutter it bleeds
  by, which the bar mirrors at the bottom),
  [ADR 0098](0098-archetypes-measures-and-the-density-island.md) (the narrow measure, which caps
  the bar with its frame)

---

## Context

Some screens are worked through one after another rather than visited: the columns of a table
being mapped, the records a search returned, the steps of a procedure. The natural control is a
pair of links to the neighbours, and an app building one had only one place to put them — a row
of buttons at the end of the page body. That row had three faults, and the app could fix none of
them.

**It moved.** A row after the content sits wherever the content ends. A long item put "next"
below the fold, a short one put it halfway up the screen, and a reader stepping through forty
items had to find the control again on every one of them — the opposite of what a stepper is
for.

**It was not a link.** A `Button` whose click calls `navigate()` cannot be middle-clicked or
opened in a new tab, and says nothing about direction to the browser. React-core has no router
link that looks like a button: `Button` takes no destination and `Link` is inline prose ink.

**It could not be pinned.** Pinning is a style — `position: sticky` and a surface for content to
scroll under — and an app module has no `style`, no `className` and no stylesheet of its own. An
archetype offers nothing after the body: `actions` is in the band at the top, which scrolls away
with the page.

## Decision

1. **`Page` takes `sequence`**, a description rather than elements: the series' `label`, the
   `previous` and `next` neighbours as `{ label, to }`, and an optional `position` of
   `{ current, total }`. Data for the reason `PageActions` takes `secondaryActions` as tuples —
   handed elements, the frame could not make them links, place them, or word the position. Every
   archetype that spreads its props onto `Page` takes it with no change of its own.

2. **The bar is a `nav` after the article, not inside it.** The layout contract's runtime check
   reads every child of the article except its header as body, so a bar inside would be a body
   child no slot table admits and would fail every governed page closed; exempting it there by
   tag would let any app `nav` through the contract. After the article the check never sees it.
   A `nav` rather than a `footer`, because outside a sectioning element a `footer` is the page's
   `contentinfo` landmark, which is the shell's. The `label` is required: the page already has a
   breadcrumb landmark, and two navigation landmarks a screen reader cannot tell apart by name
   are one too many.

3. **Three cells, always.** The previous link, the position and the next link each keep their
   cell when absent, so "next" sits at the same spot on the first item of a series as on the
   fortieth. The outer cells are `minmax(0, 1fr)`, so a long neighbour name truncates inside its
   half instead of pushing the position off centre.

4. **The steps are links.** Through the ambient `NavLinkContext` renderer, so a step is a
   client-side navigation that still opens in a new tab; a plain anchor outside a Terp router.
   Each carries `rel="prev"` or `rel="next"` and an accessible name that states the direction
   and contains the visible label — "Previous: Order 1016" — so a screen reader hears which way
   it goes and a voice user can still say what they see (WCAG 2.5.3). The markers are on the
   cells the bar owns, not on the router's anchor, so a renderer that forwards no attributes
   leaves the bar styled; the anchors therefore get the shared focus ring restated, since
   `[data-terp]:focus-visible` cannot reach them.

5. **It stays put.** The bar is `position: sticky; bottom: 0` with the band's own surface and
   border, so content scrolls under it. Inside a shell, `appshell-main` becomes a flex column and
   the article grows into it — scoped with `:has()` to a main that has a bar, so no other page
   changes — which puts the bar at the bottom of the content column on a short page, and pins it
   to the bottom of the viewport on a long one: the same line either way. It bleeds through
   main's padding by `--shell-gutter` on three sides, as the band does at the top; a narrow
   frame caps it at 32rem and takes only the bottom bleed.

6. **Focus is not hidden under it.** While a bar is on the page the document gets bottom scroll
   padding of the bar's height, computed from the tokens it is built of, so a control the browser
   scrolls into view on focus lands above the bar rather than behind it (WCAG 2.2 SC 2.4.11).

7. **It stays while the body loads or fails.** The series is the page's place, like the band;
   stepping past a record that failed to load is when a reader most wants it.

8. **Three framework strings**, with English and Dutch catalogs: `pageSequencePrevious`
   ("Previous: {label}"), `pageSequenceNext` and `pageSequencePosition` ("{current} of
   {total}"). The position is not a `PluralText`: it counts nothing it names.

## Consequences

- An app gets a stepper by describing the neighbours it already computes, and the page puts it
  in one place for the whole series, as links, in the active locale.
- `Page` returns a fragment — the article and, when given a sequence, the bar after it. Nothing
  in the package relied on a single root: every archetype renders `Page` as its outermost element.
- The flex column on `appshell-main` is the first rule that changes the shell's own layout
  because of what a page contains. It is scoped so that a page without a bar sees exactly the
  block it has always seen, which `computed.spec.ts` holds on the plain shell specimen.

## Not decided here

- **Keyboard shortcuts** for the steps. A key that means "next" collides with whatever the
  page's own controls use it for, so it is an app's call, and the links are already in the tab
  order.
- **Whether a page's actions belong in the bar too.** A sticky action bar — Save beside the
  steps — is a different question: actions change the record, steps leave it. The band keeps the
  actions until that is decided on its own.
- **An unknown total.** A series the app cannot count renders no position, rather than a guess.
