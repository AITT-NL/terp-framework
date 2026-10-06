# 0179 — A canvas fills the screen from a page, not from a style

- **Status:** Accepted and implemented (2026-10-06). `WorkspacePage` and `CanvasHost` ship in
  `@terpjs/react-core`; the `standard` contract's `WorkspacePage` slot admits the host and the
  framework states. Held by `WorkspacePage.test.tsx`, `layoutContract.test.tsx` ("the
  workspace's body"), `styles.test.ts` ("a workspace fills the height the shell leaves it"), the
  workbench's computed lane (the canvas reaches main's content edge; every other main stays a
  block) and the `workspace-page` baselines on both platforms.
- **Date:** 2026-10-06
- **Relates:** [ADR 0099](0099-the-component-gap-and-what-is-not-in-it.md) (the bar a component
  meets), [ADR 0097](0097-shell-parameters-and-ordered-navigation.md) (the pipeline diagram that
  could not be built), [ADR 0123](0123-marketing-websites-are-not-a-terp-application-kind.md) (an
  escape hatch on every page is the API), [ADR 0175](0175-the-frontend-boundary-does-not-stop-at-the-module-tree.md)
  (the boundary this stays inside), [ADR 0168](0168-a-page-in-a-series-steps-through-it-from-a-bar-that-stays-put.md)
  (the `:has()` scoping this reuses), [ADR 0158](0158-a-quantity-is-shown-one-way.md) (svg drawn
  from tokens), [ADR 0079](0079-slot-typed-layout-contracts.md) (the contract)

---

## Context

Every archetype lays its body out as blocks, and each block is as tall as its content. A canvas
has no content height: a diagram of nodes and the connections between them, a floor plan or a
planning board takes the box it is given and draws into it. No archetype gave it a box. The
shell's main area is a block, the page is a grid that aligns its rows to the start, and nothing
in the vocabulary takes the height that is left. The only way to size a canvas was a `style`,
which app code may not write (ADR 0059), or a component outside `modules/`, which ADR 0175 has
just closed.

That puts the main screen of a diagram-first app on escape-hatch markers, on every page that
draws. ADR 0123 names where that ends: "an escape hatch used on every page is not an escape
hatch, it is the API, arrived at by erosion instead of by decision."

ADR 0099's bar is a consumer this framework can name, observed twice. The first is ADR 0097's
own record: a pipeline diagram "assembled out of `Badge`s joined by literal `{"→"}` string
children, which loses the direction of flow". The second is an app whose primary screen is a
diagram of nodes and connections, and which reached for exactly the two things the boundary
refuses: a sized box, and a canvas library's stylesheet.

## Decision

**A page archetype for work done on a surface, `WorkspacePage`.** It is the ordinary page (band,
trail, actions, summary, loading and error), and below the band its body takes every pixel the
shell leaves.

- **How it fills.** The same scoping the page-sequence bar uses (ADR 0168): the shell's main
  area becomes a flex column only when it holds a workspace (`:has()` on the article's
  `data-fill="workspace"`), the page grows into it, and inside the page the host grows into what
  the band and the summary leave. No other page changes. The computed lane holds both halves:
  the canvas's bottom edge is main's content edge, and an ordinary page's main is still a block.
- **How the page knows.** `Page` reads the slot owner the archetype already provides, so there
  is no `fill` prop for any other page to set.

**One primitive in its slot, `CanvasHost`.**

- **What it is.** A named `<section>` (a landmark, so its `label` is required), painted from
  tokens only: the surface fill, and the hairline and radius a `Card` uses.
- **How it holds a canvas.** It clips, so a canvas panned past its edge never paints over the
  band. Outside a shell it keeps a 24rem floor. Each child is laid over the whole host,
  absolutely, inset 0 and at an explicit 100%.
- **Why the explicit 100%.** An `<svg>` is a replaced element: with only the inset, it took its
  width from the box and its height from its viewBox's ratio, and sat at the top of a tall
  canvas. The first recording of the baseline showed that, and the rule says so.

**The contract governs the workspace, not the drawing.** The `standard` contract's
`WorkspacePage` slot admits `CanvasHost` and the framework states (`EmptyState`, `ErrorState`,
`LoadingState`, `Alert`) and nothing else. A second block beside the canvas would have to share
a height nobody declared. What is drawn on the host is the app's, as a `Card`'s body is: the
contract governs a slot's direct children (ADR 0079).

**A diagram is buildable inside the pattern now.** An `<svg>` painted through attributes that
name tokens (`fill="var(--color-bg-subtle)"`, `stroke="var(--color-fg-subtle)"`), which is how
ADR 0158 draws charts, needs no style, no class and no marker. The workbench's `workspace-page`
specimen is drawn exactly that way, and passes axe in all five themes.

## Consequences

**Not decided here: a canvas library.** A library such as a node-graph editor ships its own
stylesheet and theming variables. The boundary refuses that stylesheet in app source (ADR 0175),
and it should: a library's global sheet paints outside the palettes and outside what the contrast
gate measures. The answer this ADR points to is a framework-owned bridge, an optional package
that imports one library's sheet, maps its theming variables to Terp tokens, and adds those
pairings to what the contrast gate measures. Which library earns it is the owner's decision, and
under ADR 0099 it needs its own consumer. Until then an app using such a library carries the
stylesheet import as a budgeted `terp-allow-no-style-imports` marker with its reason: visible,
counted and reviewable, which is what the governed escape hatch is for.

**Only the workspace changes.** Every selector added is keyed on `data-fill="workspace"` or on
the new marker, and the full screenshot lane re-ran with no other baseline moved.
