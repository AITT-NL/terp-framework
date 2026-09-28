# 0160 — App code does not write the framework's markers

- **Status:** Accepted and implemented in `@terpjs/eslint-boundaries`
  (`terp/no-framework-markers`). The matching Terp Standard catalog entry and corpus
  (`frontend/no-framework-markers`) are in terp-spec; this repository adopts them with the next
  spec release. Held by `packages/frontend/eslint-boundaries/src/markers.test.js`.
- **Date:** 2026-09-28
- **Relates:** [ADR 0094](0094-attribute-keyed-styling.md) (the stylesheet selects on the
  markers), [ADR 0079](0079-slot-typed-layout-contracts.md) (the runtime slot check identifies a
  slot's children by them), [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md)
  (`style` and `className` are refused in app modules; the governed opt-out),
  [ADR 0154](0154-conformance-finds-the-shell-by-its-markers-and-the-stack-by-its-assignment.md)
  (conformance locates the framework's screens by their markers),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (one pattern,
  enforced)

---

## Context

react-core stamps a `data-terp` marker on the elements its components render, and the
inventory is pinned (`markers.test.ts`). Two controls trust it:

1. **The stylesheet.** Since ADR 0094 every base rule is an attribute selector:
   `[data-terp="card"] { … }`. So `<div data-terp="card">` in an app module is styled as a Card
   without being one. That gets around ADR 0059's refusal of `style` and `className` without
   composing the component, and no attribute refusal sees it, because the attribute it uses is
   not `style` or `className`.
2. **The runtime half of the layout contract.** `verifySlotChildren` identifies each child of a
   governed slot by its root marker. A hand-written `data-terp="card"` passes as a Card, so the
   runtime check accepts whatever element carries it.

A third reader, the preview bridge, already says in its own source that it cannot tell a
component's marker from a string an app put there, and bounds what it forwards accordingly.

Nothing refused any of it. Neither the catalog nor the lint mentioned `data-terp`.

The question came up where ADR 0154 made the conformance helpers locate the sign-in screen by
its markers. An app can replace that screen (`renderTerpApp({ login: <Custom /> })`), and the
question was whether the replacement should render the framework's markers so the shared helpers
still find it. Doing that would make a forged marker the documented way to keep a test passing.

## Decision

**App-authored source never writes react-core's markers.** The markers are the framework's
inventory, and only the framework writes them.

- **What is refused:** `data-terp` and every `data-terp-*` attribute (the preview bridge's
  `data-terp-preview-pick` is the framework's too). The rule catches the name as a JSX attribute on
  any element or component, as the key of an object literal (an inline spread, a hoisted props
  object, a `createElement` props bag), as a literal name passed to `setAttribute`,
  `setAttributeNS` or `toggleAttribute`, and as a `dataset` assignment in the same namespace
  (`dataset.terp`, `dataset.terpPreviewPick`). Attribute names are matched case-insensitively,
  because the DOM lowercases an attribute name written on an HTML element. Measured in Chromium:
  `setAttribute("DATA-TERP", "card")` leaves `data-terp="card"`, which `[data-terp="card"]`
  matches.
- **Scope:** all of app-authored `src/**`, not only modules. A replaced framework screen is
  passed to `renderTerpApp` from the bootstrap, and nothing requires it to live in a module.
- **The message names the fix.** Compose the react-core component that renders the marker. An
  app that replaces a framework screen owns that screen, so it tests the screen by the roles and
  accessible names it renders, not by the markers the framework's own screen carries.
- **Reported under** its own catalog rule, `frontend/no-framework-markers`, with the usual
  governed opt-out (`// terp-allow-no-framework-markers: <reason>`, counted by the budget).

**What is not refused, deliberately:**

- Every other data attribute. `data-testid` and `data-state` are the app's own, and so is
  `dataset.testid`.
- Reading a marker: `getAttribute("data-terp")`, a `[data-terp="…"]` selector in a test, or a
  destructured `"data-terp"` key. None of them writes a marker, and the framework's own
  conformance helpers read them.

Two react-core components, `Popover` and `Menu`, declare `data-terp` as a prop, so a component
built on them can name its own root. That is the framework composing itself. From app code it is
the same forgery as any other, and the rule refuses it there like any other.

The runtime classification is `not-applicable`. A marker in the rendered DOM is the same
attribute whoever wrote it, which is exactly why a forged one passes the controls that read it,
so the authored source is the only place authorship is still visible.

## Consequences

- An app that writes a marker fails lint on upgrade, with a message naming both ways out. The
  example app and the project template write none. The workbench (`apps/workbench`) does, in
  specimens that reproduce react-core's own markup, but it is the framework's visual harness,
  has no boundary lint config, and is out of scope.
- An app that replaced the sign-in screen and relied on the shared conformance helpers to find
  it writes its own sign-in steps for its own screen.
- The static rule does not see an attribute name that is not a literal
  (`setAttribute(name, value)`, a computed key), or a route it does not name, such as
  `Object.assign(element.dataset, { terp: "card" })`. The spec records both as residuals rather
  than claiming them closed.
- The runtime half of the layout contract still trusts the marker it reads. This rule closes the
  authored route to a forged one; it does not make `verifySlotChildren` able to tell a real
  component from an element carrying its marker.
- The two repositories' CIs are coupled. This repository's gate stays green against the pinned
  spec, because the lint may run a rule the pinned catalog does not list yet. The spec's certify
  job runs against the framework commit its `REFERENCE_SHA` names, so it fails until that is a
  `main` commit carrying this rule. This repository's corpus test sees the new cases only after
  the spec release is adopted.
