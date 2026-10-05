# 0174 — A page spaces its sections wider than their blocks

- **Status:** Accepted and implemented (2026-10-05). Held by `styles.test.ts` ("a page's sections
  stand further apart than a section's blocks"), by the workbench's computed lane, and by both
  baseline sets.
- **Date:** 2026-10-05
- **Relates:** [ADR 0172](0172-a-block-at-rest-is-flat-and-a-shadow-means-a-layer.md) (flat at
  rest, which took away the other thing that separated blocks),
  [ADR 0169](0169-a-page-is-composed-from-the-shape-of-its-data.md) (the page's composition and its
  summary band), [ADR 0168](0168-a-page-in-a-series-steps-through-it-from-a-bar-that-stays-put.md)
  (the sequence bar)

---

## Context

A page lays out its header and its body children in one grid with one gap, `--space-4`. The
body's children are its sections: the summary band, a row of charts, a table, a record's fields.
A `Grid` puts the same `--space-4` between the blocks inside one section, and so does the hub's
grid of area cards.

So the room that ends a section was the room between two cards in it. On the admin hub, the row
of area cards was exactly as far from the chart below it as the cards were from each other. Until
ADR 0172 a resting shadow gave each block a soft edge that did some of the separating. With the
blocks flat, only spacing can say where one section stops. Looking at the flat screens, the owner
asked for "a little bit more space between sections on a page to separate them better". The
[composition draft](../internal/drafts/presentation-and-composition-design.md) already names this
as its first principle for current interfaces: hierarchy from type and space more than boxes.

## Decision

**The page's gap is the room between sections, and it is one step wider than the room inside
one:** `--space-6` (24px), against the `--space-4` (16px) a `Grid` (its default) and the hub's
grid keep between their blocks.

It is one value at every width. On a phone the shell's side gutter is 16px, but a grid stacks its
blocks there 16px apart on the same axis as the sections, so the section gap still has to be the
larger of the two.

Two rules follow the gap and name the same token:

- **The summary band's flush margin.** Inside a shell the band cancels the gap above it to sit
  against the title band's border, so its negative margin is the gap's.
- **The sequence bar's room above it.** The body ends as far above the bar as it starts below the
  title band, so the frame around the body is even.

## Consequences

- Every page with more than one section grows by 8px per section boundary. A dashboard's table
  sits 16px lower than before. Both baseline sets are re-recorded in the same change.
- The title band to the first section is 24px as well. That matches the shell's 24px side gutter
  on desktop, so the body sits in an even inset under the band.
- A section's title belongs to its block: a `Card`'s or a `DataView`'s `title`, or a chart's
  `label`. A section heading on the canvas, unframed, is a `Card` with `variant="plain"`, as the
  detail-page specimen does. A loose `Heading` placed as a body child of its own sits a section
  gap from what it names, and reads as a section without content.
- `Markdown` generates no box, so placed directly in a page its paragraphs are rows of the page's
  grid and take the section gap between them. Prose that is one section goes in a `Stack` or a
  `Card`, at the gap it wants.
- An app that cancels the page's gap itself (a negative margin in an escape hatch) has to follow
  it to `--space-6`.

## Alternatives considered

**32px (`--space-8`).** This separates sections the most, but it overdoes pages with a rule
between sections. A `Divider` takes the gap on both sides, so a 1px hairline would sit in 64px of
empty page. It also pushes a dashboard's table 32px down, against 16px at 24px.

**Wider at roomy widths only (24px on a phone, 32px on desktop).** Two values for one meaning,
with a cutover where a page's rhythm jumps. The 24px reads as a boundary at both widths, so the
second value buys nothing the first does not.

**A published token (`--page-section-gap`).** Three rules read the value, and they are held to
one token by test. The sheet publishes a token when an app asks to move it, not before, and no
app has. It stays a scale step written out until one does.
