# 0158 — A quantity is shown one way: meters and charts

- **Status:** Accepted, option 2 (2026-09-28). `Meter` ships in `@terpjs/react-core`; no chart
  is built, and the chart contract below is fixed for the first kind that is. See the Decision
  section at the end. The fork and the recommendation are kept as the record of what was
  weighed. **Amended 2026-10-03 by [ADR 0169](0169-a-page-is-composed-from-the-shape-of-its-data.md):**
  the trigger for building a kind, not the contract — see the amendment at the end.
- **Date:** 2026-09-27
- **Relates:** [ADR 0099](0099-the-component-gap-and-what-is-not-in-it.md) (the bar a
  component must clear, and its 2026-08-25 amendment on app evidence),
  [ADR 0094](0094-attribute-keyed-styling.md) (how a component is styled without inline
  styles), [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md) (why an app
  cannot style its own),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md)

---

## Context

App building on Terp reported that react-core has no way to show a quantity as a picture:
no meter for one bounded value (a quota used, a score against its range) and no chart for
a series (a count over time, a split across categories).

ADR 0099's bar is the one to answer: *a component that cannot name a consumer in this
framework is declined*, and "an app might want it" is not a consumer. Read literally, both
fail it. Nothing the framework ships measures a bounded scalar or plots a series, and 0099
refused `Progress` because nothing in the framework produces a percentage. A meter is not a
progress bar. It shows a value within a known range, not work being done. That refusal does
not decide it, but it shows the bar is applied strictly.

Two things are different from the components 0099 refused.

**An app cannot build this one itself within the pattern.** Every refusal in 0099 had a
compliant alternative in reach: a `Stack`, an existing `Tabs`, `Code block`, a `DataView`
variant. Here there is none. Module code may write neither CSS nor `style` (ADR 0059), and a
theme file carries tokens, not component rules. So a bar whose length is a value cannot be
drawn from the primitives. What remains is raw `<svg>`, which the restricted-element list does
not name.
Every app that needs a chart would then draw its own: a second way per app, with no theme
behind it, no contrast guarantee across the five themes, no accessible name, and no
locale-aware numbers. Under the ideology, a real capability with no compliant path is a gap
in the enforcement, not an app's preference.

**The evidence is one report, not two.** 0099's amendment accepted app evidence for
multi-select because the same workaround had been observed twice, each time with a named
loss. This proposal has a single report that the capability is missing. It has no observed
hand-drawn chart and no named loss yet.

## The fork

1. **Build nothing yet** and wait for the second observation 0099 asks for. The cost is
   that the observation will most likely *be* the defect: a hand-drawn SVG chart in some
   app's module, in the one theme its author looked at.
2. **A `Meter` now, charts later.** A token-styled wrapper over the native `<meter>`
   element (`value`, `min`, `max`, and the `low`/`high`/`optimum` bands HTML already defines),
   with a required accessible label and the value printed through the locale formatter. It
   is small, the element carries its own semantics, and it has no dependency.
3. **A minimal chart set in react-core as well**: a line or area over time, bars across
   categories, and a sparkline for a `HubCard` stat.
   - Drawn as SVG, styled only by attributes and tokens (ADR 0094), so no inline style and
     nothing that closes off a full Content-Security-Policy.
   - Each chart ships its data as a table alternative, and uses the `format` helpers for
     numbers.
   - No chart library: react-core publishes source, so a library's types would enter its
     public surface. That is the dependency argument 0099 §3 made against a form library, and
     it applies here unchanged.
4. **A separate `@terpjs/charts` package** with the same constraints, so react-core itself
   stays chart-free and an app that shows no charts carries none.

## Recommendation

**Option 2 now, with option 3's constraints written down as the contract any chart must
meet when its evidence arrives.**

- **`Meter` meets the bar on the capability argument alone.** No compliant path exists, the
  native element does most of the work, and a wrong answer costs one small component.
- **Charts are where 0099's caution earns its keep.** Which kinds, how many series, axis and
  legend behaviour: each choice is surface an agent will reach for. Building three kinds
  from one report is exactly the speculation the bar refuses.

So the contract is fixed now: SVG, attribute-keyed styling, tokens only, a table
alternative, locale-aware numbers, no dependency. The *first chart kind* is built when two
observations name it, and not before.

Option 4 is not recommended at this size. A package boundary is worth its cost when the
surface is large or the dependency is heavy, and neither holds for a dependency-free SVG set.

## What would change this

- A second report naming a specific chart kind, or a hand-drawn chart found in an app,
  builds that kind under the contract above.
- Evidence that a meter is always paired with a chart would argue for designing them
  together, and against building the meter first.

## Decision (2026-09-28): a meter now, and the contract a chart must meet

**Option 2, as recommended.** `Meter` ships in `@terpjs/react-core`. No chart kind is built.
The constraints written under the recommendation — SVG, attribute-keyed styling, tokens only, a
table alternative, locale-aware numbers, no dependency — are now the contract every chart kind
must meet, and the first kind is built when two observations name it. Option 4 stays declined
for the reason given above.

The split is the one the recommendation argued. A meter clears ADR 0099's bar on the
capability argument alone: there is no compliant path to a bar whose length is a value, and the
native element does most of the work. A chart does not yet, because one report names no kind,
and every kind is surface an agent will reach for.

### What building the meter decided

Five choices were decisions rather than details, so they are recorded here.

- **The bar is the native element.** Styled through its own pseudo-elements, from the adopted
  sheet, it painted exactly the tokens in all five themes — measured in Chromium, fill and
  track read back pixel for pixel — and still painted a distinct fill with forced colours on.
  So there is one element, the browser draws the proportion from its attributes, and there is
  no inline width. The fallback the proposal allowed, a hidden `<meter>` beside a drawn bar,
  would have been two elements for one fact. Gecko draws its fill through a different
  pseudo-element. Those rules are written and pinned, but no lane runs Gecko, so they are
  unmeasured.
- **The label names the meter, and is not printed.** Every place a quantity sits already has a
  visible caption: a `DetailList` term, a `Card` title, a `HubCard` title. Printing the label
  as well would put the same word twice on one line. `TileGroup` and `SplitPane` take their
  required `label` the same way.
- **So no slot table admits a meter.** The layout contract governs direct children only, and a
  meter inside a list row, a card or a hub card's stat is composition that no contract
  governs. Loose in a detail body it would be a bar with no visible caption at all, so the
  standard contract refuses it there, and `Meter.test.tsx` holds that refusal. The slot tables
  list sections. No value-level component (`Badge`, `Code`, `Avatar`, `TileGroup`) is in one
  either.
- **Bands are opt-in, and the component computes the region.** With no band declared the
  browser still files every value under "optimum". A rule keyed on the browser's choice would
  therefore paint a bare quota in the success tone, a judgement nobody made. The region is the
  HTML standard's algorithm written out, and it agrees with Chromium's own choice for every
  band shape the standard distinguishes. The band colour reinforces the printed value and never
  replaces it: Chromium's accessibility tree carries the value and the range and nothing about
  the bands.
- **One format prop, in the vocabulary that already exists.** `format` takes the
  `Intl.NumberFormatOptions` the `format` helpers take, and defaults to a percentage. A
  percentage is always the share of the range, so `74` of `100` prints `74%`, where Intl alone
  prints `7,400%`. Any other style prints the value itself, unclamped, so an overrun reads
  `120%` against a full bar. A formatter function was refused, because it would be the second
  way, and the one that skips the app's locale.

Its fills are declared pairings rather than choices in a comment: the accent and the three band
tones against the `--color-bg-inset` track, held to 3:1 in every theme by the contrast gate.
The brand fill was the other candidate. It measures 1.98 to 2.66 against that track in the
three dark themes, because it is a surface for light text, not a mark on the app's own ground.

### A raw `<meter>` is refused

With a token-styled `Meter` shipped, a raw `<meter>` in an app module is the second way, on the
same footing as a raw `<button>` beside `Button`, so `frontend/token-styled-elements` refuses it
and names `Meter`. The framework refuses it now; the Standard's refused-element list
(`restricted-surface.json`) gains it in 0.38.0. Refusing it here first is conformant, because
the Standard states the floor and not the ceiling. The framework's parity test used to require
its element map to equal the Standard's list exactly, which made that impossible; it now
requires every Standard element to be mapped, and names each element the framework refuses
ahead of the Standard in a list that empties itself on adoption.

## Amendment (2026-10-03): the trigger, by ADR 0169

The contract above stands as written: SVG, styled only by attributes and tokens, a table
alternative, numbers through the `format` helpers, no dependency.

What changes is when a kind gets built. "When two observations name it" assumed the evidence would
arrive from apps. [ADR 0169](0169-a-page-is-composed-from-the-shape-of-its-data.md) records the
owner's decision that the framework should promote varied, high-contrast pages, and with it that
the framework's own data counts as the observations: the `sync` capability stores each
`SyncRun`'s aggregates and status for a stats view, and `webhooks` records an outcome per delivery
attempt, and react-core could draw neither as more than a badge in a table row. The kinds built on
that evidence are this record's three — a line or area over time, bars across categories, a
sparkline for a figure — and three the same data asks for: columns as a mark of the over-time
chart, a status history, and a proportion bar. Any other kind still waits for a consumer of its
own, which is the rule this record set, unchanged.
