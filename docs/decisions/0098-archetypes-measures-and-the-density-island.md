# 0098 — Three archetypes, two kinds of measure, and the density island

- **Status:** Accepted
- **Date:** 2026-08-21
- **Relates:** [ADR 0097](0097-shell-parameters-and-ordered-navigation.md) (the decisions this
  one *builds*, and the two places building them changed the design),
  [ADR 0079](0079-slot-typed-layout-contracts.md) (the slot tables every archetype here lands
  in, on both halves), [ADR 0094](0094-attribute-keyed-styling.md) (the attribute-versus-inline
  line, and §4's deferred comfortable island — which this ADR closes),
  [ADR 0093](0093-semantic-token-layer-and-named-themes.md) (the token vocabulary the shell's
  geometry and the sidebar's colours belong to).

---

## Context

0097 decided the shape of the shell and the navigation model. This ADR is what building the
first two thirds of it produced. It covers the archetype tier and the shell's parameters;
navigation is still unbuilt and 0097 §5 and §6 stand until it is.

Most of what follows is not a change of direction. Three things are, and each was forced by
measurement rather than argued from taste — which is why they are here rather than in a commit
message.

## Decision

### 1. The archetype tier is three components, and the fourth is a duplicate

`FormPage`, `SettingsPage` and `SplitPage` + `SplitPane` ship. `DashboardPage` does not.

`HubPage`'s grid is already `repeat(auto-fit, minmax(min(16rem, 100%), 1fr))` with
`grid-auto-rows: 1fr` — a uniform, equal-height tile grid — and its own docstring calls a card
carrying a `stat` "a lightweight dashboard". What a real dashboard needs beyond that is
*spanning* tiles, and `Grid` refused `span` in 4b. So a `DashboardPage` today is `HubPage` with
non-navigable tiles: two names for one grid, which is the `LoadingButton` mistake the phase has
now declined six times. It earns its place the day spans do, and that day is a `Grid` decision
rather than an archetype one.

Each new slot **refuses** something, and the refusals are the substance:

- A bare `Field` at the top of a **form** body. A run of fields is a form that cannot be
  submitted — Enter does nothing without a `<form>`, and the house spelling of one is
  `Stack as="form"`. Admitting `Field` would sanction precisely the screen that looks finished
  and cannot be used by keyboard.
- A collection in a **settings** body. No `DataView`, no `DetailList`, no `Tabs`: a settings
  screen whose body is a table is an overview wearing the wrong chrome. `Card` is how a titled
  region is owned here, which is the decision 4b made when it refused to ship `Section` — this
  is the first slot to depend on that rather than merely be compatible with it.
- Anything but a `SplitPane` inside a **split**.

### 2. `SplitPage` governs its panes, not its body — `HubPage`'s shape, not `DetailPage`'s

The obvious construction is one body slot holding two pane children. It does not work, for a
reason that is a fact about the control rather than a preference: `verifySlotChildren` takes a
single `slotOwner` and `Page` hands it `article.children`, so two panes are two
indistinguishable entries in one slot with nothing to say which is the list.

The alternatives were teaching the contract two slots per archetype, or making the panes the
governed thing. The second is what shipped: `SplitPage` owns the row element and admits
`SplitPane` in it and nothing else, exactly as `HubPage` owns its grid and admits `HubCard`.
`verifySlotChildren`, the mirrored table's shape and the message builder are all untouched, and
the vocabulary lands where it belongs — on the panes, which is what an author actually composes.

It therefore provides **no** `LayoutSlotContext`, for `HubPage`'s reason: the row carries a
marker no allow table names, so a slot context above it would refuse every split page on its own
body.

### 3. There are two measures, and they cap different things on purpose

This is the part most likely to read as an inconsistency, so it is stated as a decision.

**The shell's content measure caps the page's body and leaves its header spanning the track.**
That asymmetry *is* the subheader band: a full-width row above a constrained column is what tells
a reader the page is wider than its text.

**`Page`'s own `measure="narrow"` caps the whole frame, header included** — and `FormPage` and
`SettingsPage` default it on. A form is not a wide page with a narrow column; it is a narrow
page. A Save button floating a screen-width from the field it saves is worse than one sitting
over it.

`32rem` is not a new number: it is what `admin-form` declares on both packaged create screens
and what `ProfileView`'s card carries — which 4b already named as *a page measure wearing a
card's clothes*. Folding those three into the archetype is the follow-up.

### 4. The content measure is a `width`, not a `max-width`, and that is correctness

Its selector weighs (0,3,1). As a `max-width` it therefore **out-specifies** every component
declaring a narrower one, and five are legal children of a governed body. Measured before the
fix: an `admin-form` inside a measured shell computed `max-width: 1280px` instead of `512px`, so
the packaged provisioning form rendered two and a half times too wide — and `resource-list`
(40rem), `dialog` (26rem) and both `Text` measures lost theirs too, including the very prop this
mechanism was modelled on. A declaration meant to cap was assigning.

`width: min(100%, var(--shell-content-max-width))` composes instead of competing, because CSS
resolves `max-width` *after* `width`: a child with no measure of its own is capped, and a child
with one still wins with it. The general form is worth carrying: **a constraint that must yield
to a component's own belongs on a property the cascade resolves earlier, not on the same
property at higher specificity.**

The exemption is keyed on the `page-header` **marker** rather than the `header` **tag**, because
`:not(header)` exempts any `<header>` a bespoke page happens to render as a direct child — which
would hand it a second full-width band it never asked for.

### 5. The comfortable island ships, because the shell density is what asked

ADR 0094 §4 deferred a comfortable copy of the density tokens "until something asks", and
`DataView`'s docstring has named the gap ever since: inside an already-compact subtree,
`density="comfortable"` did not make anything comfortable, because comfortable was the
**absence** of an attribute and an absence cannot override an ancestor.

That was harmless while nothing could make an ancestor compact. `AppShell density="compact"`
makes `DataView density="comfortable"` a legal combination that silently does nothing — the
defect shape this phase has refused four times. So the deferral ends here rather than being
renewed: comfortable gains named tokens and a rule, and both values are stamped.

It composes through **inheritance, not specificity**. The nearest ancestor carrying either
attribute sets the live tokens for its subtree, so an island re-sets them; the two selectors
never match the same element, so they never compete. Unlayered, for the compact rule's reason.
And zero-diff by construction, because the comfortable values *are* the `:root` values.

### 6. The sidebar reads its own colour family; its edge is not a declared pairing

`--color-sidebar-bg` / `-fg` / `-muted` / `-accent` / `-border` were declared in all five themes
and read by nothing — twenty-five declarations, zero readers, for four releases. That is the
offence `--color-fg-on-brand` was deleted for, and the difference decides the remedy: there the
vocabulary was wrong, here the readers were missing. Wiring is the fix; deleting would have been
the mistake.

It survived because `tokens.guard.test.ts` tracked three token families and `--color-` was not
one of them. It tracks this one now.

Three pairings are declared and gated. A fourth is **deliberately not**: the sidebar's edge
against the canvas fails a 3:1 non-text floor in four themes, and it should — WCAG 1.4.11 covers
UI components and graphical objects needed to understand content, and a decorative separator
beside a surface that already differs in background is neither. Declaring it would have forced
darkening a decorative line in five themes for no accessibility gain, or booking an allowance
the ratchet may not grow. The reason lives in `token-pairs.json` so it is not re-added.

### 7. A skip link is only real if its target can hold focus

The shell owns it, because the shell owns the landmarks. The half that decides whether it works
is not the link: following a fragment link sets the browser's sequential-navigation starting
point but leaves `document.activeElement` on `<body>` unless the target is focusable. A skip
link over a plain `<main id>` therefore scrolls the viewport, leaves focus in the chrome, and
sends the next Tab straight back into the navigation it exists to skip — while looking correct
in a screenshot and under a manual click.

`main` carries `tabIndex={-1}`. The keyboard lane asserts the **landing**, not the reaching.

## Consequences

- Existing apps get all of it on a version bump with no app-file edits. Two changes move pixels:
  the sidebar's colour family (a faint light-theme background and a dimmer resting link ink) and
  nothing else. The archetypes, both measures and the density island are inert until an app opts
  in.
- `DataView`'s `density` prop changes behaviour: `"comfortable"` now stamps an attribute where it
  previously stamped nothing. Zero-diff wherever nothing above is compact, which is everywhere
  today.
- The inline-style ledger stays at nine files. Every prop added here is a closed set.
- `renderTerpApp` reaches `headerActions`, `contentWidth` and `density`; the first of those was a
  slot that existed on `AppShell` all along and was unreachable from the entry point every app
  uses.

## What 0097 still owes, and why it is not amended here

0097 §5 (navigation as ordered groups) and §6 (one owned active predicate) are **unbuilt**, and
this repo's convention is to amend an ADR *by building it* — both of 0097's existing amendments
say so in as many words. Two problems are already visible and are recorded here so they are not
rediscovered, but the amendments belong to the commit that resolves them:

- **`visible: (ctx) => boolean` cannot live on the contract.** `NavItem` is on the
  stack-agnostic manifest a future non-React adapter reads and a generator emits; a function
  field cannot cross that boundary. The predicate has to be declarative data that the adapter
  resolves.
- **Three of `NavContext`'s four inputs do not exist.** `CurrentUser` carries `permissions`,
  `role_name` and `role_rank`; superuser, per-module role ranks and internal-versus-external
  appear nowhere, and adding them is a backend and OpenAPI change. A `NavContext` built from
  what is real is honest; one built from 0097's list would be vocabulary with no source.
- **The sidebar has no element the shell owns per link.** 0097 §6 says the active predicate is
  keyed to the component's own `data-active` — but the shell renders the `<li>` and the
  *caller's router* renders the `<a>`, and `AppShell` deliberately imports nothing from the
  router. The predicate has to be delegated to the router-aware caller and stamped on the
  wrapper the shell owns, which is the answer 4b's `NavLinkRenderer` amendment already reached
  for a different reason.

## Alternatives considered and not taken

- **Teaching the layout contract two slots per archetype**, so a split's body could hold a list
  pane and a detail pane as siblings. More invasive than making the panes the governed thing,
  and it would have changed `verifySlotChildren`, the mirrored table's shape and the message
  builder for one archetype's benefit.
- **Keeping the content measure a `max-width` and darkening the components it out-specified.**
  It fixes the symptom by moving five components' measures to accommodate one rule's
  specificity, and leaves the next such rule to rediscover it.
- **Renewing ADR 0094 §4's deferral of the comfortable island.** Defensible right up to the
  moment the shell took a density; after that the deferral is a decision to ship a prop
  combination that silently does nothing.
- **Deleting the five unread sidebar colour tokens**, on the `--color-fg-on-brand` precedent.
  Rejected because that precedent is about vocabulary nothing *should* read; these are tokens the
  sidebar should always have read.
