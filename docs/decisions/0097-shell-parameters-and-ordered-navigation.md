# 0097 — The shell is parameterised by tokens, and navigation is ordered groups

- **Status:** Accepted
- **Date:** 2026-08-21
- **Relates:** [ADR 0094](0094-attribute-keyed-styling.md) (the attribute-versus-inline line
  every new prop here is decided against), [ADR 0093](0093-semantic-token-layer-and-named-themes.md)
  (the token vocabulary the shell's geometry joins),
  [ADR 0079](0079-slot-typed-layout-contracts.md) (the slot tables new archetypes and new
  primitives must land in, on both halves),
  [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md) (app modules may not
  write `style` or `className` — the prohibition this ADR exists to make *survivable* rather
  than to loosen), and [ADR 0096](0096-typed-seams-cover-the-common-case.md) (the checked
  route seam whose `search` behaviour the navigation active-predicate is measured against).

---

## Context

Three structural blockers were diagnosed in `@terpjs/react-core`. Two are closed: the missing
semantic token layer (0093) and inline base styles (0094). The third is still open, and it is
different in kind from both — it is a **capability** ceiling, not a quality one.

`Stack` is the entire layout vocabulary: `as`, `direction`, `gap`, `align`, `justify`, `wrap`.
No padding, no grid, no columns, and no way to change direction at a breakpoint. `HubPage`'s
fixed `auto-fit` grid is the only grid in the framework. Because app modules may not write
`style` or `className` (0059), anything not expressible as nested `Stack`s is not merely
awkward to build — it is **unbuildable**. That is not a prediction; it has been paid for. A
fifteen-field form ships as one long vertical run because two columns cannot be expressed, and
a pipeline diagram was assembled out of `Badge`s joined by literal `{"→"}` string children,
which loses the direction of flow the moment `wrap` puts an arrow on a new line.

The important property of that evidence is *where* it came from: an app whose escape-hatch
budgets are both `{}`, with zero `terp-allow-*` markers, zero raw CSS, zero inline styles and
zero `className` across roughly three thousand lines. The guard rails held perfectly. So the
shortcoming is the framework's ceiling rather than app mess, and the pain was paid in
workarounds that stayed legal — which is exactly the pain no lint report can see.

The shell is the same story from the other end. Everything worth configuring is a module
constant, or — since 0094 moved base styles into the sheet — a literal in a rule: `15rem` and
`4rem` sidebar widths, a 768px breakpoint held in a `matchMedia` string, a three-rem header.
Most consequentially there is **no content max-width and no way to add one**, so a wide table
stretches edge to edge on a large monitor with no measure control anywhere in the framework.
The header spends three rem of vertical space on two icons — no page title, no breadcrumb, no
environment banner — and `renderTerpApp` does not pass `headerActions` through at all, so even
the slot that exists is unreachable from the one-call bootstrap every app uses.

And navigation. `NavItem` is `{label, to, icon?, role?}` — flat, no nesting, no badges, no
`exact` control, and **no ordering at all**: the sidebar's order is an accident of
`import.meta.glob` key order. `ICON_GLYPHS` is a `Record<string, ReactNode>` keyed by loose
string, so `NavItem.icon` is not type-checked and a typo degrades silently to an
initial-letter tile.

## Decision

### 1. Shell geometry is contract tokens, not props

The sidebar's expanded and collapsed widths, the header's height and the content measure are
CSS lengths. As props they are four inline styles on the shell root, and 0094 §3 is explicit
that a measured value stays inline — which would mean growing the inline-style ledger by four
sites for something that is not a measured value at all but a **theming knob**.

So they become published tokens instead: the sheet reads them and an app moves them from its
own unlayered `theme.css` with no prop surface whatsoever. Three properties follow, and the
third is why this is the right shape rather than merely a tidy one. `tokens.guard.test.ts`
already refuses any `var(--x)` the contract does not declare, so the knobs cannot be invented
locally. The ledger stays where it is. And the Studio gets four more manifest-published
controls for free, because the manifest is generated from the token sources — which is the
same leverage 2b bought and the reason a knob belongs in the token layer if it can live there.

**The one exception, and its consequence.** The mobile breakpoint cannot be a custom property:
CSS forbids custom properties in media-query conditions, and the shell reads the breakpoint
through `matchMedia` in JavaScript, not through CSS at all. It therefore stays a prop. The
consequence has to be stated rather than discovered: the responsive layout primitives
(decision 3) key on the **token** breakpoint scale and are not overridable per app, while the
shell's own mobile cutover is. Two knobs, one of them global. Pretending they are one is the
kind of drift 0093 exists to prevent.

### 2. The content measure is a page-grid constraint gated by a shell attribute — not a portal

The ask is a full-width band carrying the page's breadcrumbs and actions, above a content
column constrained to a readable measure. The obvious implementation is a portal: the shell
renders a band and `Page` publishes into it. That is rejected, for reasons that are facts
about this codebase rather than preferences.

`Page`'s runtime slot check reads `article.children` and drops the header by `tagName`. A
wrapper around the body — `display: contents` included, since the check is a DOM traversal and
the node is in the collection whether or not it generates a box — becomes the sole body-slot
child, matches no allow table, and fails **every governed page closed**. A portal does not
leave a node behind, so it would survive that; but `createPortal` needs a container that
exists when the child renders, and the shell can only publish one through state, so the first
commit renders locally and the second flips into the band. That is a visible one-frame jump on
every navigation, traded for nothing.

The mechanism chosen needs neither. `[data-terp="page"]` is **already** a grid
(`display: grid; grid-template-columns: minmax(0, 1fr)`), so the band is the page's existing
header keeping the full track while the article's other children are constrained to the
measure — gated on an enumerable attribute the shell stamps (`full` / `measure`), with the
measure itself a token from decision 1. Three things follow. Nothing moves for any app today,
because with the attribute absent not one declaration applies. `Page` keeps its `<header>`
element, so the slot check is untouched. And it works with no shell above it at all, which a
portal would not — the workbench renders `Page` standalone, and so do the tests.

### 3. Responsive layout props key on media queries against the token breakpoint scale

The sheet contains exactly one `@media` block today (`prefers-reduced-motion`). The shell's
768px cutover is not a media query at all: it is `matchMedia` in the component, stamped onto
the shell root as `data-variant="mobile"`, with every consequence descending from that one
attribute. That is a good pattern and it does not generalise to `Stack` and `Grid`, which have
no single owning component to hold the state and must work outside a shell.

So responsive props become attribute pairs read under media queries whose breakpoints are the
token values, written as literals because CSS cannot read a custom property in a media
condition, and pinned against the tokens by a test so the two cannot drift.

Container queries are the more correct answer to the question apps will eventually ask — a
`Grid` inside a narrow panel should go one-column regardless of the viewport — and they are
deliberately not taken yet. `container-type: inline-size` applies `contain: inline-size`,
which makes an element's inline size independent of its contents; putting that on `Page`'s
article or on `Card` is a layout change to be measured, not assumed, and it is not the change
this phase is making. Recorded as the option, with the measurement it owes.

### 4. New primitives are enumerable-only, so the inline-style ledger stays at nine

`INLINE_STYLE_SITES` is exact-equality per file, so every new component fails the gate on a
single inline style unless it is added to that ledger — and the ledger admits only 0094 §3's
two permanent kinds: a measured value the sheet cannot own, and a caller's own `style`
forwarded to a root. There is no third kind, and a phase that adds a dozen components is
exactly where a third would get invented.

The target is therefore that Phase 4 and Phase 5 add **zero** entries. Two places make that a
real decision rather than a slogan.

`Grid`'s minimum column width is the obvious inline candidate: a CSS length, precisely
`Icon`'s `size` shape, which §3 puts on the inline side permanently. It becomes **enumerable**
instead — a step on a token scale — and the reasoning is the framework's own: `Stack`'s `gap`
is a token index specifically so there are no arbitrary pixel gaps, and a grid whose column
floor is an arbitrary length reintroduces exactly that. `HubPage` already hardcodes
`min(16rem, 100%)`, so the scale has both a first value and a first reader. The cost is
honest: an app wanting `17.5rem` cannot have it. That is the trade `gap` already makes.

`Stack`'s `align` and `justify` stay inline and stay at one site, because they accept any
alignment keyword CSS defines — unchanged. But this is where the collision bites: a responsive
`align` can be neither inline (there is no inline media query) nor an attribute (the value set
is open). **So responsive forms are offered for `direction`, `gap` and `columns` only** — the
closed sets — and the alignment props stay single-valued. Refusing a prop is the right answer
here; minting a rule per alignment keyword, or adding a tenth inline site, are both worse.

### 5. Navigation is ordered groups declared by the app, items declared by modules

`NavItem` lives in `@terpjs/contract`, on the stack-agnostic manifest — the same surface a
future non-React adapter reads — so this is a contract change and is scoped like one.

A **group** spans modules: a "Sales" group contains items contributed by several of them, so
no module can own the group's label, order, icon, accent or landing description. Groups are
therefore declared once by the app and referenced by items. Items gain `group`, `order`,
`badge`, `exact`, nesting, and a `visible: (ctx) => boolean` predicate resolved against a
`NavContext` of module grants, per-module role ranks, superuser and internal-versus-external.

**This is additive, and the argument is structural rather than hopeful.** Today's rendering is
one flat list with no header. Under the new model an item that declares no `group` falls into
the default headerless group, which renders as one flat list with no header. Items with no
`order` keep declaration order under a stable sort. `role` keeps its exact current meaning,
and `visible` is an additional AND — both must pass, so the composition fails closed.
`visibleNav` stays exported and stays working.

One part is deliberately breaking, at the type level, because it is the whole point of the
fix: `icon` becomes a checked name. Contract cannot import react-core, so the name set is
published as data by the contract and react-core's union is held to it by a parity test —
the same shape as the `Theme` union's hand-written copy, for the same stated reason, in the
opposite direction. An app naming an icon outside the set gets a typecheck error instead of a
silent letter tile. Runtime behaviour is unchanged: the fallback stays.

### 6. "Active" is one predicate, and the component owns it

`ModuleNav` computes `isActive` as `pathname === item.to`, a raw string compare, while the
`Link` it renders carries `activeOptions: { exact: true }` and the router compares through
`exactPathTest`, which is `removeTrailingSlash(a) === removeTrailingSlash(b)` with
`includeSearch` defaulting to true. The two predicates therefore diverge in **both**
directions: the router is narrower on a filtered URL and broader on a slashed one. In the
second case the link gets `aria-current="page"` and `data-status="active"` from the router and
no `data-active` from the component, so the accent edge goes missing on the tab the router
calls current.

Active, for a nav tab, means: **the pathname matches with trailing slashes normalised,
ignoring the query string**, with `exact` controllable per item. A filter in the URL must not
unhighlight the tab a user is standing on. One shared predicate serves `ModuleNav` and the
sidebar.

It is keyed to the component's own `data-active` and **not** to the router's `aria-current`,
and that is not a style preference. TanStack's `useLinkProps` spreads the router's active
props **last**, after the caller's, so on a `Link` the router has the final word — which is
how the breadcrumb trail once rendered every ancestor as the current page. The boundary 0094
drew for attribute reuse is ownership, not availability, and here the component is not the
owner.

### 7. Motion tokens get readers; four stay unread, by name

The seven motion tokens shipped in 2a and nothing read them: the sheet wrote `150ms ease`
28 times and `100ms ease` once across sixteen declarations while reading a motion token zero
times. Three of them map exactly — `--motion-duration-fast` **is** `150ms`,
`--motion-duration-instant` **is** `100ms`, `--motion-easing-standard` **is** `ease` — so
wiring those was inert by construction and is done.

The remaining four map onto no literal in the sheet. They stay unread and are named as an
exact list rather than resolved either way, because both resolutions are worse. Deleting them
is a **contract change**, since the manifest publishes them. Giving them readers means
shipping overlay entrance and exit animations, which is a behaviour change wearing a token
wiring's clothes — and one no lane could see, because the screenshot lane runs with
`animations: "disabled"`.

That last clause is the general finding, and it outlived its occasion: **every duration and
easing in the sheet is invisible to the visual lane.** Worse for a `var()` in a shorthand — an
invalid substitution makes the whole declaration invalid at computed-value time and falls back
to `transition: all 0s`, which paints identically at rest and kills every transition in the
package. A structural test proves the sheet *names* a token; only the resolved value separates
the two. Hence a fourth workbench lane that reads computed values.

### 8. The scrollbar gutter is reserved, and the harness cannot witness why

`scrollbar-gutter: stable` joins the reset layer's existing `html` rules, so the content box is
the same width on a page that overflows and one that fits and the layout stops shifting
sideways on navigation. It is layered, so an app that prefers the jump can turn it off from its
own unlayered `theme.css`.

This is the widest visual change in the phase and it is a deliberate line rather than a fix
slipped in beside a refactor: it narrows every scroll-free page by the gutter's width. Measured
in the workbench: exactly 10px, uniformly, on 162 of 164 baselines, with **zero** height
changes across 31 distinct size pairs — a uniform shave, nothing reflowed.

And the honest limit, which had to be measured to be found: **the harness's Chromium reserves
no layout space for the viewport scrollbar at all.** With the declaration removed, a solo
specimen page and the many-screens-tall catalog both report a root box of 1280 in a 1280
viewport. So there is no jump in that browser to prevent, an assertion that the two page shapes
agree passes identically before and after, and the lane can witness only the reservation
itself, not the benefit. The benefit is real for the majority of desktop users, on browsers
that take scrollbar space — just not for the lane. Making the harness model one is possible and
deliberately not done: it would give every **inner** scroll container a space-taking bar too,
starting with the DataView's horizontal overflow, which is a change to component layout wearing
a harness change's clothes.

## Consequences

- Existing apps get the layout vocabulary, the archetypes and the nav model on a version bump
  with no app-file edits, which is the propagation lever the whole direction rests on. Nothing
  here adds a build step, a CSS export or a runtime dependency; react-core still publishes
  unbuilt `src/` and imports nothing but React.
- Two changes move pixels for every app: the scrollbar gutter (decision 8) and nothing else.
  The content measure, the archetypes and the primitives are inert until an app opts in.
- A new archetype is not a new template preset. The four presets (`blank`, `hub`, `process`,
  `portal`) are generated *home shapes* asserted by name; an archetype is a component. None of
  the archetypes added here generates a different landing screen, so the preset list does not
  move. A preset earns its place when the create wizard would generate something new.
- Widening the layout contract is not optional. `DetailPage`'s body slot admits
  `DetailList / Stack / Tabs / ModuleNav / DataView / Card` plus the framework states, so a
  `Grid` at the top of a detail body is refused today. Shipping `Grid` without widening both
  halves of the table ships a component no governed page can use — which is every generated
  project, since only the template switches the contract on.
- The icon-name union makes one class of manifest typo a typecheck error. Pre-1.0, that is a
  minor.
- `Separator` is `Divider`, and `LoadingButton` is `Button` with a loading state. Neither ships
  twice, and the inventory list that named them separately was an inventory rather than a
  design.

## Enforcement

- `markers.test.ts` — every new component's root marker joins the pinned inventory, and both
  ratchets stay empty: no new module-scope base style object, no new unmarked styled surface.
  `INLINE_STYLE_SITES` stays at nine files, which is decision 4 stated as a gate.
- `styles.test.ts` — a base rule per new marker on an exact selector; a gap rule per
  `SpaceToken` step for any new gap-reading marker; no `!important` anywhere; the
  reduced-motion selector list still naming every element that declares a transition; and
  every `transition` timed off the motion scale rather than a literal.
- `tokens.guard.test.ts` — every `var(--x)` names a contract-declared property, in both
  directions: the new shell geometry tokens must be published to be readable, and the unread
  motion tokens are pinned as an exact list so wiring one shrinks it and publishing an eighth
  forces the decision.
- `layoutContract.test.tsx` — byte-equal parity with `@terpjs/eslint-boundaries/src/layouts.js`
  for every new archetype and every widened slot, plus the allow-table marker set pinned as an
  exact array.
- The workbench — a specimen per new component and per new shell state, several of which need a
  contrived container to be observable at all (an `auto-fit` grid is a no-op at full page width;
  a vertical divider is zero-height in a block parent), and both platform baseline sets
  recorded. Lanes run one at a time, never as one command.
- `visual/computed.spec.ts` — the fourth lane, for resolved values the other three cannot see:
  the motion scale actually substituting, reduced motion actually reaching the three shapes the
  sheet names, and the gutter actually being reserved.

## Alternatives considered and not taken

- **Props for the shell's geometry.** Four inline styles on the shell root, an unthemeable
  surface handed across a public boundary, and a ledger entry each. Tokens give an app the same
  control with no prop and no site.
- **A portal for the subheader band.** Rejected on two verified facts, not taste: the slot
  check's DOM traversal, and the container-ref ordering that makes the first commit render
  locally and the second flip.
- **Container queries for the responsive primitives.** The more correct answer, deferred with
  the measurement it owes, because `contain: inline-size` on a page article or a card is a
  layout change in its own right.
- **A general `Modal` / `Drawer` / `Sheet`.** Declined in 0.9.0 and still declined. The
  reasoning was the reporting app's own comment: it built its editor in an expanded row and
  found that the better shape, and a general modal would remove the pressure that produced it.
  Terp ships **named** overlays with fixed semantics instead — a confirmation, an explicit
  post-action moment, and a command palette, which is no more a `Modal` than `Popover` is. A
  general `Drawer` would also be the framework's second drawer, since the shell's mobile
  sidebar already is one.
- **Deleting the four unread motion tokens.** The `--color-fg-on-brand` precedent points that
  way, and the difference is that those four are already published in the manifest, so removing
  them is a contract change while wiring them is not.
