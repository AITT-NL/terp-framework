# 0113 — One measure for a record, and the escapes from it

- **Status:** Accepted
- **Date:** 2026-09-04
- **Relates:** [ADR 0094](0094-attribute-keyed-styling.md) (one stylesheet keyed on data
  attributes — every rule here is one of those),
  [ADR 0098](0098-archetypes-measures-and-the-density-island.md) (measures, and the density
  island whose "a legal prop combination that silently does nothing" test two of these three
  additions had to answer),
  [ADR 0079](0079-slot-typed-layout-contracts.md) (the slot-typed layout contract a new
  detail-body component has to join, in both halves),
  [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md) (the test a new
  component has to pass: capability is not the bar, legibility is).

---

## Context

`DetailList` renders a record's label/value pairs as a `<dl>`, and `layout="aligned"` gives the
labels a shared column so the values line up down the list. Above the framework's viewport
cutover the row wrapper becomes `display: contents`, which makes each `<dt>` and `<dd>` a grid
item of the `<dl>` itself — the only way to align across rows without changing the DOM.

That shared column is the component's whole point, and three things could not live in it.

**A value too wide for a column.** A paragraph, a payload, a reported result: a pair whose label
is one word and whose content is a screen wide. The list had no way to say so, so the only
recourse was to close the `<dl>`, render the wide thing, and open another one. Which produced
the second problem.

**Several lists on one card.** A record shown in sections — identity, schedule, what it
reported — is a list per section, because the sections have their own headings and their own
order and a `<dl>` cannot carry a heading (its content model is `dt`, `dd`, `div`, and nothing
else). Each list then measures its own label column. Three sections whose labels differ in
width therefore put their values on three different vertical lines: measured in the workbench,
values at three distinct offsets on one card, none of them wrong by that list's own rules. That
is why it reads as sloppy rather than broken, and why no test in the suite could have caught
it — every list was correct.

**A pair count that follows the width.** `columns` was a closed `1 | 2`, and the component's own
notes recorded the asymmetry: `Grid` publishes `columns="auto"` as its responsive answer and a
closed count has no such escape, so `DetailList` hand-rolled a reflow at the framework's single
viewport cutover. A viewport is the wrong instrument for this — a list inside a card inside a
split pane gets a width the window says nothing about — but a container query appears nowhere in
the sheet, and the sheet's own note declines to introduce one "for a single component" without a
record of its own.

## Decision

Three additions, and each is shaped by what it must NOT quietly do.

### 1. `DetailItem.full` spans one pair across every track

`full` puts the label above the value and gives the pair the whole row: the same pair's narrow
shape, asked for at one row rather than imposed on all of them. It is what stops a wide value
from splitting the list, which is the first problem above and the cause of the second.

Two rules, not one, and the second is the interesting half: a `display: contents` box generates
no box, so `grid-column` on it is dropped and the span silently does not happen. The full row
therefore stops being a contents box (`display: block`) in the one place it was one.

It spans *tracks*, so it does nothing where there are none: `layout="inline"` at `columns={1}`,
and every layout below the cutover, are already one full-width column. Under ADR 0098's test
that would be a legal combination doing nothing — the answer here is that it is not a no-op but
the same pair rendering identically for a different reason, and the prop's documentation says so
rather than leaving it to be discovered.

### 2. `DetailListGroup` shares one measure across several lists

The lists stay separate — they have to — and the *group* owns the track list. Each aligned list
inside becomes `grid-template-columns: subgrid`, so every label in every list is measured
against the same track. Verified before it was designed: three `<dl>`s whose labels differ in
width, all values at the same pixel, with the rows still `display: contents`.

**Subgrid is a new mechanism in this sheet**, which is why this ADR exists rather than a line in
a changelog. The bar the sheet set for itself when it declined container queries was that a
mechanism change "wants its own record", and this is that record. What makes subgrid cheap where
a container query was not: unsupported, the declaration is dropped and each list keeps its own
tracks, which is exactly the output today — so it ships with no feature query, no fallback
branch, and nothing to remove later. Baseline-widely-available since Chrome 117 / Safari 16 /
Firefox 71.

**A wrapper, and explicit.** The alternative was for `Card` to do this to the lists it happens to
contain, and it is refused on two grounds: a card that deliberately wants two differently-sized
label columns would have no way to say so, and a card would have to know about `<dl>` tracks,
which is a layer it has no business in. Under ADR 0111's test, the wrapper adds capability *and*
legibility — the sharing is visible at the call site — while the inferred version adds capability
by removing the ability to say what you mean.

**Three limits, each stated rather than left to be found.** It shares the measure for
`layout="aligned"` at the default single column, because that is the only shape that has a shared
label column; a `columns={2}` list keeps its own four tracks rather than being folded into two,
which would reflow its pairs to one per row — a layout change wearing an alignment fix's clothes.
It works above the cutover, below which there is no column to share. And the group's track list
must be `aligned`'s verbatim, gutter included, because a subgrid takes the parent's tracks *and*
the parent's gutter along the axis it subgrids: two copies of one measure, pinned against each
other by a test, because a group that disagreed with `aligned` would align its lists to each
other and to nothing else on the card.

### 3. `columns="auto"` follows the container

`"auto"` repeats a pair with a floor, so the count follows the width with no cutover at all —
which also makes it the first thing in this component that responds to its *container* rather
than the window.

The floors are the behaviour, and two measurements fixed them:

- **A zero floor is unusable.** Every other track in this component is floored at zero, for a
  documented reason. Inside an `auto-fit` repeat that makes the repetition count unbounded:
  measured, Chromium produced 35 pair repetitions, collapsed 31 of them to `0px`, and put every
  pair on one row. So `auto` is the one place here that needs a real floor — `9rem` of label and
  `13rem` of value, a 22rem pair.
- **A 100% cap is not enough for a *pair*.** `Grid`'s floor is `min(16rem, 100%)` because one
  track wider than its container overflows it. Two tracks at `100%` each can sum to 200%, and
  the list scrolled sideways in a narrow panel — measured overflowing at 120px. The floors are
  therefore capped at a *share* of the track (30% and 60%), which leaves the gap its room and
  keeps one pair inside one container.

The layouts with no label column repeat one track at `Grid`'s own `16rem`, so a stacked auto list
and a grid of cards break at the same width by construction rather than by coincidence.

**The closed counts keep the cutover reflow.** `1` and `2` say a number, and a number that
silently became three would not be one.

## Consequences

- One more component in the `standard` contract's detail-body slot, declared in both halves of
  the table (`layoutContract.ts` and the eslint-boundaries mirror) or the runtime slot check
  refuses a group in the one place it is for.
- The group's tracks and `aligned`'s are one measure in two rules. `styles.test.ts` compares
  them, including the gutter, so they cannot drift.
- `auto`'s floors are rem literals with a percentage cap rather than tokens, on the reasoning
  `Grid`'s four floors already record: a published scale with one consumer gets retired here, and
  these become tokens the day an app asks to move them.
- Three new specimens, and the group's is deliberately a *pair* — the same three sections stacked
  plainly beside the same three grouped — because neither half of that picture means anything
  alone.
- What none of this adds is a container query. `auto` responds to its container through a track
  floor, which the sheet already uses everywhere; the instrument the earlier note declined is
  still declined, and still has no record.

## Measurement

All three in the workbench's computed lane, which is where a resolved layout can be read rather
than inferred — and all three fail with the sheet reverted, which is the assertion that they are
about the rules rather than about the markup:

| | measured | reverted |
|---|---|---|
| `full` — the wide value's left edge | the list's own left edge | 100px inside it, still in the value track |
| group — distinct value offsets across three lists | 1 | 3 |
| `auto` — pairs in the 48rem container | 2 | 1 |

`auto` was additionally measured across seven container widths while the floors were being
chosen: three pairs at 1200px, two at 900px, one from 700px down, and no sideways scroll at
240px.
