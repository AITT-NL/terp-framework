# 0226 — Reference directions hold the vocabulary to looks that are not the default

- **Status:** Proposed on 2026-11-28. Held by `apps/workbench/visual/directions.spec.ts` (three
  reference directions, resolved in a browser: every control, container, multi-line field and
  title reads its role, whatever the direction sets it to) and
  `packages/frontend/react-core/src/roles.test.ts` (a multi-line field reads both corner roles,
  in exactly the capped form). Amends
  [ADR 0223](0223-type-and-shape-have-roles-as-colour-does.md): a multi-line field takes the
  control corner up to the container corner.
- **Date:** 2026-11-28.
- **Relates:** [ADR 0223](0223-type-and-shape-have-roles-as-colour-does.md) (the roles a
  direction is written in), [ADR 0224](0224-a-frontend-starts-from-a-design-brief.md) (an app's
  brief chooses its direction), [ADR 0094](0094-attribute-keyed-styling.md) (an app's unlayered
  `theme.css` wins over the layered sheet), and in terp-studio the directions a new app is
  offered at creation.

## Context

ADR 0223 gave type and shape roles, and `roles.test.ts` holds which rule reads which. Neither
shows what a look an app actually ships resolves to, once its `theme.css` has set the roles and
the steps behind them; and nobody had set them to a look far from the default and looked. The
screenshot baselines cannot: they render the default, and recording each look on both platforms
would multiply the baselines for a question a computed value answers.

Doing it for three looks found one defect and six things the vocabulary cannot say.

The defect is in ADR 0223's own example. Every field wears the control corner, and the example
sets it to `var(--radius-full)` for pill-shaped buttons. On a textarea, or on a multiple
Combobox whose chips have wrapped onto a second row, a 9999px corner draws a stadium whose
curved ends cut into the text.

## Decision

### 1. Three reference directions, resolved in a browser

The workbench keeps three looks deliberately unlike the default and unlike one another
(`apps/workbench/visual/reference-directions.ts`):

- **console**: square, tight and quiet, for a tool people work in all day. It is written as an
  author would, with a bare `0`.
- **portal**: pill-shaped controls, soft cards and a rounded heading face, for a portal people
  visit now and then.
- **editorial**: serif headings at a light weight and nearly square corners, for an app people
  mostly read and write in.

None sets a colour: a palette has its own contrast gate, and these are about type and shape.
`apps/workbench/visual/directions.spec.ts` injects each one the way an app's `theme.css`
arrives, as one unlayered `:root` block over the layered sheet, and checks the computed values
across the whole catalog:

- every button, input and select wears the control corner the direction resolves to;
- every card, empty state and record card wears the container corner;
- every multi-line field (a textarea, a list-box select, a multiple Combobox) wears the smaller
  of the two;
- every page, card and empty-state title takes the heading face and weight.

The expected values come from a probe that reads the same roles, so the test states the contract
("a button wears the control corner, whatever it is") rather than a number per look. It reads
those components, not every reader of every role: one of them that drifts onto a step passes
every baseline and fails here, and `roles.test.ts` holds the rest of the readers by name. No
specimen renders a list-box select, and a new one would need baselines on both platforms, so the
lane renders the element `Select` renders with `multiple` into the page. Screenshots of the three
looks are for a person to look at, and are not recorded.

### 2. A multi-line field is never rounder than a container

The Textarea, a Select that is a list box (`multiple`, or a `size` above one) and the multiple
Combobox field take `min(var(--radius-control), var(--radius-container))`. The list box also
stops drawing the dropdown chevron, which it never had a dropdown for:

- **The default is unchanged.** The control corner is the smaller of the two, so nothing renders
  differently.
- **A pill direction** gets multi-line fields with its container's corner.
- **ADR 0223's own example**, pill controls beside nearly square cards, gets nearly square
  textareas.
- **A bare `0`** is not a length `min()` accepts, so it makes the declaration invalid at
  computed-value time. That falls back to the initial corner, `0`, which is what `min()` would
  have given. The console direction is written that way, so the lane holds it.

### 3. The gaps are recorded, not filled

What the three looks could not say is listed below as the vocabulary's known gaps. Each would be
a role or a key of its own, with a list of readers and a default to choose. That is a decision
per gap, not something to slip into a test change.

| A direction wanted | Why it cannot | What it would take |
|---|---|---|
| A page title at display size | `page-title` sets `--font-size-sm`, a step; moving the step moves all small text | A title-size role |
| Chips that follow a pill-shaped field | `combobox-token` keeps `--radius-sm`, so a pill field holds square chips | A corner for the parts inside a control, derived from the control's |
| A borderless card on a tinted surface | `card` paints `1px solid var(--color-neutral-200)`, and no role names a container's edge | An edge role for containers, measured like a pairing |
| A button label's own voice | Its weight is a step, and no token gives case or tracking | Label roles for controls |
| Another mark for the active navigation item | It is the sidebar accent fill, which `--color-sidebar-*` themes, plus a 2px inset rail in `--color-brand-primary` and semibold weight; the rail's form (an underline instead, its side, its width) and the weight cannot be chosen | A layout declaration key, as `navPlacement` is, rather than a token |
| Density in more than two steps | `shell.density` is `comfortable` or `compact` | A third step, and what it does to every control height |

## Runtime

No rule changes, so there is nothing to classify. The lane tests the framework's own sheet.

## What it does not do

- **It adds none of the roles the gaps ask for.** Each needs its own decision.
- **It does not make the directions an API.** They live in the private workbench. An app states
  its own look in `theme.css`, and its brief says why (ADR 0224).
- **It does not record screenshots.** The computed values are the contract.

## Consequences

- A change that moves one of the components the lane reads off its role, or onto a step, fails
  under at least one direction as well as in `roles.test.ts`; a change to any other reader fails
  in `roles.test.ts`.
- ADR 0223's statement that every field wears the control corner now carries the cap, in the
  ADR's table, the theming guide, react-core's README and the CHANGELOG.
- The gaps table is where the next vocabulary change starts.
