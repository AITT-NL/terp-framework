# 0217 — App components can own a scoped stylesheet

- **Status:** Proposed on 2026-11-19. Built in 0.44.0. Held by
  `packages/frontend/eslint-boundaries/src/index.test.js` ("checks class bindings and
  stylesheet scope independently", the bootstrap and dynamic stylesheet cases),
  `findings.test.js` (a CSS-only edit invalidates the lint cache), the `no-inline-styling` and
  `no-style-imports` corpus cases, and `packages/frontend/conformance/tests/control-fit.spec.ts`.
- **Date:** 2026-11-19.
- **Amends:** [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md), which
  refused `className` and every app stylesheet, and
  [ADR 0175](0175-the-frontend-boundary-does-not-stop-at-the-module-tree.md), whose bootstrap
  was the one file that imported a stylesheet.
- **Relates:** [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md) (a
  restriction names the property it protects), [ADR 0079](0079-slot-typed-layout-contracts.md)
  (the archetype slots a stylesheet does not loosen) and
  [ADR 0084](0084-runtime-applicability-classification.md) (the runtime classification below).

## Decision

An app component may statically default-import a sibling file named like `Board.module.css`
and put one of its classes on a native element as `className={styles.board}`. ESLint resolves
the import binding in lexical scope and reads the stylesheet. Its vocabulary admits local
class selectors, including lists and the common interaction states, and responsive groups
using `@media`, `@container` and `@supports`. Declarations are layout and typography
properties, and paint comes only from `var(--color-*)` tokens. Global selectors, nested
rules, `@import`, cross-file `composes` and `!important` are refused. A class on a framework
component is refused: the component takes its props. A marker on the import waives the
import's form only, never a finding inside the stylesheet. A CSS-only change invalidates the
boundary CLI's lint cache.

Inline `style`, a class that is not a module's own, a stylesheet loaded through `import()` or
`import.meta.glob`, and every global stylesheet outside the bootstrap's three token layers are
still refused, under the existing catalog ids `frontend/no-inline-styling` and
`frontend/no-style-imports`.

## Context

A planning board groups work by status across lanes and stacks those lanes as space runs
out. Requiring each application to wait for a new react-core layout prop makes that product
choice a framework release decision. ADR 0111 asks which safety property justifies
restricting a capability. The typed client and server authorization protect access to the
tasks in both the board and the ordinary task list. Their layout can be chosen by the
application.

## What it does not do

A screen that needs its own composition uses the body of a plain `Page`. The archetypes keep
their slot contracts (ADR 0079): a stylesheet does not let a native element into an
`OverviewPage` body. Framework controls keep their own styling and focus treatment, and the
shared tokens keep the surfaces, text and spacing themed. Visual review and interaction tests
establish whether a layout works across themes, input methods and viewport widths;
`expectControlFitsHorizontally` in `@terpjs/conformance` checks that a control fits its
viewport and every ancestor whose overflow clips it.

## Consequences

Vite emits app styles into a same-origin CSS asset that the existing production policy
(`style-src 'self'`) admits, so the policy is unchanged. The allowance gives application code
no new client or server permissions.

Both rules stay build-time controls by recorded decision (ADR 0084, `not-applicable`): a CSS
Module compiles to hashed class names in an emitted stylesheet, and in the built DOM nothing
tells a module's class from one react-core renders, so no app authorship is left for a runtime
check to observe. The runtime controls around it are unchanged: the production policy refuses
a `<style>` element, a style attribute in markup and a stylesheet from another origin, and
where an app declares a layout contract, the runtime check still refuses an archetype body
child outside its slot.
