# 0098 — Archetypes, measures, the density island, and a shell that can move its navigation

<!-- The filename still says `archetypes-measures-and-the-density-island`, which is what
     this ADR covered when it was opened. It gained the skip link (§7) and the header
     placement (§8) as 4d finished, and an ADR is cited by number rather than by slug, so
     the heading widened and the file did not. Recorded rather than renamed: a broken
     link is a worse cost than a slug one section out of date. -->

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

- A bare `Field` at the top of a **form** body, so the body is always a container rather than a
  loose run of controls.

  The stronger claim — that this prevents a form which cannot be submitted — is one this ADR
  made first and it is **wrong**, so it is corrected here rather than quietly dropped. Both
  halves of the contract match on `data-terp` markers, and `Stack` renders the same marker
  whether or not it was given `as="form"`. `<Stack><Field/></Stack>` therefore passes and is
  still unsubmittable by Enter. Closing that would need a second marker for the form case: six
  more names describing the same DOM, which is the `Section` trade 4b declined. The general
  point is worth keeping — **a contract keyed on markers can constrain what a body contains,
  never how a component was configured.**
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

Its selector weighs (0,4,0) — four attribute selectors, one of them inside `:not()`, with the
universal contributing nothing. As a `max-width` it therefore **out-specifies** every component
declaring a narrower one, and five are legal children of a governed body: `admin-form` at
(0,1,0), `text[data-measure]` at (0,2,0), and the rest below that. Measured before the
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
would hand it a second full-width band it never asked for. That swap is also what took the
selector from (0,3,1) to (0,4,0): an attribute inside `:not()` weighs more than an element does.
It strengthens the argument above rather than weakening it — and it is the reason the number is
stated here rather than left to be recomputed, since the first three places it was written down
kept the pre-swap figure.

### 5. The comfortable island ships, because the shell density is what asked

ADR 0094 §4 deferred a comfortable copy of the density tokens "until something asks", and
`DataView`'s docstring has named the gap ever since: inside an already-compact subtree,
`density="comfortable"` did not make anything comfortable, because comfortable was the
**absence** of an attribute and an absence cannot override an ancestor.

That was harmless while nothing could make an ancestor compact. `AppShell density="compact"`
makes `DataView density="comfortable"` a legal combination that silently does nothing — the
shape this phase keeps refusing, most recently in the union that makes `Select`'s two forms
mutually exclusive. So the deferral ends here rather than being
renewed: comfortable gains named tokens and a rule, and a component stamps whichever value it
was asked for.

**Asked for, and not defaulted** — which shipped wrong once and is worth the sentence. Giving
`AppShell` a `density` default of `"comfortable"` reads as harmless, because comfortable is the
`:root` value. It is not, and the island is exactly why: now that comfortable has a rule,
stamping it on the shell root overrides `data-density="compact"` on `<html>`, which 0094 §4
names as *the app-wide case*. An unasked-for shell prop must not beat an app-wide choice, so
absence means "inherit whatever is above me".

It composes through **inheritance, not specificity**. The nearest ancestor carrying either
attribute sets the live tokens for its subtree, so an island re-sets them; the two selectors
never match the same element, so they never compete. Unlayered, for the compact rule's reason.
And zero-diff by construction, because the comfortable values *are* the `:root` values.

### 6. The sidebar reads its own colour family; its edge is not a declared pairing

`--color-sidebar-bg` / `-fg` / `-muted` / `-accent` / `-border` were declared in all five themes
and read by nothing — twenty-five declarations, zero readers, for three releases. That is the
offence `--color-fg-on-brand` was deleted for, and the difference decides the remedy: there the
vocabulary was wrong, here the readers were missing. Wiring is the fix; deleting would have been
the mistake.

It survived because `tokens.guard.test.ts` tracked three token families and `--color-` was not
one of them. It tracks this one now.

**One** pairing is newly declared and gated — the hovered link. The resting link and the brand
were already in `token-pairs.json` as `sidebar-muted-text` and `sidebar-text`, declared when the
family shipped and gated ever since against tokens nothing read; a first draft added
byte-identical duplicates of both, which would have reported one defect twice and inflated the
coverage count. A further pairing is **deliberately not** declared: the sidebar's edge against
the canvas fails a 3:1 non-text floor in four themes — 1.18:1 light, 1.35 midnight, 1.50
twilight, 1.72 dark, with only `contrast` clearing it at 7.00 — and it should, because WCAG
1.4.11 covers
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

Three things follow from that `tabIndex`, and two of them were wrong in the first build:

- **The target must not paint the shared focus ring.** `main` carries a `data-terp` marker, and
  with a `tabIndex` it comes into scope of `[data-terp]:focus-visible` — so following the link
  outlined the whole content column plus a 3px halo. The ring's job is to say which *control*
  takes the next keystroke; a scroll target that took focus programmatically is not one. Scoped
  to this marker rather than to `[tabindex="-1"]`, because other elements take `-1` for other
  reasons and some of them are controls.
- **The link must not exist while the drawer is open.** The drawer is `aria-modal` and the column
  below it is `inert`. A link outside both, pointing *at* the inert subtree, contradicts each of
  them, and whether a keyboard route to it exists depends on where the browser's
  sequential-navigation starting point happens to be — not something an accessibility guarantee
  should rest on. Stacking order does not help: z-index has no bearing on tab order, and the
  first build's comment claimed it did.
- **The id is per instance,** not a module constant, because a page with two shells otherwise
  renders two `<main id="terp-main">` and both links jump to the first one. The workbench
  catalogue is that page.

### 8. The nav can live in the header, and moving it moves its surface with it

`AppShell` has had one shape: a full-height sidebar, collapsing to an icon rail. That is right
for the app it was built against and wrong for the one the template already offers to
generate — the `portal` preset, "a personal landing for customers, staff or suppliers", which
gets 15rem of permanent chrome for three destinations. An app cannot opt out, because it cannot
write `style` or `className` and the shell takes no say in the matter.

`navPlacement="header"` renders the same brand, the same nav and the same user menu inside the
header and no sidebar at all. Four decisions inside that.

**It is desktop-only, and the attribute says so.** Below the breakpoint both placements are the
drawer — a horizontal row of links does not fit 420px, and the drawer already exists, focus trap
and all. So the shell derives the attribute from the viewport rather than stamping it from the
prop, exactly as it derives `data-collapsed`. Every rule keyed on it is then free of a
`[data-variant="desktop"]` guard, because the attribute is absent whenever it would not be true.

**The header becomes the sidebar surface** — one declaration where six overrides would have
gone. The brand, the brand title, the resting link, the hover wash and the active link all
already read `--color-sidebar-*`; moving the *surface* carries the family with it and nothing is
overridden. It is also the only reading that survives theming: an app painting its sidebar navy
gets a navy header with the same legible ink, where per-property overrides would have given it
navy ink on a white header. The proof the mechanism is right rather than merely short is that
the contrast gate needs nothing new — the declared sidebar pairings are still exactly the
pairings in play.

**No toggle**, and that is correctness rather than tidying: the control carries `aria-expanded`,
so rendering it with no sidebar would announce a state about an element that does not exist. The
brand takes the slot, which is the other thing the sidebar was carrying. The user menu moves to
the end of the header group — losing it is the failure a placement prop invites, since it is
where an app puts sign-out.

**`defaultCollapsed` is `never` under `"header"`.** With no sidebar there is nothing to collapse,
so the pair would type-check, do nothing and give no sign of it. Two things follow from the same
fact and only one of them is a type: the rail choice is *persisted*, so a user who had collapsed
the sidebar before the app moved its nav would get icon-only links in a header with room for
labels, and the attribute that normally reveals the rail state lands nowhere. `railCollapsed`
forces false, with a test that fails on the leak.

The third of the three rules — `overflow: visible` on the header-placed nav — is a fix and no
baseline can hold it. The sidebar's nav is a vertical scroll container, and a computed
`overflow-y` other than `visible` forces `overflow-x` to `auto` too; in a header the box is
exactly one link tall, so that scroller can never scroll and its only effect is to clip a focused
link's outline and ring on both edges. The computed lane asserts the **pair** — visible in the
header, `auto` in the sidebar — because a rule that simply set `visible` everywhere would satisfy
half of it while silently taking the sidebar's scrolling away.

### 9. The brand mark gets a box, a pair, and no third slot

Three things were missing from the brand and only two of them turned out to be slots.

**A box.** The brand link handed whatever it was given straight into a flex row, so an app's
asset sized itself — and an oversized one was clipped by the sidebar's `overflow-x: hidden`,
with nothing to say so, in the 4rem rail where a mark most needs to survive. `--shell-brand-size`
is published and the mark renders inside it. Zero-diff: the default `TerpMark` is 28px and the
token is `1.75rem`, so the box is exactly the size of the thing that used to be the flex item.

**A pair, because a brand is not a `currentColor` glyph.** Every bundled icon strokes in
`currentColor` and themes for free; a company mark usually cannot, and a dark-ink one is
invisible on three of the five shipped themes — so an app with a real logo could not use them.
`logoDark` renders a second mark and the **stylesheet** picks.

Not React, and that is the load-bearing part. The theme is `<html data-theme>`, which an app may
set from its own `main.tsx` with no `ThemeProvider` mounted at all, and `AppShell` is used
directly by every specimen and every test. A React branch would need a context the shell does
not require, and would fail by showing the wrong mark rather than by failing.

Which themes count as dark is the part that would rot. Enumerating them in the framework
stylesheet is a list that goes stale the first time a theme is added — and stales *silently*,
on the new theme only. `themes.json` already requires an `appearance` per theme and the token
build already emits `color-scheme` from it, so it emits `--appearance-show-light` /
`--appearance-show-dark` from the same field. A sixth theme cannot forget to answer.

That pair is a **mechanism, not a design token**, and saying so cost two widened gates —
which is the right price, because both gates were stating something true and now state it more
precisely. Geometry is theme-invariant *except* this pair, subtracted by name rather than by
prefix; and the manifest names every base-root token *except* this pair, because a theme editor
offering `block` / `none` offers a way to break the switch rather than a way to theme anything.
The list lives in a hand-written module rather than being imported from the generator that emits
it: importing it would make every future addition self-approving. A third such property fails
both gates until someone writes down why. And a new gate covers the half a subtraction cannot:
every theme must declare **both** halves and show exactly one, because a theme that declared
only `show-light` would inherit the base value for the other and display both marks.

**No third slot**, and the refusal is the useful part. A separate collapsed mark was on the list
until the rail was looked at: the rail already separates the two halves of a brand, because
`logo` is the mark and `title` is the wordmark, and collapsing hides the title. An app whose
logo is a wide lockup should split it that way rather than supply a third asset — and the only
thing that was actually missing for that to work is the box above.

**The tab is the other half of the seam.** The template's `index.html` declared no icon at all,
which in a single-page app is worse than a 404: the browser's default request for
`/favicon.ico` is answered with `index.html`, so it receives HTML where it asked for an image and
falls back to a generic mark with nothing logged anywhere. The template now ships
`public/favicon.svg` and links it, and the file carries both appearances in its own
`prefers-color-scheme` block — a favicon is a separate document and never sees the page's
tokens, so `var(--color-brand-primary)` there would resolve to nothing and paint an empty
square. Gated in both directions: the file must exist and the link must point at it.

## Consequences

- Existing apps get all of it on a version bump with no app-file edits. **One** change moves
  pixels: the sidebar's colour family — a faint light-theme background, a dimmer resting nav-link
  ink in every theme, and a different hover wash in four of the five. The archetypes, both
  measures and the density island are inert until an app opts in.

  (This bullet was written as "Two changes move pixels … and nothing else" and then named one,
  which is the sentence shape the same series had just corrected in 0097. Worth recording rather
  than quietly fixing: the defect is not a typo, it is what happens when a count is written
  before the list it counts.)
- `DataView`'s `density` prop changes behaviour: `"comfortable"` now stamps an attribute where it
  previously stamped nothing. Zero-diff wherever nothing above is compact, which is everywhere
  today.
- The inline-style ledger stays at nine files. Every prop added here is a closed set.
- `renderTerpApp` reaches `headerActions`, `contentWidth`, `density` and `navPlacement`; the
  first of those was a slot that existed on `AppShell` all along and was unreachable from the
  entry point every app uses.
- The header placement adds two baselines and no diffs: every existing shell specimen is
  byte-identical, because the attribute it is keyed on is absent unless an app asks. The brand
  box adds two more and likewise moves nothing, because the box is the size of the mark that was
  already there.
- `--shell-brand-size` is a fifth published shell token; `--appearance-show-light` /
  `--appearance-show-dark` are deliberately **not** published, and the two gates that let them
  through name them one by one.

## What 0097 still owes, and why it is not amended here

0097 §5 (navigation as ordered groups) and §6 (one owned active predicate) are **unbuilt**, and
this repo's convention is to amend an ADR *by building it* — 0097's second amendment says so
verbatim ("Amended in 4b, by building it") and its first says the same in other words ("building
it produced the opposite and better shape"). Two problems are already visible and are recorded here so they are not
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
