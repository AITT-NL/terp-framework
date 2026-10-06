# 0179 — A canvas fills the screen from a page, not from a style

- **Status:** Accepted and implemented (2026-10-06). `WorkspacePage` and `CanvasHost` ship in
  `@terpjs/react-core`; the `standard` contract's `WorkspacePage` slot admits the host, the
  framework states and `ConfirmDialog`. Held by `WorkspacePage.test.tsx`,
  `layoutContract.test.tsx` ("the workspace's body"), `styles.test.ts` ("a workspace fills the
  height the shell leaves it"), the workbench's computed lane (the canvas reaches main's content
  edge and its drawing fills the host; a page in a shell that is not a workspace keeps main a
  block; the canvas takes the full track in a measured shell), the keyboard lane (a canvas
  reached by Tab shows the shared ring on its host) and the `workspace-page` baselines on both
  platforms.
- **Date:** 2026-10-06
- **Relates:** [ADR 0099](0099-the-component-gap-and-what-is-not-in-it.md) (the bar a component
  meets), [ADR 0097](0097-shell-parameters-and-ordered-navigation.md) (the pipeline diagram that
  could not be built, and in §2 the content measure the host is exempt from),
  [ADR 0123](0123-marketing-websites-are-not-a-terp-application-kind.md) (an escape hatch on
  every page is the API), [ADR 0175](0175-the-frontend-boundary-does-not-stop-at-the-module-tree.md)
  (#147; the boundary this stays inside), [ADR 0168](0168-a-page-in-a-series-steps-through-it-from-a-bar-that-stays-put.md)
  (the `:has()` scoping this reuses), [ADR 0158](0158-a-quantity-is-shown-one-way.md) (svg drawn
  from tokens), [ADR 0079](0079-slot-typed-layout-contracts.md) (the contract)

---

## Context

Every archetype lays its body out as blocks, and each block is as tall as its content. A canvas
has no content height: a diagram of nodes and the connections between them, a floor plan or a
planning board takes the box it is given and draws into it. No archetype gave it a box. The
shell's main area is a block, the page is a grid that aligns its rows to the start, and nothing
in the vocabulary takes the height that is left. The only way to size a canvas was a `style`,
which app code may not write (ADR 0059), or a component outside `modules/`, which ADR 0175
(#147, merged ahead of this) closes.

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
shell leaves. Its trail is `parents`, typed and passed as `DashboardPage`'s is; it takes no
`breadcrumbs` and no `measure`.

- **How it fills.** The same scoping the page-sequence bar uses (ADR 0168): the shell's main
  area becomes a flex column only when it holds a workspace (`:has()` on the article's
  `data-fill="workspace"`), the page grows into it, and inside the page the host grows into what
  the band and the summary leave. No other page changes. The computed lane holds both halves:
  the canvas's bottom edge is main's content edge, and main around an ordinary page in a shell
  is still a block.
- **What fills while the canvas is not there.** A `LoadingState`, `ErrorState` or `EmptyState`
  in the canvas's place grows the same way, keeps the host's 24rem floor and centres its
  message, so the frame does not jump when the canvas arrives. An `Alert` does not: it is a line
  of the page above the canvas, and the canvas takes what it leaves.
- **How the page knows.** `Page` reads the slot owner the archetype already provides, so there
  is no `fill` prop for any other page to set.
- **In a measured shell.** `contentWidth: "measured"` caps every body child at the measure
  except the two bands (ADR 0097 §2). The host is exempt as they are: the measure exists for
  reading, and a canvas is not read along a line. Capped, it stopped at the measure against the
  start of a wider track, under a band that ran past it. It joins the rule's one `:not()`, so the
  rule weighs what it did.

**One primitive in its slot, `CanvasHost`.**

- **What it is.** A named `<section>` (a landmark, so its `label` is required), painted from
  tokens only: the surface fill, and the hairline and radius a `Card` uses.
- **How it holds a canvas.** It clips with `overflow: clip`, so a canvas panned past its edge
  never paints over the band. `clip` rather than `hidden`, because `hidden` makes the host a
  scroll container, and focus moving to something near the canvas's edge could scroll the
  drawing inside its frame. Outside a shell it keeps a 24rem floor.
- **Through a layer of its own.** The host renders one inner element, `canvas-host-layer`,
  absolutely positioned at inset 0, and the canvas is that layer's child at 100% in both
  directions. The layer exists because the host's height comes from flex growth inside a column
  that is only `min-height` tall, so a percentage height resolved against the host is not
  definite, and positioning the canvas itself absolutely does not hold for a library: a canvas
  library's root is sized by the library's own sheet (commonly `position: relative` and a 100%
  size), and an unlayered sheet beats every rule in Terp's layers. No library styles the layer,
  and an absolutely positioned box at inset 0 has a definite size, so the root's 100% resolves.
- **Why the explicit 100%.** An `<svg>` is a replaced element: given only a box, it took its
  width from the box and its height from its viewBox's ratio, and sat at the top of a tall
  canvas. The first recording of the baseline showed that, and the rule says so.
- **One canvas per host, one host per workspace.** Every child of the layer takes the whole
  layer, so a second child does not share the box: it lands below the first and is clipped. A
  `ConfirmDialog` is the exception and keeps its own size, because an open modal dialog sits in
  the top layer and a 100% height would stretch it over the viewport. Two hosts in one workspace
  would split its height between them; the slot is written for one.
- **Its focus ring is drawn on the host.** A canvas that answers keys takes focus, and it fills
  the layer edge to edge, so a ring around it lies wholly outside the host's padding box and the
  clip removes all of it: a keyboard user on the canvas saw no indicator. While the layer's
  child matches `:focus-visible`, the host draws the framework's shared ring on itself, the same
  three declarations as `[data-terp]:focus-visible`, in `terp.state` beside it. The host's own
  outline and shadow sit outside the box it clips.

**The contract governs the workspace, not the drawing.** The `standard` contract's
`WorkspacePage` slot admits `CanvasHost`, the framework states (`EmptyState`, `ErrorState`,
`LoadingState`, `Alert`) and `ConfirmDialog`, as the other governed bodies that hold content
rather than panes or cards do, so an action taken on the canvas (deleting a node) has somewhere
to ask. Nothing else is admitted: a second block beside the canvas would have to share a height
nobody declared. What is drawn on the host is the app's, as a `Card`'s body is: the contract
governs a slot's direct children (ADR 0079).

**A diagram is buildable inside the pattern now.** An `<svg>` painted through attributes that
name tokens (`fill="var(--color-bg-subtle)"`, `stroke="var(--color-fg-subtle)"`), which is how
ADR 0158 draws charts, needs no style, no class and no marker. The workbench's `workspace-page`
specimen draws one that way and passes axe in all five themes. Its strings are literals, as
everywhere in the workbench; app code passes message descriptors.

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

**Not decided here: the shell's height on a phone.** The shell is `min-height: 100vh`, and a
mobile browser's `100vh` is the viewport with its toolbar retracted. While the toolbar shows,
the shell is taller than what is visible, so a workspace's canvas ends below the fold by the
toolbar's height. `100dvh` would follow the toolbar, but it moves the shell, and with it every
page, so it is the shell's decision rather than a side effect of this one. Nothing in the shell
changes here.

**Only the workspace changes.** Every selector added is keyed on `data-fill="workspace"` or on
the two new markers; the one shared rule touched, the measure's `:not()`, gains an entry for the
host and nothing else. The full screenshot lane re-ran with no other baseline moved.
