# 0079 — Slot-typed layout contracts

- **Status:** Accepted
- **Date:** 2026-07-07
- **Relates:** [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md)
  (strict-only boundary lint + the escape-hatch budget, the only opt-out mechanism this
  ADR reuses) and [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (the fail-closed runtime + build-time test shape both halves follow).

---

## Context

The platform already enforces "every routed view renders a page archetype" two-layer:
the `pageMarker` runtime check in `buildAppRouter` refuses an unframed view fail closed,
and the boundary lint keeps app modules on the token-styled `@terp/react-core` surface.
That guarantees every screen keeps the breadcrumb/title/error *frame* — but inside the
frame, an archetype's body is free-form. Two apps built from the same primitives can
still diverge in look, feel, and structure, and an agent building a screen gets no
guidance beyond "use react-core components".

The requested next ratchet: let an app opt into a named **layout**, with only specific
components allowed in specific slots (only cards in a hub grid, only data collections in
an overview body, …), enforced strictly — so the enforcement failures *tell a coding
agent exactly how to build the screen*, and an existing app can switch to a layout later
and be walked to conformance by the messages.

## Decision

Ship **slot-typed layout contracts**: named, data-driven, opt-in per app, enforced with
the established two-layer fail-closed pattern, with one agent-directive message phrased
identically by both halves.

- **Contracts as data.** `@terp/eslint-boundaries/src/layouts.js` is the source table
  (the layout analog of `spec.js`): per contract, per governed archetype ("slot owner"),
  the allowed react-core component names mapped to the `data-terp` marker each stamps on
  its root element. One contract ships first — `standard`: `HubPage` bodies hold
  `HubCard` only; `OverviewPage` bodies hold `DataView` / `ResourceList` / `ModuleNav` /
  `Stack` plus the framework states (`EmptyState` / `ErrorState` / `LoadingState` /
  `Alert`) and `ConfirmDialog`; `DetailPage` bodies hold `DetailList` / `Stack` / `Tabs`
  / `ModuleNav` / `DataView` plus the same states. The plain `Page` is deliberately
  unconstrained — the sanctioned home for a bespoke screen, so the contract needs no
  second opt-out mechanism. Adding a layout is adding a manifest entry, not lint code.
- **Opt-in, backwards compatible.** The lint half activates on a checked-in
  `layout-contract.json` (found upward from the linted file, analogous to
  `escape-hatch-budget.json`); the runtime half activates on
  `renderTerpApp({ layoutContract })` / `buildAppRouter(..., { layoutContract })` (an
  unknown id throws at build time). No config means today's behavior; the template
  generates both sides in sync so a new project starts enforced and conforming.
- **Build-time half.** The `terp/layout-contract` ESLint rule checks the static JSX
  children of each slot owner against the contract (raw text and fragment children
  included; `{...}` expressions deliberately skipped — dynamic children are the runtime
  half's job). Strict-only, no modes (ADR 0059); the only opt-out is the existing
  justified `// terp-allow-layout-contract: <reason>` marker, counted by the budget
  ratchet.
- **Runtime half (authoritative).** Every sanctioned component stamps a `data-terp`
  marker on its root; with a contract active, the archetypes verify one macrotask after
  mount (exactly like the page-archetype check) that the body slot's rendered DOM
  children all carry allowed markers, and refuse the view fail closed otherwise — so
  mapped arrays, wrapper components, and anything else static analysis cannot see are
  still governed. Checks are skipped while the archetype shows its loading/error frame.
- **Agent-directive messages.** Both halves phrase the identical message via one
  builder: the contract, the slot, what was found, what is allowed, and the concrete
  fix (compose from the allowed components, move bespoke content to a plain `Page`, or
  opt out with a justified marker). `terp guide layouts` documents the recipe.
- **Parity, not duplication drift.** react-core (a standalone runtime package that must
  not depend on a lint package) carries a TypeScript mirror of the table; a react-core
  test imports the eslint-boundaries source and asserts the tables and the message
  builder are identical, so the two copies cannot drift.

## Consequences

- A new templated app is consistent by construction: hub → cards, overview → data
  collection, detail → record sections, with any deviation refused at lint time and at
  runtime with instructions instead of a bare error.
- An existing app adopts a contract by adding the config + option and following the
  failures to conformance; per-screen exceptions ride the existing escape-hatch budget,
  and a recurring legitimate need should become a contract allowance (a data change)
  rather than an accumulation of opt-outs.
- Coarse first, by design: component allow-lists per body slot, one `standard` contract.
  Finer grammar (cardinality, required components, per-route-subtree contracts) can
  ratchet in later as data without new enforcement machinery.
- The `data-terp` markers are a consistency rail, not a security boundary: module code
  spoofing a marker is visible in review and lint-adjacent, and the contract governs
  look-and-feel, not authorization.
