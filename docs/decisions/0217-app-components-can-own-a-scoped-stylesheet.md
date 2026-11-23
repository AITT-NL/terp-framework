# 0217 — App components can own a scoped stylesheet

- **Status:** Proposed on 2026-11-19; the owner accepted it for 0.44.0 on 2026-11-23. Built in
  0.44.0. Held by `packages/frontend/eslint-boundaries/src/index.test.js` ("checks class
  bindings and stylesheet scope independently", which also pins each refusal's wording; "admits
  only inks and surfaces whose every pairing the palette declares and measures", against
  `@terpjs/contract`'s `token-pairs.json`; and the bootstrap and dynamic stylesheet cases),
  `findings.test.js` (a stylesheet fixed after a refusal is linted again, not replayed from the
  cache), the `no-inline-styling` and `no-style-imports` corpus cases with their recorded
  residuals, and `packages/frontend/conformance/tests/control-fit.spec.ts`.
- **Date:** 2026-11-19.
- **Amends:** [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md), which
  refused `className` and every app stylesheet;
  [ADR 0175](0175-the-frontend-boundary-does-not-stop-at-the-module-tree.md), whose bootstrap
  was the one file that imported a stylesheet;
  [ADR 0169](0169-a-page-is-composed-from-the-shape-of-its-data.md), whose rationing of
  emphasis and placement now binds the framework's blocks and the archetype slots, not a layout
  an app owns; and [ADR 0093](0093-semantic-token-layer-and-named-themes.md), whose token
  vocabulary stays the whole of an app's paint but no longer the whole of its styling surface.
- **Relates:** [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md) (a
  restriction names the property it protects), [ADR 0079](0079-slot-typed-layout-contracts.md)
  (the archetype slots a stylesheet does not loosen) and
  [ADR 0084](0084-runtime-applicability-classification.md) (the runtime classification below).

## Decision

An app component may statically default-import a sibling file named like `Board.module.css`
and put one of its classes on a native element as `className={styles.board}`. ESLint resolves
the import binding in lexical scope and reads the stylesheet. Its vocabulary admits local
class selectors, including lists and the common interaction states, and responsive groups
using `@media`, `@container` and `@supports`. A class is named as a script identifier
(`.taskCard`, not `.task-card`), because `className` reads it as `styles.taskCard` and Vite
exports a hyphenated class under a key no member expression can name. Declarations are layout
and typography properties and paint, and paint takes a palette role, not merely a `--color-*`
token: `color` an ink (`--color-fg-default`, `-muted`, `-subtle`), a background a surface
(`--color-bg-canvas`, `-surface`, `-subtle`, `-summary`) and a border a border token. Every
one of those inks over every one of those surfaces is a text pair the palette declares and its
contrast gate holds to AA in every theme, so a pairing an app forms from them, on one element
or across two, is one already measured. A brand fill, a status ink, the accent and the
primitive ramp stay with the framework controls that carry their partners. A list marker takes
a counter style keyword, never a string or `symbols()`, which would put copy on screen that no
catalog translates. Global selectors, nested rules, `@import`, cross-file `composes` and
`!important` are refused.

The module's binding is read in a `className` on a native element and nowhere else:
`className={styles.board}`, or `className={active ? styles.active : styles.board}` for a style
that follows a state. A class on a framework component is refused, and so is the binding passed
on through a spread, a call or a variable, which would carry a class to a framework control past
that check: the component takes its props. Ink and type are inherited, so a class that sets
them is refused on an element that holds a framework component (or renders `children`): they go
on the element that holds the app's own text. A marker on the import waives the import's form
only, never a finding inside the stylesheet. A CSS-only change invalidates the boundary CLI's
lint cache. Every refusal names its line or element, its cause and what would be admitted.

The vocabulary itself (the selector grammar, the properties and the paint roles) is this stack's
adapter, in `packages/frontend/eslint-boundaries/src/cssModules.js`, as the catalog's `reference`
field records how a stack realises a rule (ADR 0203). The rules and their intents stay the shared
statement: a stylesheet reaches only what its component owns, and paint follows the palette.
Another stack realises the same intents in its own adapter, so the design document's
boundary-lint spec names styling as token paint plus a component's own stylesheet.

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
application. What the styling rules protect is narrower: paint that follows the palettes, so
every theme holds its contrast, and framework controls that look and behave the same in every
app. Both survive a stylesheet confined to its own component's native elements.

## What it does not do

A screen that needs its own composition uses the body of a plain `Page`. The archetypes keep
their slot contracts (ADR 0079): a stylesheet does not let a native element into an
`OverviewPage` body. Framework controls keep their own styling and focus treatment: no class
lands on a framework block and no inherited ink or type reaches one from an element that holds
it, so ADR 0169's rationing still holds for every `Card`, figure and chart, and none gains a
tone or a variant. Inside a layout it owns, an app may place its native elements on tracks of
its own and give them a surface, a border and a radius from the roles above; where a framework
block fits, such as a `Card` for a titled group, it composes that block instead.

Two forms stay outside what the lint resolves, recorded in the corpus's `RESIDUALS.json`: a
framework component an element renders through a value written elsewhere (`const body =
<Card />`, rendered as `{body}`), whose inherited ink and type the lint does not trace; and an
element with a module class inside a framework control's own children, such as a `Button`
label, whose ink the lint holds to the admitted surfaces rather than the one that control
paints. The guides ask for contrast to be checked in every shipped theme, which is where both
would show.

Only paint is held to tokens. Lengths, spacing and type values on an app's own elements are
the app's: the guides ask for the spacing and type scale tokens, which a house style or
`theme.css` then reaches, but the lint does not refuse a literal length or a font family.

The stylesheet has no marker of its own. A declaration outside the vocabulary is styling a
framework component or token should own, so the route is the component or a request for the
token. The one escape stays the one there was before this decision: a justified marker on a
stylesheet import, counted by the escape-hatch budget and decided by a human.

Visual review and interaction tests establish whether a layout works across themes, input
methods and viewport widths; `expectControlFitsHorizontally` in `@terpjs/conformance` checks
that a control fits its viewport and every ancestor whose overflow clips it.

## Consequences

Vite emits app styles into a same-origin CSS asset that the existing production policy
(`style-src 'self'`) admits, so the policy is unchanged. The allowance gives application code
no new client or server permissions.

`frontend/no-style-imports` stays a build-time control by recorded decision (ADR 0084,
`not-applicable`): a stylesheet import is a build-graph edge, and once the bundler has emitted
the CSS no module authorship is left for a runtime check to observe. `frontend/no-inline-styling`
is `deferred`. Most of it is erased the same way: react-core sets inline styles of its own, and
a module's class is a hashed name like any other on a native element. One part is not. Every
react-core control's root carries a `data-terp` marker and react-core renders no class on it,
save the router's active link, so a class on a framework control can be seen in the running
page, on the seam `verifySlotChildren` already walks by those markers. A runtime refusal of a
class on a `data-terp` element, beside that check, flips the entry to `required`; it has not
shipped. The runtime controls around the rule are unchanged: the production policy refuses a
`<style>` element, a style attribute in markup and a stylesheet from another origin, and where
an app declares a layout contract, the runtime check still refuses an archetype body child
outside its slot.
