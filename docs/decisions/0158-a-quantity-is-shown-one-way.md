# 0158 — A quantity is shown one way: meters and charts

- **Status:** Proposed. Nothing is built. This records the fork and a recommendation for a
  maintainer to decide. The decision will be an amendment to this ADR.
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
