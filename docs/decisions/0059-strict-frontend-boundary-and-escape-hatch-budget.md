# 0059 — Strict-only frontend boundary gate with a governed escape-hatch budget

## Status

Accepted.

## Context

The frontend boundary rules (`@terp/eslint-boundaries`, design §7.1.5) enforced the
component surface only partially: raw `<button>`/`<input>`/`<select>`/`<textarea>`, the
`style` attribute, raw `fetch`, deep imports and cross-module imports were refused, but a
module could still hand-author layout through `className` + its own stylesheet, render a
raw `<table>`/`<dialog>`/`<form>`, hard-link in-app routes with `<a href="/...">`, or route
a view that skipped the page archetypes entirely. Worse, the copier template's CI never ran
the lint, so a generated project carried the rules but never enforced them.

Two shaping questions were raised: should the enforcement extend to framework consumers
(not just this monorepo), and should there be **modes** (e.g. an optional-but-default
"strict" mode)?

## Decision

**No modes.** Every Terp app is born from the template — there are no existing codebases to
migrate — so a severity dial would only institutionalize drift. The frontend gate mirrors
the backend gate exactly: one fixed rule set, every violation an error, always. If a genuine
brownfield story ever appears, a warn-only mode can be added then.

The full layout/component system is enforced on the app-authored surface (`src/modules/**`):

- raw `button`/`input`/`select`/`textarea`/`table`/`dialog`/`form` are refused, each mapped
  to its `@terp/react-core` component (`Button`, `Input`, `Select`, `Textarea`, `DataView`,
  `ConfirmDialog`, `Stack as="form"`);
- `style` **and** `className` attributes are refused, and module-authored stylesheet imports
  are refused — styling flows from the design tokens, layout from the react-core primitives;
- in-app anchors (`<a href="/...">`) are refused — routing goes through the stack's `Link`;
- every routed view must render a page archetype (`Page`, `OverviewPage`, `DetailPage`,
  `HubPage`). Two layers: `buildAppRouter` refuses an unframed view at runtime (fail closed,
  via a marker `Page` sets during render), and the react-core suite proves the control bites.

**Granularity comes from the governed escape hatch** (the design-§8 mechanism, ported): a
justified `// terp-allow-<rule>: <reason>` comment on (or immediately above) a violating
line suppresses that rule there; an unjustified marker is itself reported. Marker counts
must **exactly** match the app's checked-in `escape-hatch-budget.json` — a rise needs a
justified bump in the same change, a drop must be lowered to lock in the win
(`terp-boundaries-budget`, run by `npm run lint` after eslint).

Consumers get all of this by construction: the template ships the eslint config, the empty
budget, the lint script, and a CI `frontend` job that runs `npm run lint`.

## Consequences

- One enforced way to build screens, for the monorepo and every generated app alike; the
  boundary spec stays declared as data, so a future stack adapter inherits the same rules
  and escape-hatch semantics.
- Opt-outs are visible, greppable, justified, and monotonically shrinking — never a mode.
- The `<rule>` in a marker is the reported ruleId (`no-restricted-syntax`,
  `no-cross-module-imports`, ...), keeping suppression aligned with what the linter says.
- Scaffolded starter views now frame themselves in `OverviewPage`, matching the runtime
  control from the first render.
