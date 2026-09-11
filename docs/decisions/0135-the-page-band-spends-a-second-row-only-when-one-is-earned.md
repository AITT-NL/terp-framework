# 0135 — The page band spends a second row only when one is earned

- **Status:** Implemented.
- **Date:** 2026-09-11
- **Relates:** [ADR 0097](0097-the-page-band-is-chrome-and-reaches-the-gutter.md) (the band as
  chrome, and the property this keeps: it works with no shell above it),
  [ADR 0079](0079-slot-typed-layout-contracts.md) (the slot check that drops the header by
  tag name, which is why the band's own structure is free to change)

---

## Context

The page band carries three things: the breadcrumb trail whose leaf is the view's single `h1`,
a meta group of status badges and a one-sentence lead line, and the page's action cluster. It
was a wrapping flex row with `justify-content: space-between`, and its measured promise was
that it matched the app header above it — 48px with a title, 53px with an action button.

That promise held only while nothing in it was long. Three failures, all the same mechanism:

- **A crumb could leave its own chevron behind.** The separator sits inside the `li` beside its
  label, and the `li` was `flex-wrap: wrap`, so a long label pushed the chevron onto the next
  line — where it sat at the start of a row, pointing at nothing.
- **No crumb could shrink.** With no `min-width: 0` and no ellipsis on the crumb text, a deep
  trail widened until the band wrapped. Flex collects items into lines using their
  *hypothetical* main sizes and only then shrinks what is on a line, so the wrap happened
  before any truncation could.
- **The wrap then mislaid the actions.** Once the band had a second line, `space-between` had
  free space to distribute on it: a page that passed a fragment of buttons got them scattered
  across the full width, and a page that passed one cluster got it left-aligned on a row whose
  only job was to right-align it.

The third is the one worth naming, because it was invisible for as long as the band stayed one
row. The left group is `flex: 1 1 0`, so it absorbed every pixel of free space and
`space-between` had nothing to distribute — right up until the trail forced a second line.

A zero flex basis had already been fitted to buy the single row back, and it could not fix
either remaining failure. Wrap order follows source order, so the meta group and the cluster
could not share a row while staying two groups; and no basis prevents free space appearing on
a line that exists.

## Decision

**1. The band places by area, not by flow.** It is a grid of `minmax(0, 1fr) auto`. Nothing is
positioned by wrap order and no free space is distributed anywhere, so neither the scattering
nor the left-aligned cluster has a place to happen. `minmax(0, ...)` rather than `1fr` does the
job the flex basis did: a track's automatic minimum is its content's, so without it a long
unbreakable title still refuses to shrink.

**2. The second row is conditional, and free when it is taken.** A page with badges or a lead
line already spends a row on them; the cluster joining them there costs no height at all, and
it buys the trail the whole of the first row — which is what stops a deep trail having to
truncate in the first place. A page with neither keeps the single row, and with it the
measurement the chrome is held to. `Page` knows which it is at render time, so this is an
attribute and not a measurement.

**3. Every crumb may be cut; no crumb may be orphaned.** Both the list and its items are
`nowrap`, and the crumb text carries `min-width: 0` with an ellipsis. A deep trail degrades by
losing characters rather than by growing the chrome, and a chevron never leaves its label.

**4. The lead line is desktop-only, written as a correction rather than a rule.** Hidden at
every width, shown again above the second cutover. A sentence about the page is the first thing
to go when the band is short of room: the trail says where you are and the cluster says what
you can do, and neither has a smaller form that still works.

**5. The primary action keeps its label at every width.** Supporting actions drop to icons in
the middle region and fold into the overflow menu below the first cutover, above the page's own
rare and destructive items. The primary does neither. It is the one thing the page is for, and
a glyph or a menu line makes the main act of the screen a guess or a second tap.

**6. A cluster is always a group.** `Page` wraps whatever it is handed in the `page-actions`
box rather than letting a caller's nodes sit loose in the band, so the cluster is one grid item
whether or not the page reached for `PageActions`.

## Consequences

`page-heading` survives as a marker but generates no box: its two children have to be grid
items of the band itself because they sit on different rows, and a wrapper that boxed them
would put them in one cell. `display: contents` is the sheet's existing answer to that shape.
`page-meta` is new, and groups the badges and the lead line so they share the second row as one
left-hand item rather than competing for cells with the cluster opposite them.

Folding a supporting action into a menu needs it to be a *description*, not an element: by the
time a caller hands over a `<Button>` the label is inside someone else's tree and can only be
shown or hidden. `PageActions` therefore gains `secondaryActions`, a tuple of the same shape
`overflow` already takes. The existing `secondary` node stays and is unchanged, and is
documented as the form that cannot follow the viewport.

The band's single-row measurement stops being true of every page and becomes true of the pages
that have nothing else to show. That is a deliberate narrowing of ADR 0097's claim rather than
an abandonment of it: the row the app header is matched against is still there, and a page that
earns a second row was previously getting one anyway — just a taller, unaligned one with its
buttons in the wrong place.
