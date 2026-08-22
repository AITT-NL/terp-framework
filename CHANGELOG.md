# Changelog

All notable changes to the Terp platform. Terp releases **in lockstep**: every backend
distribution (`terp-core`, `terp-arch`, `terp-cli`, `terp-migrations`, `terp-cap-*`) and
every frontend package (`@terpjs/contract`, `@terpjs/react-core`,
`@terpjs/eslint-boundaries`, `@terpjs/conformance`) carries the same version and
publishes from the same tag
(`v<version>`); the gate enforces the lockstep (`tests/architecture/test_release_versions.py`).

The full rationale trail lives in [docs/decisions/](docs/decisions/) — one ADR per
decision, 0001 onwards.

## 0.10.0

### Added

- **Density reaches the shell, and the comfortable island exists (ADR 0094 §4, ADR 0098 §5).** `AppShell`
  takes `density`, threaded through `buildAppRouter` and `renderTerpApp`: one attribute on the
  shell root, from which every control height and cell padding follows by token inheritance,
  with no prop on anything below.

  Shipping that alone would have created a defect, and `DataView`'s own docstring had been
  describing it for two releases: *"inside an already-compact subtree, `density="comfortable"`
  does not make [anything comfortable] … until the shell takes a density of its own."*
  Comfortable was the **absence** of an attribute, and an absence cannot override an ancestor.
  That was harmless while nothing could make an ancestor compact. A shell density makes
  `AppShell density="compact"` + `DataView density="comfortable"` a legal combination that
  silently does nothing — the shape this phase keeps refusing, most recently in the union
  that makes `Select`'s two forms mutually exclusive. (A running tally was written into five
  places in one commit and two of them said three. A citation keeps where a count rots.)

  So comfortable gained named tokens and a rule of its own, which is the vocabulary ADR 0094
  deferred *until something asked*. The mechanism is the compact rule mirrored, and it composes
  through **inheritance rather than specificity**: the nearest ancestor carrying either
  attribute sets the live tokens for its subtree, so an island simply re-sets them, and the two
  selectors never match the same element so they never compete. Unlayered, for the compact
  rule's reason — inside a layer it would lose to the contract's own `:root` values whenever the
  attribute lands on `<html>`.

  Zero-diff by construction and checked as such: the comfortable values *are* the `:root`
  values, so stamping the attribute where nothing above is compact computes exactly what it
  computed before — all **236** existing baselines byte-identical at that commit, including
  `dataview-compact`.
  What the island costs is one specimen with two tables, because one table cannot show an
  island: deleting the rule collapses them into each other and repaints 20,274 pixels.

- **The sidebar paints from its own colour family, three releases after that family shipped
  (ADR 0098 §6).**
  `--color-sidebar-bg` / `-fg` / `-muted` / `-accent` / `-border` were declared in **all five
  themes** and read by **nothing** — twenty-five declarations, zero readers. That is the offence
  `--color-fg-on-brand` was deleted for; the difference is that there the vocabulary was wrong,
  and here it was right and the readers were missing. So wiring is the fix and deleting would
  have been the mistake. It went unnoticed because `tokens.guard.test.ts` tracked three token
  families and `--color-` was not one of them; it tracks this one now, as an empty list.

  Mostly inert, **recounted** rather than estimated: **fifteen** of the twenty-five already
  equalled the neutral the sheet was reading — background, foreground and border agree in every
  theme except the light background. Ten move, in three groups, and an earlier draft of this
  entry named two of them: it counted the resting declarations and forgot that `accent` is one
  of the five.

  The light sidebar goes `#ffffff` → `#f8fafc`, the faint separation from the canvas that every
  dark theme already had and light never did. The nav link's resting ink dims in every theme —
  light `#334155` → `#475569`, dark `#e2e8f0` → `#b4c0d0` — which is the deliberate half: a
  sidebar's resting links are secondary to the page, and the active one should carry the weight.
  And the **hover wash** changes in four themes: every one but light, where the two values
  already agree.

  Verified as a transformation rather than accepted as a diff, and the light/dark asymmetry is
  what makes it checkable. Light repaints **205,159 px** on each of the three full-shell
  specimens and **54,353** on the collapsed rail — a narrower sidebar, less area, consistent
  with a *background* change. Dark repaints **666** and **164** — three hundred times smaller,
  consistent with only the link ink moving, which is exactly what the token values predict since
  dark's background, border and foreground are byte-identical to the neutrals they replaced.
  `app-shell-mobile` does not move at all: its sidebar renders only when the drawer is open.

  **One** pairing is newly declared — the hovered link — measured before being declared rather
  than after. The resting link and the brand were already in `token-pairs.json` as
  `sidebar-muted-text` and `sidebar-text`, declared when the family shipped and gated ever
  since against tokens nothing read; a first draft added byte-identical duplicates of both,
  which would have reported one defect twice and inflated the coverage count. All of them
  measure 7.24:1 light, 7.94 dark, 7.50 midnight, 7.60 twilight and 18.42 for `contrast`
  against its AAA floor. A further pairing was **withdrawn**: the
  sidebar's edge against the canvas fails a 3:1 non-text floor in four themes — 1.18:1 light,
  1.35 midnight, 1.50 twilight and 1.72 dark, with only `contrast` clearing it at 7.00 — and
  it should, because
  WCAG 1.4.11 covers UI components and graphical objects needed to understand content, and a
  decorative separator beside a surface that already differs in background is neither. Declaring
  it would have forced darkening a decorative line in five themes for no accessibility gain. The
  reason is recorded in `token-pairs.json` so it is not re-added.

- **`defaultDrawerOpen`, and four rules get their first picture.** Below the breakpoint the
  sidebar renders only while `drawerOpen` is true, which is internal state with no way in — so
  the drawer's `position: fixed`, its `100dvh`, its z-index and shadow, and the backdrop's
  `inset: 0` have shipped unpainted since they were written. `styles.test.ts` asserts them as
  text with "no baseline can hold it" beside them, and that was true: a per-specimen viewport is
  not enough, because `app-shell-mobile` already renders at 420×900 and shows the drawer
  **closed**. This is the same door `defaultCollapsed` opened for the icon rail, where four
  rules were likewise unpainted behind it.

  `overlay: true`, and not as a precaution: the drawer is `position: fixed` and the backdrop is
  `inset: 0`, so an element shot would clip to the card and record the page behind them.

- **Skip to content, which the shell owns because the shell owns the landmarks (ADR 0098 §7).** There was no
  skip link and `main` had no id. The same change also named the desktop `aside`, which looked
  like a third fix and was not: the `nav` immediately inside it already carries that exact
  string, so the landmark list gained a "Primary" complementary containing a "Primary"
  navigation. Reverted to mobile-only, where the `dialog` role demands a name. Naming the aside
  is a separate decision with a string to choose, not a side effect of adding a skip link.

  The half that decides whether it works is where focus lands. Following a fragment link sets
  the browser's sequential-navigation starting point but leaves `document.activeElement` on
  `<body>` unless the target is focusable — so a skip link over a plain `<main id>` scrolls the
  viewport, leaves focus in the chrome, and sends the next Tab straight back into the navigation
  it exists to skip. It looks correct in a screenshot and under a manual click. `main` carries
  `tabIndex={-1}`, and the keyboard lane asserts the landing rather than the reaching; removing
  it puts `activeElement` at `null` and fails.

  The target also must not paint the shared focus ring. `main` carries a `data-terp` marker and
  now a `tabIndex`, which together put it in scope of `[data-terp]:focus-visible` — so following
  the link outlined the entire content column, header to footer, plus a 3px halo. The ring says
  which *control* takes the next keystroke; a scroll target that took focus programmatically is
  not one.

  The visible rule sits in `terp.state`, which is load-bearing rather than filing: the resting
  half is the shared visually-hidden block in `terp.base`, and a selector list takes the
  specificity of the member that **matches** — here `[data-terp="appshell-skip-link"]` at
  (0,1,0), the same weight as the un-hiding rule. (A first draft cited the list's (0,3,0)
  member, which is the collapsed-rail selector and never matches a skip link; on that reading
  the two rules would have been a source-order coin flip rather than a layer decision.) Layer
  order settles it with nothing to reason about.

  `--z-index-skip-link` (45) sits above the sticky header and its backdrop so it is not painted
  under the chrome it overlaps, and below the drawer because nothing paints over an open modal.
  Stacking order does **not** keep it out of the drawer's focus trap and a first draft claimed
  it did — z-index has no bearing on tab order. The link is simply **not rendered** while the
  drawer is open: the drawer is `aria-modal` and the column below it is `inert`, so a link that
  sits outside both and points *at* the inert subtree is the one element contradicting each of
  them, and with the drawer open there is nothing to skip to anyway.

  The id is **per shell instance** (`useId`), not a module constant. A constant is wrong wherever
  two shells mount together — every one renders `<main id="terp-main">` and a link to it, so each
  link jumps to the first shell on the page. The workbench catalogue is exactly that page. It was
  also documented as an exported `MAIN_CONTENT_ID` and never re-exported from the entry point, so
  the one argument for sharing it had no consumer either.

- **Nav and route visibility is declarative data, and it gates the route as well as the link
  (ADR 0097 §5, amended in 4e).** `NavItem` and `ModuleRoute` take `permission`, a named grant
  from `CurrentUser.permissions`, **ANDed** with the `role` they already had.

  0097 specified `visible: (ctx) => boolean`. A function cannot live on the manifest — it is
  stack-agnostic, serialisable, and a generator emits it — so the predicate had to become data.
  The interesting part is what the data can honestly say. 0097's `NavContext` named module
  grants, per-module role ranks, superuser and internal-versus-external; `CurrentUser` carries
  **none** of the four. It carries `role_rank`, `role_name` and `permissions`, and the last is
  the general mechanism the decision never named. So the context is two fields built from what
  `/me` actually returns, rather than four built from a wish.

  The AND is not a design choice, it is a mirror: a server `Policy` carrying a `Permission`
  enforces the permission's role floor **and** the grant, which is the same reasoning the
  `Authorized` component's own `permission` prop already records. Reusing that shape means the
  navigation gains the gate the buttons already have instead of a second vocabulary for one idea.
  No combinator, and the decisive reason is on the server: `AuthzRef` is one ref per read and one
  per write, so an any-of on the client could express a gate no `Policy` can declare, and a
  client gate with no possible server counterpart can only drift from the endpoint it mirrors.

  **It is declared on `ModuleRoute` too, and that is the half worth insisting on.** A nav-only
  gate hides the link and leaves the route reachable by URL, which is not a weaker form of
  authorization but the appearance of one. `role` has never had that asymmetry — it is declared
  on both — and `permission` does not get to introduce it. The mutation that removed the route
  gate left the entire suite green, which is how the missing test was found.

  `visibleNav`'s context is a **required** argument, and the break is deliberate. Optional would
  have been source-compatible and silently wrong: an existing two-argument caller would fail
  closed on every item that gained a `permission` and quietly drop links from a sidebar with no
  error anywhere. Required turns it into a typecheck error at the one call site each app has.
  Listed here with the icon union as the release's breaking changes.

  Fails closed three ways, each with a test: signed out (rank is null before permissions are
  consulted), an unknown or misspelled name, and an app that mounts no grant capability — whose
  empty list must hide everything that names a permission rather than waving it through. Five
  mutations, five reds, including the two that started green.

- **The shell decides which nav item is current, and the router is told rather than asked
  (ADR 0097 §6, amended in 4e).** `AppShell` takes `activePath`, resolves the set once, and
  passes `active` on the link context it already had. `buildAppRouter` supplies the router's
  pathname and pins every nav `Link` to `activeOptions: { exact: true }` with the shell's verdict
  as `aria-current`.

  That pinning is the whole mechanism, and it is one line doing the work of a new attribute and a
  new rule. `aria-current` is not among the props `useLinkProps` destructures, so a value passed
  in survives into the anchor; the router's own active props are spread **last**, but only when
  it considers the link active. Under exact matching, "the router considers this active" implies
  the link's path equals the URL — the longest possible match, hence always the item the shell
  picked. **The router can agree or stay silent; it cannot name a second current item.** Prefix
  matching is what broke that, and it was the default: at `/settings/users` both `/settings` and
  `/settings/users` carried `aria-current="page"` and both painted.

  **No new attribute, no new rule, and no baseline moved** — all 244 byte-identical. An earlier
  draft stamped `data-active` on the `<li>` the shell owns and added a rule for it; that was
  wrong three ways, and worth recording because each one was invisible until it was written down.
  The retained `a[aria-current="page"]` rule still painted the *loser*, since the router marked
  every prefix-active link. The new selector weighed (0,1,2) against that rule's (0,2,1), so it
  would have **lost** on the winner too. And a child combinator contradicts the sheet's own
  documented decision beside the nav rule — *"the link element belongs to the caller's router …
  there is no element here to stamp"* — and breaks outright with react-core's own `Link`, which
  wraps its anchor in a span.

  `ModuleNav` adopts the same predicate and the same pinning, which closes the divergence its
  own rule's comment described and deferred to "the navigation model". Its tabs gain `exact` too,
  and the default is now the **prefix**, so a detail route under a tab keeps that tab lit instead
  of blanking the strip.

  One fix travels with it, for a regression the same commit introduces: reading the pathname
  makes `Shell` re-render on every navigation, where before it re-rendered only when the session
  changed. `Outlet` is memoised with no props so a plain re-render stops at that boundary, but a
  **context value** punches straight through a memo bailout — and this one is used *as a
  component*, so an unstable identity remounts every in-app link in the tree on each navigation.
  The published renderer is memoised, and a test asserts reference equality across a navigation
  rather than asserting that a render happened.

  Five mutations, five reds: the router left prefix-matching, the verdict not passed to the link,
  the shell inventing a path when not told one, first-match instead of the set verdict, and the
  memoisation removed.

  **A routed shell specimen is deliberately not added.** It would photograph the sheet's
  `aria-current` rule, which nine existing baselines already photograph, and the thing it alone
  could prove — that the shell picks the right item — is a DOM property four memory-router tests
  now assert directly and far more precisely than a picture can. It would also have cost a new
  `ready` field on the specimen record, because both lanes wait on an element that is visible on
  first paint while the router's first render is asynchronous, so the a11y lane's single
  `analyze()` could have returned a clean run over an empty box.

- **One predicate decides which nav item is current, and it is a property of the SET
  (ADR 0097 §6, amended in 4e).** `isNavItemActive` and `activeNavPath` ship as pure functions
  with no consumer yet — the shell and `ModuleNav` adopt them next — because the shape of the
  answer was worth settling on its own.

  The framework had two notions of "active" and they disagreed: `ModuleNav` compared
  `pathname === item.to` raw while the `Link` it rendered compared through the router, and the
  sheet's own comment beside the rule said so and deferred the fix to "the navigation model".
  What that comment did not know is that the interesting problem is **arity**, not comparison.
  "At most one item is current" is a property of the whole set, and a router computes
  `isActive` per link with no knowledge of siblings — so a nav listing `/settings` and
  `/settings/users` gets **two** links the router considers active at `/settings/users`, two
  `aria-current="page"` attributes and two painted tabs. A screen reader says "current page"
  twice and neither link is wrong on its own terms. This ships today, in every app: the
  packaged `/admin` item sits alongside the example app's `/admin/grants` and
  `/admin/webhooks`.

  Per-item `exact` is not the fix, which is worth stating because it was the first answer:
  turn it on to stop that and `/settings/appearance` — a real route that is not itself a nav
  item — lights nothing at all. **Longest segment-aligned match wins** handles both, and
  `NavItem.exact` is offered for the narrower job it is actually good at: a landing page that
  should own only itself.

  Two details that each removed a special case rather than adding one. Matching on **segments**
  rather than string prefixes means `/` claims nothing but itself, which retires the
  hand-written `exact: item.to === "/"` the router adapter carried — that flag was working
  around a prefix test the adapter did not have. And normalising both operands the way the
  router does (collapse repeated slashes, then drop a trailing one) means the root needs no
  rule of its own: `//foo` was the single shape a segment test would have let through, and an
  earlier draft special-cased the root and justified it with `/profile`, which the segment test
  already rejects. Six mutations, six reds, including one that stayed green first time and
  showed the justification was wrong.

  Search and hash are ignored on purpose: a nav tab's identity is its path, so filtering a list
  must not unhighlight the tab the user is standing on.

- **The brand seam: a box, a mark per appearance, a favicon — and no third slot
  (ADR 0098 §9).** Three things were missing from the brand and only two of them turned out to
  be slots.

  **A box.** The brand link handed whatever it was given straight into a flex row, so an app's
  asset sized itself and an oversized one was clipped by the sidebar's `overflow-x: hidden` with
  nothing to say so — in the 4rem rail, which is where a mark most needs to survive.
  `--shell-brand-size` is published as a fifth shell token and the mark renders inside it.
  Zero-diff: the default `TerpMark` is 28px and the token is `1.75rem`, so the box is exactly the
  size of the thing that used to be the flex item, and all 242 existing baselines are
  byte-identical.

  **A mark per appearance, because a brand is not a `currentColor` glyph.** Every bundled icon
  strokes in `currentColor` and themes for free; a company mark usually cannot, and a dark-ink
  one is invisible on three of the five shipped themes — so an app with a real logo could not
  use them. `logoDark` renders a second mark and the **stylesheet** picks. Not React, and that is
  load-bearing: the theme is `<html data-theme>`, which an app may set with no `ThemeProvider`
  mounted, and a React branch would fail by showing the wrong mark rather than by failing.

  Which themes count as dark is the part that would rot — a list in the framework stylesheet
  goes stale the first time a theme is added, silently and on the new theme only. `themes.json`
  already requires an `appearance` and the token build already emits `color-scheme` from it, so
  it now emits `--appearance-show-light` / `--appearance-show-dark` from the same field. A sixth
  theme cannot forget to answer.

  That pair is a **mechanism, not a design token**, and saying so cost two widened gates — the
  right price, because both were stating something true and now state it more precisely.
  Geometry stays theme-invariant *except* this pair, subtracted by name rather than by prefix;
  the manifest names every base-root token *except* this pair, because a theme editor offering
  `block` / `none` offers a way to break the switch rather than a way to theme anything. The
  list is hand-written rather than imported from the generator that emits it, or every future
  addition would approve itself. A **new** gate covers what a subtraction cannot: every theme
  must declare both halves and show exactly one, since a theme declaring only `show-light` would
  inherit the other and display both marks. Four mutations, four reds.

  **No third slot**, and the refusal is the useful part. A separate collapsed mark was on the
  list until the rail was looked at: the rail already separates the two halves of a brand,
  because `logo` is the mark and `title` is the wordmark, and collapsing hides the title. An app
  whose logo is a wide lockup should split it that way rather than supply a third asset — and
  the only thing missing for that to work was the box.

  **The tab is the other half of the seam.** The template's `index.html` declared no icon, which
  in a single-page app is worse than a 404: the browser's default request for `/favicon.ico` is
  answered with `index.html`, so it gets HTML where it asked for an image and falls back to a
  generic mark with nothing logged anywhere. The template ships `public/favicon.svg` and links
  it, and the file carries both appearances in its own `prefers-color-scheme` block — a favicon
  is a separate document that never sees the page's tokens, so `var(--color-brand-primary)`
  there would resolve to nothing and paint an empty square. Gated in both directions, and the
  `main.tsx` comment now names both places a mark lives instead of one.

- **The shell can put its navigation in the header, and moving it moves its surface with it
  (ADR 0098 §8).** `AppShell` has had exactly one shape — a full-height sidebar collapsing to an
  icon rail — which is right for the app it was built against and wrong for the one the template
  already offers to generate. The `portal` preset is "a personal landing for customers, staff or
  suppliers"; it gets 15rem of permanent chrome for three destinations, and an app cannot opt
  out, because it may write neither `style` nor `className` and the shell took no say in the
  matter. `navPlacement="header"` renders the same brand, the same nav and the same user menu in
  the header, and no sidebar at all.

  **Desktop-only, and the attribute says so.** Below the breakpoint both placements are the
  drawer — a horizontal row of links does not fit 420px, and the drawer exists already, focus
  trap and all. The shell derives the attribute from the viewport rather than stamping it from
  the prop, the way it already derives `data-collapsed`, which is what frees every rule keyed on
  it from a `[data-variant="desktop"]` guard: the attribute is absent whenever it would not be
  true.

  **The header becomes the sidebar surface**, which is one declaration where six overrides would
  have gone. The brand, its title, the resting link, the hover wash and the active link all read
  `--color-sidebar-*` already, so moving the *surface* carries the family with it. It is also the
  only reading that survives theming: an app painting its sidebar navy gets a navy header with
  the same legible ink, where per-property overrides would have handed it navy ink on a white
  header. The check that the mechanism is right rather than merely short is that **the contrast
  gate needs nothing new** — the declared sidebar pairings are still exactly the pairings in
  play. In the shipped themes it moves almost nothing: `--color-sidebar-bg` equals
  `--color-neutral-0` in four of the five.

  **No toggle, and the user menu moves with the nav.** The toggle carries `aria-expanded`, so
  rendering it with no sidebar would announce a state about an element that does not exist; the
  brand takes its slot. The user menu goes to the end of the header group — losing it is the
  failure a placement prop invites, since it is where an app puts sign-out.

  **`defaultCollapsed` is `never` under `"header"`,** because a legal combination that silently
  does nothing is the shape this phase keeps refusing. The same fact has a second half that a
  type cannot cover: the rail choice is *persisted*, so a user who had collapsed the sidebar
  before the app moved its nav would get icon-only links in a header with room for labels, and
  the attribute that normally reveals the rail state lands nowhere. `railCollapsed` forces false,
  with a test that fails on the leak — one of five mutations run against the five new
  assertions, all five red.

  Two baselines added, none changed: every existing shell specimen is byte-identical, because
  the attribute is absent unless an app asks. The third of the three new rules —
  `overflow: visible` on the header-placed nav — no baseline can hold, and it is a fix rather
  than a reset: the sidebar's nav is a vertical scroll container, and a computed `overflow-y`
  other than `visible` forces `overflow-x` to `auto` as well, so in a header, where the box is
  exactly one link tall, that scroller can never scroll and its only effect is clipping a focused
  link's outline and ring on both edges. The computed lane asserts the **pair** — `visible` in
  the header, `auto` in the sidebar — because a rule that set `visible` everywhere would satisfy
  half of it while quietly taking the sidebar's scrolling away.

- **`renderTerpApp` passes `headerActions` through.** The slot has existed on `AppShell` all
  along; reaching it meant abandoning the one-call bootstrap for `TerpProvider` +
  `buildAppRouter`. A slot that exists and is unreachable from the entry point every app uses.

- **Three archetypes, and the fourth is declined (ADR 0098).** `FormPage`,
  `SettingsPage` and `SplitPage` + `SplitPane`, each in both halves of the layout-contract table,
  each with a specimen and both platform baselines.

  **`Page` gains `measure`,** and `FormPage` / `SettingsPage` default it on. `"narrow"` caps the
  whole frame — header included — at 32rem, which is the opposite of the shell's content measure
  one rule above it, and deliberately: a wide page with a narrow column wants its title spanning
  the track, because the band is what tells you the page is wider than its text. A form does not.
  A Save button a screen-width from the field it saves is worse than one sitting over it.

  32rem is not a new number. It is exactly what `admin-form` declares on both packaged create
  screens and what `ProfileView`'s card carries — and 4b already named that card as *a page
  measure wearing a card's clothes*. So this is the mechanism three surfaces were each
  hand-rolling; folding them into it is the follow-up rather than part of shipping it.

  **`SplitPage` is built on `HubPage`, not on `DetailPage`,** and that is the decision worth
  knowing. The obvious shape for two panes is one body slot holding two children — but the
  runtime check takes a single slot owner and reads `article.children`, so two panes would be two
  indistinguishable entries in one slot. Teaching the contract two slots per archetype was the
  invasive option. Instead the panes are the governed thing: the archetype owns the row element
  and admits `SplitPane` in it and nothing else, exactly as `HubPage` owns its grid and admits
  `HubCard`. `verifySlotChildren`, the mirrored table's shape and the message builder are all
  untouched. It therefore provides no `LayoutSlotContext` — for `HubPage`'s reason: the row
  carries a marker no allow table names, so a slot context above it would refuse every split page
  on its own body.

  The slots refuse three things on purpose, and each refusal is the useful half. A **bare `Field`
  at the top of a form body**, because a run of fields cannot be submitted — Enter does nothing
  without a `<form>`, and the house spelling of one is `Stack as="form"`; admitting `Field` would
  sanction the screen that looks finished and cannot be used by keyboard. A **collection in a
  settings body**, because a settings screen whose body is a table is an overview with the wrong
  chrome. And **anything but a `SplitPane`** inside a split.

  **`DashboardPage` is declined,** the phase's sixth refused duplicate. `HubPage`'s own docstring
  already calls a card carrying a `stat` a lightweight dashboard, and its grid is
  `repeat(auto-fit, minmax(min(16rem, 100%), 1fr))` with `grid-auto-rows: 1fr` — a uniform
  equal-height tile grid, which is what a dashboard of tiles is. What a real dashboard needs
  beyond that is *spanning* tiles, and `Grid` refused `span` in 4b. So a `DashboardPage` today
  would be `HubPage` with non-navigable tiles: two names for one grid, which is the
  `LoadingButton` mistake. It earns its place the day spans do.

  The split's keyboard contract is asserted as **two** claims, because the obvious one cannot
  fail for the reason it names. Asserting that Tab visits the list before the detail is a fact
  about DOM order, and CSS cannot change it — so `row-reverse`, `direction: rtl` or a
  `grid-column` putting the detail first would each leave it green while the screen read
  backwards, which is exactly the WCAG 1.3.2 / 2.4.3 failure. The second claim is geometric: the
  list pane must paint left of the detail in two columns and above it when stacked. Verified by
  mutation with an `order: -1` on the detail pane — a CSS-only change the DOM assertion passes
  and the pair does not.

  Two things about that lane were wrong before they were right, both caught by its own guards. A
  round eight tab steps wrapped past the end of the document and began a second pass; bounding it
  to the panes' own focusable count then under-reached, because a breadcrumb link and a page
  action sit ahead of them. It walks one full document cycle and filters. And the first version of
  the split specimens had **nothing focusable in either pane** — plain spans in the list, a bare
  card beside it — so the sequence under test was empty and the assertion vacuous. A master-detail
  list whose rows cannot be activated is also not one.

  117 specimens now, 234 baselines per platform, 585 axe runs.

- **The shell's geometry is four published tokens, and the content measure exists at last
  (ADR 0097 §1, §2).** The two sidebar widths and the header's floor were literals in the
  sheet, and there was **no content max-width and no way to add one** — so a wide table
  stretched edge to edge on a large monitor with no measure control anywhere in the framework.

  `--shell-sidebar-width-expanded`, `--shell-sidebar-width-collapsed`, `--shell-header-height`
  and `--shell-content-max-width`, in one `shell` family so the manifest carries them as one
  category and an app tunes them together from its own unlayered `theme.css` with **no prop at
  all**. Tokens rather than props is the decision and it is not stylistic: four CSS lengths as
  props are four inline styles on the shell root, which is 0094 §3's permanent-inline kind — so
  the ledger would have grown by four for something that is not a measured value but a theming
  knob. As tokens the guard refuses one the contract has not published, and the Studio gains
  four manifest controls for free. Wiring the three existing literals was **provably** inert:
  the token values *are* the literals, and all 224 baselines stayed byte-identical on both
  platforms.

  The measure ships behind `contentWidth` on the shell (also on `buildAppRouter` and
  `renderTerpApp`), default `"full"`, which stamps nothing — the density prop's shape, for the
  density prop's reason: full width is what the sheet already does, so an attribute for it
  would match no rule. With it absent, not one declaration applies.

  **The measure and the subheader band are one declaration, not two features.** A full-width
  band only reads as a band once the column beside it is narrower, and `[data-terp="page"]` is
  *already* a single-column grid — so the band is the page's existing `<header>` keeping the
  track while its siblings take the measure. No new element, no new marker, no portal. Both
  alternatives were rejected on facts rather than taste: a body wrapper (`display: contents`
  included) becomes the sole entry in `article.children` and fails every governed page closed,
  because that slot check is a DOM traversal; and `createPortal` needs a container that exists
  when the child renders, so the shell could only publish one through state — first commit
  local, second commit in the band, a one-frame jump on every navigation.

  One thing stated rather than left to be discovered: "full width" is the full width of the
  article's own track. `appshell-main`'s padding sits outside it, so this is a measure within
  the content column, not a bleed to the window edge — which would need a negative margin and
  therefore an inline site.

  And the specimen needed 1920, which was arithmetic rather than preference and was measured
  rather than predicted. The rule fires only once the article's track exceeds the 80rem
  measure, and the track is far narrower than the window: 1280 gives article 898 / body 898,
  1600 gives 1218 / 1218, and only 1920 gives 1538 / 1280. **Both** the pinned viewport and the
  obvious wider one would have recorded a green baseline over a declaration that never fired. A
  predicted figure had said 1632/352px by subtracting only the sidebar and the main padding;
  the specimen's own box and the scrollbar gutter come off too. Moving the measure one step
  (80rem → 72rem) now repaints 42,296 pixels on exactly those two baselines and fails the
  computed lane.

  `tokens.guard.test.ts` tracks the `--shell-` family from the day it shipped, as an empty
  list: a fifth shell token with no reader lands there and has to justify itself. That is the
  offence `--color-fg-on-brand` was deleted for, and it went unnoticed for a release because
  only three families were tracked at all.

- **The two governed archetypes and the packaged admin screens get their first pictures, and
  one of them found a defect on its first run (ADR 0079, ADR 0097).** `OverviewPage` and
  `DetailPage` had **zero** pixel coverage, and the three admin markers — `admin-form`,
  `admin-section-title`, `admin-payload` — had no baseline on either platform and were never
  rendered by the axe lane. That is how five base styles survived the whole 0094 migration
  inside views both ratchets read as clean; the sheet's own comment on that block says so.
  Six specimens close it across this section: 113 specimens, 226 baselines per platform and 565
  axe runs.

  `Page` itself was never the gap — `page-header`, `page-loading` and `page-error` picture it
  directly. What had no picture is either archetype that *wraps* it, and with it the body shape
  the contract actually admits: `overview-page` renders a lead `Text`, a `Divider` and a
  `DataView`, which is the widening 4b shipped and which no specimen had ever rendered inside a
  governed body. Three body children also put two of the page grid's gaps in frame, where
  `page-header`'s single child only ever exercised the header-to-body one.

  Two of the three admin specimens are a different *kind* of specimen from the third.
  `admin-user-create` mounts the **real** packaged screen, in a memory router carrying the real
  `/admin/...` paths — it renders nothing that waits on a response, because the form only POSTs
  on submit. `GroupDetail` and `AuditLogAdmin` load on mount, and those two reproduce the
  surface the sheet styles instead.

  The reason recorded for that at first was wrong and is worth correcting rather than quietly
  restating: it claimed a mock server would breach the registry's no-live-data rule. The
  workbench **already has one** — `workbench-mock-auth` in its vite config answers the auth
  boot with a fixed user, and its own comment calls that the determinism rule applied to the
  session. So extending it with audit and group fixtures is the better long-term answer, not a
  forbidden one. What is actually in the way is the **axe lane**: it reads the tree once, with
  no stability retry and no wait for data, so a run that scoped the loading frame would pass on
  an empty `DataView` and report nothing — worse than no coverage, because it looks like
  coverage. Closing it means teaching that lane to wait for a row, which is a harness change.

  And the one claim a reproduced surface cannot make — that the *real* component keeps the
  payload's scroll container reachable — is asserted in `admin.test.tsx` instead, against the
  packaged screen with a real row expanded. The audit fixture serves one row now for exactly
  that; the note explaining why it served none is replaced by the test.

  And `admin-payload` had to be built twice, which is the reusable part. The first version
  rendered the payload inside a real expanded `DataViewTable` row and **gated nothing**:
  measured, the `<pre>` came out 1594px with `scrollWidth === clientWidth`, so it never
  scrolled — it grew, and pushed the table from 1232 to 1626. A `<td>` under `table-layout:
  auto` is shrink-to-fit, so nothing constrains the box, and `overflow-x: auto` on a box that is
  never narrower than its content is inert. The picture looked like coverage either way.
  Constrained to 34rem, the same content gives 544 against a 1594 scroll width, and deleting the
  never narrower than its content is inert. The picture looked like coverage either way.
  Constrained to 34rem, the same content gives 544 against a 1594 scroll width, and deleting the
  declaration now repaints both baselines by ~91,500 pixels *and* fails the computed lane.

  "Inert in production" would be too strong, and an earlier draft of this entry said it.
  `DataView` renders **cards** below the 768px breakpoint, and the expanded panel then lands in
  a plain block div where the payload fills its container and scrolls exactly as the specimen
  does. So the declaration is live on a phone and does nothing in a desktop table cell — which
  is also what makes the `tabIndex` below a live fix rather than a precaution. The desktop half
  waits on the DataView's expanded-cell width model, with the column-sizing work.

- **An exported page archetype with no slot-table entry was a green build (ADR 0079).**
  `verifySlotChildren` returns null for a slot the table does not name, and the lint rule
  early-returns the same way — so an archetype exported *without* an entry is silently
  ungoverned by **both** halves of the control: no error, no warning, and a governed app renders
  it with the body slot wide open. Nothing asserted the two lists agreed, which made "forgot the
  table entry" indistinguishable from "deliberately unconstrained".

  Three assertions, derived from the entry point's own exports rather than restating a list —
  a list is the thing that was missing. A new archetype joins the check by existing, and has to
  take a slot or name its reason; a slot naming an archetype nobody exports fails the other
  direction. The plain `Page` is the one excused entry, for the contract's own reason: it is the
  bespoke pressure valve. The vacuity guard earned itself immediately, catching that
  `/^[A-Z]\w*Page$/` cannot match `"Page"` — after the leading capital there is no `Page` left
  to match, so the derived list was silently one short.

- **`Select` takes typed options, so a closed enum stops needing a local wrapper.** It accepted
  raw `<option>` children and nothing else, so every enum meant one hand-written element per
  member *plus* `setStatus(event.target.value as Status)` on the way out — and the cast is
  exactly where a wrong value gets in. It now also takes `options: SelectOption<T>[]` with a
  typed `onValueChange`, inferring `T` from the list, plus a `placeholder` that renders the
  disabled empty-valued leading row every app was writing by hand.

  `SelectOption<T>` carries the type parameter `ComboboxOption` does not; widening `Combobox` to
  match is additive and can follow the day something asks. The two forms are a **union**, not
  two optional props: rendering `options` while silently ignoring `children` would be a prop
  that works in one branch and does nothing in the other, which is the defect shape found twice
  in one release — so the combination does not typecheck at all. Verified by mutation in the
  example app, where a `"dong"` typo now reports *Type '"dong"' is not assignable to type
  'TaskStatus'. Did you mean '"doing"'?* instead of shipping an option nobody can select.

  Both readers were converted in the same commit and the packaged form's baseline is
  byte-identical, but only one of them exhibits the typed half: `UserCreate`'s rank ladder is
  `String(rank)`, so `T` degrades to `string` there and no cast was removed, because that file
  never had one. The cast the feature exists to remove is the app-side
  `setStatus(event.target.value as Status)`, and the example app is where it goes.

  Three things about the type were each found by breaking the alternative, and none of them is
  cosmetic. `onValueChange` sits **outside** the union: inside it the prop has two signatures,
  TypeScript cannot contextually type a parameter across a union of signatures, and
  `onValueChange={(value) => …}` came back as an implicit `any` — invisible to anyone passing a
  function by reference, which is how it survived the first attempt. Its parameter is
  `NoInfer`, because otherwise the *callback* becomes the inference site on the raw-children
  branch: `<Select onValueChange={setStatus}><option value="dong"/></Select>` took `T` from the
  callback and never compared the children to it, allowing precisely the typo the prop is for.
  And `value` is `NoInfer` too, or a wrong value widens the parameter it is checked against.

  Two shapes the first version broke and this one keeps, both unused in the repo and therefore
  caught by probing the type rather than by the suite: a `multiple` select with a
  `readonly string[]` value, and a numeric `value`. Narrowing them bought nothing, since `T`
  can only come from an options list. A `<Select>` with neither options nor children compiles
  too — `children` is optional, not required.

- **A fourth workbench lane, for values the other three cannot see:
  `visual/computed.spec.ts` (ADR 0097).** The screenshot lane runs with
  `animations: "disabled"` — deliberately, so the spinner keyframes do not make every run
  differ — and the cost of that was never written down: **every duration and easing in the
  sheet is invisible to it.** A transition at 150ms, at 400ms, or gone entirely produces
  byte-identical baselines, and axe reads a static tree, so neither lane says anything about
  a computed value.

  That gap has a sharp edge, which is what made the lane necessary rather than nice. A
  `var()` inside a shorthand that fails to substitute makes the whole declaration invalid at
  computed-value time and falls back to the property's initial value — `transition: all 0s
  ease 0s`. Every element still paints identically at rest, every baseline still passes, axe
  still finds nothing, and every transition in the package is silently dead. A structural
  test proves the sheet *names* a token; only reading the resolved value separates the two.

  Three tests, and it also gates two claims the sheet had only made in a comment: that
  reduced motion reaches a marked element, a nav link **and** a breadcrumb link — the last
  two bare `<a>`s the block reaches only through selectors of their own, one of which it had
  silently failed to reach before — and that the scrollbar gutter is really reserved. Scoped
  like the keyboard lane: cases where the resolved value IS the contract, and nothing else.
  It runs as its own CI step, never in one pool with the others.

- **A specimen can declare a viewport of its own, which retires two text-only gates on the
  shell (ADR 0097).** The workbench pins 1280x900 so a baseline cannot depend on a window
  size. The cost, which `styles.test.ts` had been stating in as many words: anything that only
  applies at a width the pin is not was out of reach of both lanes, so the shell's mobile
  geometry and the sidebar's `flex-shrink` were asserted as text because "no baseline can hold
  it" was true.

  Two specimens hold them now, and both were confirmed to paint their subject rather than
  assumed to. `app-shell-mobile` (420x900) is the first picture of the mobile variant anywhere;
  moving `appshell-main`'s tightened padding one step to the desktop value repaints 1,309 pixels
  there and nothing else. `app-shell-narrow` (820x900) is the band just above the breakpoint
  where `flex-shrink: 0` is the only thing holding the rail at 15rem; removing it repaints
  124,797 pixels there and leaves the other three shell specimens untouched.

  The second carries the lesson: a narrower window was **not enough**. A flex row under no
  pressure never asks an item whether it may shrink, so the specimen renders a wide `DataView`
  rather than a paragraph — with the paragraph it would have been a green baseline over an
  unexercised declaration. Adding both left all 164 existing baselines byte-identical on both
  platforms, so the per-specimen promise survives a per-specimen viewport.

  Still text-only, and a viewport cannot fix it: the drawer's own geometry and its backdrop
  render only while `drawerOpen` is true, which is internal state with no way in — the wall
  `defaultCollapsed` was added to get past for the icon rail, where four rules had shipped
  unpainted behind it.

- **`Button` gains `size`, `loading` and `fullWidth`, and the framework's own sign-in screen
  stops working around their absence (ADR 0097).** It had `variant` and `icon` and nothing
  else, and the gaps were paid for in ways that show what a missing prop costs. Full width was
  reachable only as `style={{ width: "100%" }}`, which app modules may not write (ADR 0059) —
  a shape the framework could produce and its consumers could not ask for, and one `LoginView`
  had to reach through a rule on its button *group* instead. A busy submit was hand-rolled out
  of `disabled` plus a swapped label, with no spinner and no `aria-busy`.

  All three are attributes with a rule each, so all three are themeable and none adds an
  inline style — the ledger stays at nine sites. Two decisions inside that are worth knowing.
  `data-size` is stamped only for `sm` and `lg`, because the standard control's geometry IS
  the base rule, exactly as "comfortable" is the token sheet's `:root` value and the attribute
  for it matches no rule. And the two sizes are a `calc()` off `--density-control-min-height`
  rather than heights of their own, which is what makes size and density compose without
  either knowing about the other: measured, a small button in a compact subtree comes out 4px
  shorter, the token's own step.

  `loading` sets `disabled` too, so a second click cannot start the same request twice, and it
  wins over an explicit `disabled={false}`. Its cursor is the one non-obvious part: a loading
  button is also `:disabled`, and that rule lives in `terp.state`, so a `data-loading` rule in
  `terp.base` loses on layer order and the cursor silently stays `not-allowed` — telling a user
  "you may not" where the truth is "not yet". Verified in a browser, because no lane had ever
  held a cursor at all: Playwright paints no pointer into a screenshot.

  `LoginView` now passes the props on all four of its buttons and the group rule retires.
  Zero-diff, and checked rather than assumed: all 168 existing baselines byte-identical on
  both platforms.

- **The layout vocabulary: `Grid`, responsive `Stack` props, `padding`, `Divider`, a plain
  `Card`, the prose primitives, and `DetailList` as a real grid (ADR 0097).** The last of the
  diagnosis's three structural blockers, and the only one that was a *capability* ceiling rather
  than a quality one. App modules may not write `style` or `className`, so anything not
  expressible as nested `Stack`s was not awkward to build — it was **unbuildable**. A
  fifteen-field form shipped as one long vertical run because two columns could not be
  expressed, in an app whose escape-hatch budgets were both `{}` across three thousand lines.
  The guard rails held perfectly; the ceiling was the framework's.

  **`Grid`** takes a fixed 1–4 columns or `"auto"` (the default), and `auto` is the responsive
  answer with no breakpoint at all: a track floor reflows the grid to whatever its *container*
  can hold, which is what a caller usually means and more nearly right than a viewport query.
  `minColumn` is a four-step scale rather than a length, for the reason `gap` is a token index —
  so there are no arbitrary widths. No `span`, and therefore no twelve-column option: a span
  system needs a child component to carry it, and `columns={12}` without one is twelve narrow
  cells rather than a layout system.

  **`Stack`** gains `padding` — the dimension whose absence meant a padded region was reachable
  only through a `Card`, which brought a border and background whether or not they were wanted —
  and `{ narrow, wide }` pairs for `direction` and `gap`. **One cutover, not a scale:** the pair
  changes over exactly where the shell becomes a drawer and the DataView becomes cards, so a
  toolbar reflows when the chrome around it does.

  **The prose primitives** — `Heading`, `Text`, `Code`, `Link` — close a narrower and worse gap
  than "no typography". A module could always render a `<p>`; what it could not do was give it
  any treatment, because a bare element carries no marker for a rule to reach. Bare prose in a
  module is text the app can never theme, and the framework's own generated home page shipped
  exactly that. `Heading` separates `level` from `size`, so a visually small `h2` needs no wrong
  element, and offers no level 1 at all: `Page` renders the single `h1` of every routed view.

  **`Divider`** is an `<hr>`, so the separation reaches the accessibility tree rather than only
  the pixels — and it is `Separator` under its other name, shipped once. **`Card
  variant="plain"`** keeps the heading and drops the box, for a titled region inside something
  that is already a surface; boxed, a section whose body is a `DataView` gets a border inside a
  border and the table loses its full width.

  **`DetailList`** becomes a real grid: `layout="aligned"` puts every label in a shared column,
  `"stacked"` puts it above its value, and `columns` takes two pairs per row. `inline` stays the
  default, because every governed detail screen already renders one.

  **Two components were deliberately not shipped, and that is the more useful half.** `Section`
  and `Surface` were both on the list and both turn out to be `Card` with declarations removed —
  `Card` already renders a `<section>` with an `<h3>`, a description, an actions slot and
  children stacked on the token scale. A `Section` would have meant six more markers describing
  the same DOM; a `Surface` is a `Card` with no title, which `Card` already is. What the list
  was pointing at was the chrome, not a component, so it is a variant: three declarations, no
  new markers, and usable in governed bodies immediately because the contract already admits
  `Card`.

  Every new prop is a closed set and becomes a `data-*` attribute with a rule each, so the
  inline-style ledger stays at **nine sites** and every one of these is themeable from an app's
  `theme.css`. Nothing an existing app renders changes: every default stamps no attribute, and
  all 190 baselines were byte-identical on both platforms through the whole phase.

- **The layout contract widens, on both halves, and the asymmetry is the decision (ADR 0079,
  ADR 0097).** Shipping `Grid` without this would have shipped a component no governed page
  could use — and only a copier-generated project has the contract switched on, so the example
  app could not have detected it. `Grid` is admitted to **detail** bodies and not overview ones:
  an overview body is a data collection, and a grid of summary cards is a hub, which has its own
  archetype. `Divider` and `Text` join both. `Heading` joins neither, deliberately — a heading
  in a governed body must **own** its section, and `Card` is how a section is owned; a bare
  heading with siblings after it is a grouping the check cannot see. Both halves of the table
  stay byte-equal, and the asymmetry is pinned by tests rather than left to the data.

### Changed

- **Every transition in the framework stylesheet is timed off the published motion scale,
  so moving a motion token now moves something (ADR 0097).** The seven motion tokens
  shipped in 0.7.0 and nothing read them: the sheet wrote `150ms ease` 28 times and
  `100ms ease` once across sixteen declarations while reading a motion token zero times. An
  app could set `--motion-duration-fast` from its `theme.css` and watch nothing happen, and
  a Studio editor built from the token manifest would have offered four duration controls
  that moved nothing.

  Inert by construction, and the values were checked rather than assumed:
  `--motion-duration-fast` **is** `150ms`, `--motion-duration-instant` **is** `100ms` and
  `--motion-easing-standard` **is** `ease`, so all 29 literals mapped onto a token pair and
  no computed value changed — 164 baselines and 406 axe runs unmoved.

  Four tokens stay unread and are now named as an exact list rather than resolved either
  way, because both resolutions are worse than the record:
  `--motion-duration-base`, `--motion-duration-slow`, `--motion-easing-entrance` and
  `--motion-easing-exit` map onto no literal in the sheet. Deleting them is a contract
  change, since the manifest publishes them; giving them readers means shipping overlay
  entrance and exit animations, which is a behaviour change wearing a token wiring's
  clothes. The spinner's `0.8s` stays a literal: a rotation period is not an interaction
  step, and the scale tops out at 400ms.

- **The scrollbar gutter is reserved, so a page no longer shifts sideways when content
  crosses the fold (ADR 0097).** `scrollbar-gutter: stable` joins the reset layer's
  existing `html` rules, next to the themed scrollbars. Navigating from a screen that fits
  to one that scrolls used to change the width of the content box by the scrollbar's width,
  moving the header, the table and the centred sign-in card with it.

  **This one moves pixels, and it moves them everywhere:** it narrows every scroll-free page
  by the gutter. Measured in the workbench at exactly 10px on 162 of 164 baselines, with
  **zero** height changes across 31 distinct size pairs — a uniform shave, nothing reflowed —
  and the re-record was verified as that transformation rather than accepted as a diff. The
  only baselines that changed without resizing are the eleven overlay specimens, which are
  viewport shots at a fixed 1280x900, so a narrower page moves their content instead. It is
  layered, so an app that would rather have the jump turns it off from its own unlayered
  `theme.css`.

  One honest limit came out of measuring it: **the harness's Chromium reserves no layout
  space for the viewport scrollbar at all.** With the declaration removed, a solo specimen
  page and the many-screens-tall catalog both report a root box of 1280 in a 1280 viewport.
  So there is no jump in that browser to prevent, an assertion that the two page shapes
  agree would pass identically before and after, and the lane can witness the reservation
  but not the benefit. The benefit is real on the browsers that take scrollbar space, which
  is most desktop Chrome and Firefox on Windows and Linux — the users, just not the lane.

- **The published type scale gets its first readers, and the reconciliation it does *not* do is
  now a number.** `--font-line-height-*` and `--font-letter-spacing-*` shipped in 0.7.0 read by
  nothing — the motion-token shape again, resolved differently because the facts differ. Every
  motion literal mapped exactly onto a token, so wiring those was inert. Here the sheet writes
  line heights of 1.2, 1.25, 1.3, 1.4 and 1.5 while the scale offers 1.2, 1.35, 1.5 and 1.7:
  **only 8 of 32 literals map.** Converting those eight and leaving thirteen is a
  half-migration; converting the rest changes rendered line heights across a dozen components,
  which is a typography pass with its own baselines rather than something done in passing.

  New components have nothing depending on their metrics, so the prose primitives take the scale
  as published and six of the seven tokens now have consumers. What remains is tracked rather
  than hoped for: the unread-token gate generalises from motion to any tracked family, and gains
  a ledger of the bare `line-height` / `letter-spacing` literals as an exact multiset — so a new
  rule adding a 27th bare line height has to use a token or come and say why.

- **The one viewport cutover is spelled in one place.** It was written twice, verbatim, as
  `const MOBILE_BREAKPOINT = "(max-width: 768px)"` in both `AppShell` and `DataView` — the
  duplication the diagnosis named — and the responsive `Stack` rules would have made a third
  copy, in the stylesheet, where the first two could not see it. It now lives in one module,
  which both components and the sheet take it from, held against the published
  `--breakpoint-md` by a gate that also refuses a fourth copy.

  The literal cannot become a `var()` and that is worth stating: CSS forbids a custom property
  in a media-query condition and `matchMedia` takes a string, so reading the token would mean a
  layout read on every mount, broken under SSR. And the sheet's query is
  `not all and (max-width: 768px)` — the *complement* of the components' string rather than a
  second literal — so the two halves partition the viewport by construction instead of by a
  chosen epsilon, and the shell's existing behaviour at exactly 768px is untouched.

### Fixed

- **Two workbench specimens were nondeterministic, and had recorded the wrong state.** The split
  specimens put a `ResourceList` in the list pane with `renderActions`, which `ResourceList`
  wraps in `<Authorized action="write">` — so the rows rendered only once the auth boot's two
  round-trips resolved. The baselines committed with them caught the state *without* the
  actions: 385px tall against 430 once the session landed.

  `toHaveScreenshot` cannot see this. It keeps shooting until two consecutive frames match, so
  it stabilises on whichever state it finds and reports both as settled — which is why the
  recording and the comparison disagreed while each was individually stable.

  The rule that follows is narrower than the registry's "no live data", and worth having
  explicitly: a specimen **may** sit behind the auth seam, because the dev server's own
  `workbench-mock-auth` plugin answers it with a fixed user — but nothing it *renders* may
  depend on that session having resolved. `SignedIn` alone is fine; `Authorized` content inside
  it is not. Both panes now use plain buttons and need no session at all.

- **`ResourceList`'s optional title renders a second `h1`, and an unstyled one.** Found while
  composing the split's list pane. The prop's own doc says to omit it under a `Page` "whose title
  is the `h1`" — and passing it there does exactly what that warns about: a second `h1` in the
  document outline, at the UA default size, visibly *larger* than the page's own title at
  `font-size-lg`. It is the same shape `admin-section-title` exists to fix for `h2`.

  Not fixed here, and the reason is worth stating rather than leaving as silence: that `h1`
  carries no `data-terp` marker and no rule, so neither the marker inventory nor the base-rule
  roster can see it, and giving it either moves the existing `resource-list` baselines. That is
  its own change with its own picture. The split specimens use the documented shape — no title,
  since `SplitPane`'s `label` is already the pane's accessible name.

- **The audit payload was a scroll container no keyboard could reach.** `admin-payload` declares
  `overflow-x: auto`, so a wide payload scrolls — and the `<pre>` carried no `tabIndex`, which is
  the WCAG 2.1.1 failure axe reports as `scrollable-region-focusable`. `Code` block already
  carries one for exactly this reason, with a comment at the site saying so; the audit screen's
  `<pre>` predates it and nothing connected the two.

  Found by the axe lane on the first run in which a specimen rendered the marker at all, which
  is the point of the coverage above rather than a coincidence: those three admin markers had
  never been rendered by that lane, in any theme.

  **Live rather than latent, on a phone.** A first draft of this entry called it latent, on the
  strength of the measurement showing the payload never scrolls inside a desktop table cell.
  That measurement is about one of the two layouts: below 768px `DataView` renders cards, the
  expanded panel lands in a plain block div, and the payload becomes a real scroll container
  with a ~200-character line in a ≤768px box. So a keyboard user on a narrow viewport could not
  reach it, which is the case the fix answers. On desktop it currently adds a tab stop to a box
  that does not yet scroll — the honest cost, and it resolves when the expanded-cell width model
  lands.

  Gated on the real component, which the workbench cannot do: a specimen writes its own `<pre>`
  with its own literal `tabIndex`, so every lane there stays green with the attribute deleted
  from `AuditLogAdmin`. `admin.test.tsx` renders the packaged screen and expands a row.

- **A `Link`'s caller attributes reached a wrapper instead of the anchor, and two layout
  primitives had no list reset.** Both are the same shape — something that worked in one branch
  and silently did nothing in the other.

  `Link` placed the caller's attributes on its wrapper for an in-app path and on the anchor for
  an external one, so the same `aria-label` either named the link or vanished, decided by
  whether the destination started with a slash. On a `<span>` around a link an `aria-label` is
  ignored: the link keeps its content as its accessible name and the caller's intent disappears
  with no error. The cause was a real constraint — `NavLinkRenderer` took `{ to, children }` and
  nothing else — so the seam gains one optional key for attributes bound for the anchor. An
  implementation that destructures only the first two stays source-compatible. The *marker*
  deliberately does not travel that way: a renderer that ignores the key would leave an unstyled
  link with no error, and a component's styling hook cannot depend on a caller honouring a seam.

  `Stack` and `Grid` both document `as="ul"` and neither reset the UA list styling, so the
  documented use rendered bulleted and indented. `hubpage-grid` and `resource-list-items` already
  carry that reset because both are *always* lists; these two are lists only when asked, and no
  specimen rendered either as one — so nothing could notice. Fixing it moved none of the 214
  existing baselines.

  And a `Link` to a bare relative path is refused rather than silently reloading the page:
  `to="records"` fell through to the external branch and rendered a relative anchor, skipping the
  router's guard. Every route a manifest declares is absolute.

- **A long unbreakable value no longer pushes a `DetailList` past its container.** The diagnosis
  named the missing alignment and cited "nine pairs including two 64-character digests"; the
  digests were the actual defect and it took two goes. An implicit grid column is `auto`, which
  floors at *min-content*, so the track needed `minmax(0, 1fr)` — the same declaration `Grid`'s
  fixed counts need for the same reason. That was not enough, and the specimen said so rather
  than a review: a 64-character digest has nothing to break at, so it overflowed the column
  whatever the column's floor. `overflow-wrap: anywhere` on the value is the fix — the same
  answer `profile-email` already uses for a long address, where the sheet notes it as
  unobservable because that screen's session is a fixed short one.

## 0.9.0 — 2026-08-21

### Added

- **The query string joins the checked route table: `search` on a manifest route,
  `useRouteSearch`, and `search` on `useTerpNavigate` (ADR 0096).** Friction
  reported from building a control-plane-plus-worker app on Terp, and the sharpest
  item in that report.

  `useTerpNavigate` took `to` and `params`. A list screen's filters, its sort and
  its page cursor all live in the **query string** — so every screen with a filter
  had to reach for the router's own `useNavigate` / `useSearch`, and lost path and
  param checking on the way out. The reporting app had five of six screens outside
  the seam. The guarantee ADR 0092 bought was therefore missing on the majority of
  screens, which is close to the worst possible distribution: it held exactly where
  a typo was least likely.

  A route declares its keys and `terp routes` emits a second table:

  ```ts
  { path: "/records", view: "List", search: ["status", "page"] }
  ```
  ```tsx
  const { status, page } = useRouteSearch("/records");
  void navigate({ to: "/records", search: { status: "open" } });
  ```

  Three limits, each deliberate. **Keys, not types** — every value is
  `string | undefined`, because a query parameter is text and is absent until set;
  parsing `page` is the screen's business, and a validation language in a manifest
  would sit away from the screen that reads the value. **Replace, not merge** —
  clearing a filter means sending the key as `undefined`, and a merge would keep the
  old value, so "clear" would silently not clear. **Only declared keys are
  returned** — a stray key someone hand-typed into the URL cannot reach a screen's
  logic. A route that declares nothing refuses `search` outright; before
  `terp routes` has generated, the shape stays loose, so an app that has not adopted
  is unaffected.

- **`GET /me` reports the caller's named permissions, so a UI can hide exactly what
  the server would refuse.** `useCan` compares role *rank*, because rank was all the
  wire carried. A screen whose write needs a named grant (`definitions.publish`) had
  nothing to ask: it hid by rank as a proxy and handled the 403 anyway — showing a
  button it knew might fail, or hiding one the user was entitled to. Both are wrong,
  and neither is detectable from the client.

  `CurrentUser.permissions` is filled through a registry seam
  (`register_permission_projector`), not an import: the access capability registers
  its grant lookup at import exactly as a scope predicate does, so auth and identity
  never import the capability that owns grants, and an app that mounts none projects
  an empty tuple. On the frontend, `usePermissions()` / `useHasPermission(name)` read
  it and `Authorized` takes an optional `permission` **alongside** `action` — both
  must pass, which is what the server does (a `Policy` carrying a `Permission`
  enforces the rank floor *and* the grant), so a UI checking one of the two would
  disagree with the endpoint in one direction or the other.

  It is a **display** input and says so in three places. The guard re-checks every
  request; a client that treats the list as authority has moved the gate to the wrong
  side of the wire.

- **`useEndpointDownload` — downloading an artifact the backend generates.**
  `useFileDownload` covers a stored file id. An evidence bundle or a CSV export has
  none, and the only routes to it were a raw `fetch` (refused: one typed egress path)
  or a raw `<a href>`, which carries no bearer token and so 401s or silently saves an
  error page under the intended filename. The reported outcome was the feature being
  dropped rather than built.

  It goes through the session client, so the base URL, the bearer token and the
  credentials are the client's, and a non-2xx **rejects** instead of saving the error
  body. `saveBlob` is the blob-to-anchor dance extracted once, with the object-URL
  revoke in a `finally` — the leak every hand-rolled copy forgets — and
  `useFileDownload` now uses it too. An unfilled `{placeholder}` fails closed rather
  than requesting a literal `{id}`.

- **`terp guide package-boundaries` — the recipe for an app with a second top-level
  package.** A worker that cannot run under the gate (a legacy-DB connector, a
  device, a non-Python runtime) lives beside `app/`, and the two must not import each
  other. The report wanted `terp check` to own that contract; the answer is
  import-linter, which is what the platform already uses for its own layer-0
  keystone, and which fails with the offending import chain rather than a file:line.
  The topic writes out the three contracts, the two-command gate (`terp check` over
  `app/`, `lint-imports` over both), and the point that neither package may import
  the other but **both may import a third** — which is how a shared contract package
  replaces twin modules pinned against drift by a test.

- **Expiring, fenced custody of work: `terp.core.leases` + `terp-cap-leases`, and a
  reaper that puts the row back (ADR 0095).** Friction reported from building
  queue-shaped work on Terp, twice, from two directions that turned out to be one
  missing primitive.

  First: a row a crashed worker took stays taken. A worker flips a request to
  `claimed` and is then killed — OOM, a rescheduled pod, a dropped connection.
  Nothing in the schema records *who* took it or *until when*, so nothing can tell
  "still working" from "died three hours ago", and the only recovery is a
  hand-written `UPDATE` by somebody with database access. Second: nothing enforces
  "at most one active run per pipeline". Exclusivity *while a holder is alive* is
  expressible today (a partial unique index, an optimistic-concurrency claim); what
  is not is exclusivity **with an expiry** — and without the expiry, the mutex has
  the first problem.

  The evidence that decided it came from neither report. `terp-cap-sync`'s own
  service docstring had been carrying this since it shipped: *"a job that dies
  mid-loop leaves a `running` run whose work already committed per-record; the next
  successful run supersedes its cursor — reaping stale runs is a follow-up."* Two
  independent occurrences, one of them in the framework's own flagship consumer
  capability, is the bar for promoting a pattern to a primitive.

  A lease is a resource (an opaque `(kind, key)` — `LeaseResource.for_row(row)`, or
  `LeaseResource("pipeline", pk)` for a mutex on something that is not a row at
  all), a holder, an expiry, and an **epoch fence**. The fence is the part that is
  easy to leave out and expensive to omit: expiry alone establishes that a holder
  *may* have died, and does nothing about one that merely **paused** and wakes after
  its own deadline to finish work a successor already took over. Every fenced
  statement carries `AND epoch = :epoch`, and only a grant increments it, so a
  superseded holder's renew, release and forfeit all match zero rows.

  Take it inside the write that claims the row and the two can never disagree:

  ```python
  class RequestService(BaseService[RunRequest, ...]):
      def _after_write(self, session, entity, action):
          if entity.status == CLAIMED:
              hold_lease(session, LeaseResource.for_row(entity),
                         holder=self.worker_id, ttl_seconds=60)
  ```

  A resource somebody else holds raises `LeaseHeldError` *inside* the write unit, so
  the row never reaches `claimed` at all — no compensating update to forget. Inside a
  work loop, `guard.heartbeat()` is cheap (it writes only past the lease's half-life)
  and **raises** `LeaseLostError` rather than returning a boolean a caller can forget
  to check, because losing a lease means a successor may already be doing this work.

  **This seam has no default store, on purpose.** Every other store seam here
  (idempotency, throttle, cache) ships a safe in-process default, because degrading
  one costs a re-execution or a cache miss. Degrading a lease costs *two workers
  running the same work at once* — the exact thing it exists to prevent — and the
  in-memory version cannot deliver the headline feature at all, since its state dies
  with the very process whose crash the lease exists to survive. So the default is
  `None`, the first lease call fails closed naming the missing wiring, and an app
  that wants leases names its store: `create_app(lease_store=DatabaseLeaseStore(),
  require_durable_leases=settings.is_production)`. That boot guard refuses the
  in-memory store *and* `None`.

  **The reaper is the half only your domain can write.** An expired lease frees a
  resource; it does not free the work, and no generic mechanism knows whether the
  right answer is "queue it again", "close it failed" or "leave it for a human". So
  `register_lease_reaper(kind, recovery)` declares it once, and each cycle runs the
  recovery **and** forfeits the lease in one transaction — the domain's own audited
  `_save` nests into the reaper's write unit, so a recovery is as traceable as any
  other mutation. A kind with no reaper is simply *released*, which is the correct
  shape for a pure mutex. The cycle ships as a declared `leases.reap` job with a
  `lease_reap_schedule` helper, so it runs on whatever an app already operates —
  APScheduler, Celery beat, a `CronJob` — with no new daemon to deploy. A reaper that
  only exists as a command is a reaper somebody has to remember to schedule.

  `terp leases list --expired` names the holder and the deadline — the distinction a
  bare `claimed` column cannot make — and calls out, per kind on the page, any kind
  with **no** registered recovery, because "nothing reaped it" and "nobody declared a
  recovery for it" look identical on the rows alone and the second is the mistake an
  author actually makes. `terp leases reap` runs the same bounded, fenced cycle the
  job runs. There is deliberately no force-release, in the CLI or the admin router:
  taking a live lease from a holder that may still be running is the split brain the
  fence exists to prevent. Recipe: `terp guide leases`.

- **Two declared token pairings for danger text, and a third gate that counts inline
  style sites rather than style objects.** `--color-status-danger` has been painted as
  text in three places — a `Field`'s error line, a failed create, a failed sign-in — and
  neither pairing was declared, so the contrast gate measured it nowhere and axe only
  where a specimen happened to paint it. `danger-on-card` and `danger-on-canvas` measure
  5.29:1 at worst across the five themes and clear AAA in `contrast`, so they declare a
  fact rather than open a ratchet. They matter most for the surfaces no lane can reach:
  the sign-in error is set only inside a `catch`, so no specimen can render it, and a
  declared pairing is the only gate such a surface will ever have.

  The third gate exists because the other two were narrower than they looked, and four
  of the packaged admin views proved it — they carried five base styles through the whole
  migration while both ratchets read clean. The unmarked-surface worklist names files
  with **no** marker at all, and every admin view rendered none, so each read as a view
  composition and was excluded by the list's own rule; the style-object ledger counts
  declarations annotated `CSSProperties`, and four of these were call-site literals with
  the fifth an unannotated object. `INLINE_STYLE_SITES` counts sites per file, so the
  only way out of it is to render no inline style — and the nine that remain are named
  one by one, each either a measured value the sheet has no business owning or a caller's
  own `style` forwarded to a root. Verified by putting one back: the new check names the
  file while the old ledger stays silent.

  Two claims in those gates were corrected in passing, both false before this release
  touched them: `styles.test.ts` said three inline box-shadows remained and named
  `AppShell`'s drawer and `DataViewCardList`'s card, which had both migrated releases
  earlier — there is now none anywhere, which is what the shared focus ring's retired
  escalation actually rests on. And `ui/Button.test.tsx` cited the login screen's
  full-width submit as an example of a legitimate inline escape; a fixed 100% is layout
  policy rather than a measured value, and it is a rule on the form now.

- **Three workbench specimens and per-lane scripts.** `resource-list-error` paints the
  failed-create message, whose ink had no baseline in any theme; `page-loading` and
  `page-error` paint the frame's two async states, which `LoadingState` and `ErrorState`
  had only ever been photographed outside of — and `page-error` sets both props at once,
  because `error` winning over `isLoading` is a documented behaviour with no other gate.
  81 specimens, 573 checks.

  Both of the page specimens render inside a fixed-height **grid** wrapper, and that is
  load-bearing rather than tidy: `Page`'s grid declares `align-content: start`, which is
  unobservable while the article is content-height, so the declaration would otherwise
  have moved into the sheet with no baseline able to see it. Confirmed by mutation — it
  fails those four baselines and nothing else.

  The scripts are `visual:screens`, `visual:a11y` and `visual:keyboard`, and they close a
  contradiction the workbench README carried: it warned that a red `color-contrast`
  result is only evidence when the lane had the machine to itself, and then offered
  `npm run visual`, which starts all three lanes in one worker pool. That is the
  contention condition, met a third time here — three twilight specimens failed together
  on a full run, the axe lane alone passed all 81, and the identical full command passed
  573 on the next attempt. CI never met it, because the workflow runs the three lanes as
  three separate steps. A scheduling rule with no command behind it is obeyable only by
  remembering it.

- **The Standard moves to 0.25.0, and the lease rule it adds is enforced from this
  release.** `backend/no_manual_lease_columns` refuses an application table that
  declares its own lease bookkeeping — a holder column paired with an expiry, a
  heartbeat stamp, or an equivalent claim deadline. **An existing app with a
  queue-shaped table can newly fail its own gate**, which is the point: the pattern is
  refused because the hand-rolled form reliably omits the half that makes a lease safe,
  and until this release there was nothing to use instead.

  The check itself was already here. `terp.arch`'s `check_no_manual_lease_columns`
  shipped with the lease seam, and the Standard had no entry for it — so the framework
  implemented a rule its own pinned spec did not catalogue, and the gate said so:
  *rules shipped without a spec/catalog/backend entry*. That is a lockstep failure
  rather than a design question, and the fix is the release that was already staged.

  Both pins move together, as ADR 0082 requires: `terp-spec==0.25.0` and
  `@terpjs/spec` 0.25.0, with `terp.arch.SPEC_VERSION` and the ESLint adapter's
  `SPEC_VERSION` alongside them — four constants a test holds to one value. The
  Standard is now 82 rules, 69 backend and 13 frontend; the escape hatch is
  `# arch-allow-no-manual-lease-columns: <reason>` and the recipe is
  `terp guide leases`.

### Changed

- **The styling migration is finished: the last five view components and the packaged
  admin screens take their base styles from the shipped stylesheet, so every screen an
  app renders is now restyleable from `theme.css`.** 0.8.0 moved every *component* and
  said, as a count, that five modules still declared base style objects. Those five were
  the view components — the page frame itself, the sign-in screen, the profile screen,
  the module tab strip and the standard listing screen — which is to say the parts an
  app sees most and could reach least. `Page` alone is the frame under every routed
  view, `HubPage`, `OverviewPage` and `DetailPage` included.

  **28 new markers, 159 to 187**, and the two ratchets that tracked the work are empty:
  23 module-scope style objects to zero, and the unmarked-surface worklist from four
  files to none. Zero pixel movement throughout, on both platforms — each component
  measured against the baselines on its own, and every diff intentional or nothing.

  The families an app's `theme.css` can now target: `page`, `page-header`,
  `page-breadcrumbs`, `page-heading` and `page-title` for the frame; `login-view`,
  `login-card`, `login-brand`, `login-title`, `login-form`, `login-sso`,
  `login-separator`, `login-separator-rule` and `login-error` for the signed-out
  screen; `profile-card`, `profile-avatar`, `profile-email` and `profile-role`;
  `module-nav-list` and `module-nav-link`; `resource-list-create`,
  `resource-list-error`, `resource-list-empty`, `resource-list-items` and
  `resource-list-row`; and `admin-form`, `admin-section-title` and `admin-payload` for
  the packaged admin area. `module-nav` and `resource-list` had markers already and get
  a base rule for the first time.

  `DetailPage` and `OverviewPage` deliberately take **no** marker, and that is a
  decision rather than an omission. Each is a context provider wrapped around `Page`
  and renders no element at all, so there is nothing to mark without inventing a box —
  and the box is precisely what must not exist there. `Page`'s runtime slot check reads
  its article's DOM children, so a wrapper around the body becomes the sole body-slot
  child, matches no allow table, and refuses every governed page fail-closed;
  `display: contents` is no escape, because that check is a DOM traversal and the node
  is in the collection whether or not it generates a box. The same edge decides that
  `Page`'s header stays a `<header>` element: the check drops it by tag name, so marking
  it as a `<div>` — which is what marking an element normally looks like — would put it
  back into the body set. Only a copier-generated project has the contract switched on,
  so the example app could not have detected either.

- **`ModuleNav`'s active tab is styled from `data-active`, not from the `aria-current`
  beside it.** Both attributes are on the element and the component sets both from one
  boolean, so the ARIA one looks like the better key — it is what the selected `Tabs`
  tab uses. It is wrong here for a fact about the router rather than a matter of taste:
  TanStack's link props spread the router's own active props **last**, after the
  caller's, so on a `Link` the router has the final word on `aria-current`. That makes
  this the breadcrumb defect's exact shape, and the rule it produced holds — reuse a
  semantic only where the component is its sole author.

  The sharper half is that the two notions of "active" are not the same predicate, and
  they diverge in **both** directions. `activeOptions.includeSearch` defaults to true, so
  with exact matching the router also requires an exact query-string match while
  `ModuleNav` compares the pathname alone — there the router is narrower, and keying on
  `aria-current` would have withheld the accent edge from the tab a user is standing on
  whenever a filter is in the URL. But the router compares paths through
  `removeTrailingSlash` and `ModuleNav` compares them raw, so on a trailing slash the
  router is active and `ModuleNav` is not — and the accent edge goes missing on a tab the
  router calls current. That second case is a real defect rather than a consequence of
  this change: the inline styling it replaced read the same `isActive`, so the behaviour
  is unchanged and it is the navigation model's to fix.

- **The sign-in screen's separator ink moves from `--color-neutral-500` to
  `--color-fg-subtle`, so midnight and twilight repaint it slightly.** The two tokens
  are byte-identical in light and dark, so nothing moves in the two themes with
  baselines; the other two get the value the contrast gate has been measuring all along.
  Only `--color-fg-subtle` has a declared pairing, which is the whole point — this is
  the rest of the migration that moved seventeen sheet rules in 0.8.0, not a new
  argument. The "or" is `aria-hidden` but it is visible text, so it is held to AA rather
  than treated as an ornament.

- **The `<dialog>` refusal now names the alternative instead of only naming
  `ConfirmDialog`.** Reported as "a ban with no replacement is only obeyable by not
  building the feature" — with a request for a general `Dialog`. We are not shipping
  one, and the reason is the reporting app's own code comment: it built the editor in
  an expanded row instead and recorded that *"it turns out to be the better shape
  anyway: the row stays visible, so the finding that sent the author here is still on
  screen while they fix it."* The feature was built, differently and better; shipping
  a general modal would remove the pressure that produced that.

  What was genuinely broken is the wording. "Use ConfirmDialog" is right for a
  confirmation and wrong advice for an edit form, and an author who reads it for one
  concludes the framework is missing something and the rule cannot be obeyed. With no
  severity dial (ADR 0059) the message *is* the control — it is the only thing between
  a refused build and a correct fix. The refusal now names a routed page or an
  expanded row, and asks for a report rather than a raw `<dialog>` if neither fits.
  `BOUNDARY_SPEC.restrictedElementGuidance` carries it, so any other element whose
  named replacement does not fit every case can say so; every element without an entry
  keeps its plain one-line refusal.

### Fixed

- **`terp-cap-sync` no longer strands a `running` run, and no longer lets two
  reconciles of one source overlap.** The deferred follow-up its own docstring
  admitted to is closed rather than reworded: a reconcile now holds a lease on
  `(tenant_scope, entity_type)` for its whole run — on the *source*, because that is
  what must not overlap, and because a lease on a row that does not exist yet cannot
  serialise the decision to create it. A competing reconcile is refused with
  `LeaseHeldError` and retries on its next tick instead of opening a second run
  against the same external system; one that dies mid-loop has its lease lapse and
  its abandoned run closed `failed` with the reason on the row, so the source becomes
  retryable. The heartbeat fails closed, so a worker that stalled past its expiry
  stops rather than finishing over its successor. Leasing is **optional** here: an app
  that wired no lease store reconciles exactly as before, so adopting it is a decision
  about operational guarantees and never a migration.

- **A failed sign-in was announced to nobody.** The error on the signed-out screen was a
  plain paragraph: it appeared, it was red, and for anyone who could not see it nothing
  had happened at all — the form simply sat there with the credentials still in it. It
  carries `role="alert"` now, which `ResourceList`'s error has had since it existed, and
  one attribute covers both the failed-credentials and the failed-SSO path. The
  regression it prevents is the sort no lane can see: the assertion moved from finding
  the text to finding the alert, and the text was always there.

  Not fixed, and named because it is the same debt the toast viewport carries: the region
  mounts together with its content, so a screen reader that was not already observing it
  can still miss the insertion. The durable shape is a region that is always present and
  empty until it has something to say, and that belongs with the toast's next change.

## 0.8.0 — 2026-08-20

The second half of the frontend design system: components stop carrying their
base styles as inline `style={}` and move them into the injected stylesheet,
keyed on the `data-terp` / `data-variant` attributes every component root
already stamps (ADR 0094).

### Changed

- **Every component's base styles have moved out of inline `style={}` and into the
  shipped stylesheet, keyed on the `data-terp` / `data-variant` attributes each
  component root already stamped — so for the first time an app's `theme.css` can
  restyle the framework rather than only recolour it.** This is the release's
  largest change, and it is very nearly invisible: component after component landed
  with **zero pixel movement** across the workbench's per-specimen baselines, which is
  the evidence that a declaration moved rather than changed. What changes is what an
  app can say.

  Very nearly, not entirely — and the exceptions are deliberate rather than fallout,
  so they are listed instead of averaged away. Two are visible in an app: a batch
  action's leading glyph sits **4px** closer to its label, because the hand-rolled
  wrapper was replaced by `Button`'s own already-ruled icon slot; and the DataView
  toolbar's active layout toggle gains an accent border, because a `neutral-100` wash
  measures 1.09–1.16:1 against the band and an ink difference alone made a
  state on two icon-only controls colour-only (SC 1.4.1 and 1.4.11). One is
  density-only: the toolbar's inline padding now reads `--density-cell-pad-x`, which is
  identical at comfortable and 4px tighter at compact — the toolbar was already named
  as a reader of that token while the value was a literal. The rest were workbench
  fidelity fixes, where a baseline had been showing something an app never saw.

  Before this, an app could redefine a token's *value* and nothing else. Card
  padding, control height, table row height, spacing rhythm and every interaction
  state were frozen in the package, because an inline style attribute outranks any
  author rule in any layer. That is also why the shipped stylesheet needed
  `!important` on every state rule it had: **35 declarations at 0.7.0, now ZERO**. Not one
  rule in the shipped sheet outranks an app's `theme.css` any more, which is the
  whole point: for *important* declarations the layer order reverses and unlayered
  styles sort last, so an escalation did not merely outrank an app's stylesheet — it
  made that one declaration unthemeable. The last five came off with `AppShell`,
  which blocked them all on its own. `54` source files carried a style object; `20` do — and that number is deliberately
  the coarse one, because a file keeps its place in it for a single measured value the
  sheet has no business owning. The finer measure is per file and gated: **five** modules
  still declare a module-scope base style object, **23** between them, asserted as exact
  equality so a partial migration has to move the number.

  The mechanism an app should know about is the **cascade layer**, because it is
  what makes overriding pleasant rather than a fight. The sheet is ordered
  `@layer terp.reset, terp.base, terp.state, terp.motion`, and an app's `theme.css`
  is **unlayered** — an unlayered author declaration beats a layered one whatever
  its specificity, so a `theme.css` rule wins against any framework rule without
  `!important` and without out-specifying it. Exactly one rule inside the sheet is
  unlayered too, for the same reason: the `data-density="compact"` re-scoping, which
  inside a layer would lose to the contract's own `:root` token values and silently
  do nothing.

  The corollary is worth stating because it reframes the `!important` count from a
  tax into a wall. For *important* declarations the layer order **reverses**, and
  unlayered styles sort last — so a layered `!important` beats an unlayered
  `!important`. Measured in a browser against this sheet: with the focus ring
  escalated, a `theme.css` rule lost both with and without `!important`; with it
  retired, the same rule wins either way. An escalation does not merely outrank an
  app's stylesheet, it makes that one declaration **unthemeable**. Which is why
  every retirement in this release is a feature and not tidying.

  Specificity is *not* the mechanism, and the difference cost real defects during
  the migration: `[data-terp]:focus-visible` and
  `[data-terp="button"][data-variant="primary"]` both weigh (0,2,0), so only source
  order separates them, and the focus ring is declared first — the moment the
  primary button's resting shadow became a rule in the same layer, a keyboard-focused
  primary button stopped showing a ring at all. States live in `terp.state` above
  `terp.base` precisely so a state rule wins on layer order rather than on luck.

- **The `data-terp` marker vocabulary has grown, and two markers have moved.** Markers
  are the join between a component and both its styling and the layout contract's
  runtime slot check, so the inventory is pinned by a test and belongs in a release
  note. It went from **45 names at 0.7.0 to 159** — 114 new markers, none removed,
  because a component cannot take its base styles from the sheet until every part of
  it a rule needs to reach is addressable.

  They arrive in families, and an app's `theme.css` can target any of them: **31** for
  the DataView cluster (its table cells, cards, pagination, row actions, view-options
  panel, toolbar, scroll container, skeleton and error inset), **12** for the app
  shell (its root, sidebar, drawer backdrop, brand row and title, nav list and labels,
  content column, header, header group, main and footer), **3** for the hub (the page
  grid, and a card's heading row and icon tile), and the rest for the form fields, the
  framework states, `Combobox` and the calendar. Twenty-five arrived with the overlays
  and the chrome, and those are worth naming individually because they are the batch
  in which two markers also *moved*:
  `calendar-grid`; `menu-trigger`, `menu-item-icon`, `menu-item-check`;
  `page-actions`; `theme-toggle`, `theme-toggle-label`, `language-switcher`,
  `language-switcher-label`; `user-menu`, `user-menu-avatar`, `user-menu-identity`,
  `user-menu-email`, `user-menu-role`, `user-menu-header`; `toast`,
  `toast-viewport`, `toast-icon`, `toast-body`, `toast-title`; `dialog-body`,
  `dialog-title`, `dialog-description`, `dialog-actions`; and `markdown`.

  **Two markers moved, and both matter to a `theme.css`.**

  `Menu`'s trigger button was `data-terp="iconbutton"` and is now
  `data-terp="menu-trigger"`. It shared that marker with nine visually unrelated
  buttons — the shell's two header toggles, four pagination arrows, a toast
  dismisser, the combobox's clear button, the calendar's two month arrows — while
  overriding every one of the marker's declarations inline, so nothing keyed on
  `iconbutton` could describe it. A `theme.css` targeting `[data-terp="iconbutton"]`
  expecting to reach a menu trigger needs the new name.

  And `data-terp="calendar-week"` changed what it names. It was on the month grid —
  one element holding all 42 day cells — and now names each of the six week rows,
  with the grid itself becoming `calendar-grid`. That split is what made the ARIA
  grid valid (see **Fixed**), so a rule written against `[data-terp="calendar-week"]`
  now applies six times rather than once.

  Three attribute vocabularies also widened. A toast's tone is `data-tone`, the same
  attribute `Badge` and `Alert` use, so one tone means one thing package-wide — with
  `toast.error()` painting as `data-tone="danger"`, because the shared vocabulary is
  {neutral, info, success, warning, danger} and a fourth synonym would leave
  `[data-terp="toast"][data-tone="danger"]` silently matching nothing. A destructive
  menu item is `data-destructive="true"`; its disabled treatment stays `:disabled`,
  because the element is a real button carrying the real attribute. And a
  `Popover` panel now carries `data-owner`, naming the component whose panel it is:
  the panel is portalled to `document.body`, so a per-component panel geometry has
  nothing to hang on otherwise.

- **Three components name their own rendered root without adding an element to
  anyone's layout.** `ThemeToggle`, `LanguageSwitcher` (inline variant) and
  `UserMenu` return a bare `Menu`, so their root was `Popover`'s wrapper and read
  `data-terp="popover"` — indistinguishable from any other popover and unreachable
  from a stylesheet. `Popover` and `Menu` now accept the root's marker as a prop, and
  each component names itself with `data-variant` separating its variants. `Markdown`
  returned a fragment with no root at all; it now has a wrapper whose single rule is
  `display: contents`, which generates no box — so its blocks remain individual items
  of any parent `Stack` and the diff is zero by construction, while descendant
  selectors become possible for the first time. A prose-rhythm block wrapper remains a
  later, deliberate change.

- **Stacking levels read the tokens published for them.** `--z-index-popover` and
  `--z-index-toast` had no readers while `Popover` hardcoded 60 and the toast
  viewport hardcoded 100; the combobox listbox was the family's only reader and
  pointed at `--z-index-drawer`, one level below where an anchored panel belongs.
  `AppShell`'s three followed with its own migration, and they were the family's
  remaining gap: `--z-index-drawer` had no reader anywhere while the one element that
  wanted it — the shell's mobile drawer — hardcoded 50, and `--z-index-backdrop` and
  `--z-index-sticky` had none either. All three are read now, and gated, because a
  hardcoded number would move no baseline and read as correct.


- **The seventeen sheet rules that painted `--color-neutral-500` as secondary ink now
  paint `--color-fg-subtle`, so the token the contrast gate measures is the token the
  sheet applies.** `token-pairs.json` has always declared `subtle-on-surface`, and its
  background half was exact — `--color-bg-surface` and `--color-neutral-0` carry the
  same value in all five themes, as do `--color-bg-canvas` and `--color-neutral-50`.
  The foreground half was not: the raw ramp step and the semantic ink diverge in two
  palettes (midnight `#7d8590` against `#8b949e`, twilight `#9d90b8` against `#a294bd`),
  so in those themes the gate measured 6.15 and 5.71 on a card while the sheet painted
  5.07 and 5.41. Nothing was illegible — the point is that a gate aimed at a token
  nothing paints is where the next token move goes unnoticed. This is the rest of the
  migration the calendar entry below describes, not a new argument.

  The rule for which ink goes where is unchanged and now has no exceptions:
  `--color-fg-subtle` where the ink lands on a plain surface, `--color-fg-muted` where
  it can land on a tinted one, because subtle fails AA against three of the six washes a
  DataView card can carry. All seventeen were checked against it before moving; none is
  text on a tinted surface. Five are icon buttons whose glyph can reach a toned row or a
  neutral-100 hover, which are graphical objects at SC 1.4.11's 3:1 and reach 4.26 in
  the worst theme — and those pairings are now declared, so that is measured rather than
  argued. Repaints nothing the picture-taking lanes can see: light and dark
  are byte-identical between the two tokens and the screenshot lane covers exactly those
  two, confirmed green on both platforms. Midnight and twilight get slightly darker
  secondary ink.

### Added

- **`defaultOpen` on `Combobox`, `DatePicker` and `DateRangePicker`.** The same
  uncontrolled-open shape `Popover` and `Menu` have always taken, so a filter
  panel can ship with its list already open — and so the subtree can be rendered
  deterministically at all. That second reason is why it lands now: the combobox
  listbox and the calendar have been styled from the framework stylesheet since
  the first half of this migration, and **neither had ever been painted by
  either visual lane**, because `open` was internal state with no way in. Some
  sixteen shipped rules were changeable without any gate noticing. The combobox
  opens with its cursor on the selection rather than nowhere, which is the state
  focusing the box produces.

- **Density is a token family, a prop, and one attribute away.** The contract
  declares live `--density-control-min-height` (2.25rem), `--density-cell-pad-y`
  and `--density-cell-pad-x` (0.75rem) plus explicit `--density-compact-*`
  counterparts (2rem, 0.5rem, 0.5rem) — root-only geometry like every other
  scale, published in the manifest. The react-core sheet re-scopes the live
  tokens under `[data-density="compact"]`, so a subtree root stamped with that
  attribute tightens everything beneath it that reads one: control height for
  `Button`, `Input`, `Select` and the date-picker trigger, cell padding for the
  DataView's cells, cards and bars. A `theme.css` can move either value set
  app-wide.

  `DataView` takes a `density` prop for it. `"compact"` stamps the attribute;
  `"comfortable"` stamps **nothing**, because comfortable is what the token sheet
  declares on `:root` and an attribute for it would match no rule — so the
  absence of the attribute *is* the comfortable case, and the one thing not yet
  expressible is a comfortable island inside a compact subtree. The shell's own
  density prop lands with the shell.

  The cell-padding pair is worth one sentence of history, because it is the
  clearest illustration of the rule this release applies twice: it was declared
  one release earlier, no rule read it, and it was deleted in the same release
  that deleted `--color-fg-on-brand` for the same offence. A token the manifest
  advertises and nothing applies is a knob that does nothing. It is back here, in
  the same commit as its readers.

- **The workbench's `linux` screenshot baselines, so the visual lane runs in CI for the
  first time.** Baselines are split by platform because font rasterisation differs
  between Windows and Linux by more than any tolerance worth keeping, and only the
  `win32` set had ever been recorded — so CI ran the accessibility and keyboard lanes
  and skipped the one lane that compares pixels. Every "no baseline moved" claim in this
  release, including the headline one above, was until now a human claim produced on one
  machine. 156 baselines recorded in `mcr.microsoft.com/playwright:v1.62.0-noble` from a
  clean export of the tree, matching the `win32` filenames exactly; the whole suite green on
  the recording run, and green again on a second run comparing against the recorded set — the
  second run being the half that matters, because a baseline that only passes the run that
  wrote it is not a baseline.

  CI runs the lane inside that same image rather than on the runner directly. A GitHub
  runner shares Ubuntu's kernel with the image but not its font packages, and fonts are
  the entire reason the sets are split — comparing outside the environment that recorded
  would have made the lane noise on its first run. The image tag now has to track the
  pinned Playwright version: a mismatch presents as every baseline failing at once, and
  the instinct that provokes is to re-record, which would bury it.

- **A `nonTextPairs` section in `token-pairs.json`, held to SC 1.4.11's 3:1.** Three
  ratios had been measured, found to matter, and then written into `styles.ts` as prose,
  because the file carried text pairings only and bolting a second kind onto `textPairs`
  would have meant one list held to two bars. Why prose was not enough is on this
  release's own record: the focus ring shipped at 1.67:1 for as long as its value was
  something a person had to remember to check. Ten entries, measured in all five
  themes — the contract suite goes from 193 tests to 248.

  What is left out is the half that keeps the file honest. The focus ring's translucent
  halo is excluded, because the opaque outline is the indicator and the shadow is
  reinforcement around it; the active toggle's `neutral-100` fill is excluded at 1.10,
  which is the whole reason that rule carries a border; and neither the toggle's border
  against the toolbar band nor the focus ring on a card is an entry, because both name the
  same two tokens as the *text* pairing `accent-on-surface`, which holds them to 4.5 and
  would go red first. Declaring them again at 3:1 would add cases that cannot fail and
  overstate what the ratchet covers. A test refuses that restatement rather than leaving it
  to review, because the first draft of this section made exactly that mistake. Asserting a
  ratio WCAG does not ask for is how a data file teaches people to ignore it, which is
  already why dividers are absent from `textPairs`.

  The `--color-neutral-300` control boundary is a real failure rather than a formality —
  1.42 to 2.36 across the surfaces a bordered control sits on, in four of the five
  themes. It is recorded rather than fixed, because the fix is the token value and moving
  it repaints every bordered control in the package, which is a decision about how the
  framework looks and not a side effect of adding a gate. `BELOW_UI` holds all eight at
  their measured floors so the debt can only shrink, and the contrast theme clearing the
  same pairing at 10.37 is what shows the fix is a value rather than a structure. The
  allowance is guarded by *pairing* rather than by theme, unlike the text ratchet: every
  palette inherited the same 300-step boundary, so restricting by theme would have
  backdated a debt none of them chose, while restricting by pairing forbids new debt just
  as firmly.

### Fixed

- **The generated CI no longer fails a green conformance run because the seed
  container finished.** `docker compose up -d --wait api web seed` listed a
  one-shot alongside the long-lived services, and `--wait` reports *any*
  container that exits — including with status 0 — as a failure
  ([docker/compose#10596](https://github.com/docker/compose/issues/10596)). The
  workbench came up correctly (db → migrate → seed → api + web, every service
  healthy), `seed` did its job, exited 0, and the step failed with exit code 1
  before Playwright ever started — so an app whose whole gate was green saw a red
  conformance job with no test output and an empty report artifact. The
  scaffolded workflow now waits only on the services that stay up and runs the
  one-shot after them:

  ```yaml
  docker compose up -d --wait api web
  docker compose run --rm seed
  ```

  `api` already depends on `migrate` with `service_completed_successfully`, so
  the ordering is unchanged. The framework's own `conformance.yml` and the
  `terp verify` hint for the `conformance` check carry the same recipe. Existing
  apps are not migrated automatically — apply the two lines to
  `.github/workflows/ci.yml`.

- **`terp verify --only env-seams` now judges `environment.schema.json`'s own
  shape, so an app can no longer pass its gate with a manifest the deploy side
  refuses.** The reader that renders the declared variables into `.app.env` is
  fail closed on the *whole file*: one defect anywhere and every declaration —
  the app's secrets included — disappears from the environment form and is never
  rendered. That verdict used to be given only there, which put it a deploy (and
  often a different machine) away from the edit that caused it. It happened: an
  authoring agent explained `OIDC_REDIRECT_URI` well and wrote a `description`
  past 500 characters, `terp verify --profile full` stayed green, and the app
  lost its manifest — MariaDB password and all — with nothing in the gate, the
  guide or the shipped manifest's own `$comment` mentioning a length limit.

  The check now reports every defect at once (the reader raises on the first,
  which would cost an author one gate run per mistake), naming the subject the
  way the deploy-side message does — `OIDC_REDIRECT_URI.description must be a
  string of at most 500 characters (it is 501)` — and states the consequence,
  not just the rule. The dialect it judges against lives in
  `terp.cli.envschema`: the `type`/`properties`/`required` shape, at most 50
  variables, UPPER_SNAKE names, platform-owned and `VITE_*` names refused,
  `type`/`title`/`description`/`format`/`group`/`resolvedBy` as strings of at
  most 500 characters, `resolvedBy` in `host | container | browser`, and `enum`
  as at most 50 strings of at most 200 characters. There is no package the two
  sides can share, so the limits are mirrored with matching wording and held
  equal case by case in `tests/architecture/test_cli_env_seams.py`.

  The shape verdict is given *before* the seam verdict: a manifest that is
  refused declares nothing, so reporting which seam supplies its variables would
  answer a question that no longer applies and name the wrong fix. Still a plain
  read of checked-in files — no Docker daemon, no `docker` binary. `terp guide
  environment` grows the limits and the reason the 500-character cap is the one
  an authoring agent walks into.

- **The calendar was three defects deep, and nothing in the repo could see any
  of them.** Its `role="grid"` held all 42 day buttons as *direct*
  `role="gridcell"` children with no `role="row"` between them, which is an
  invalid ARIA grid on two counts at once — a `grid` must own rows, and a
  `gridcell` must be owned by one — so no screen reader could report a day's
  position and axe rated it critical. Its roving cursor moved `tabIndex` and
  nothing else: the focus effect carried an empty dependency list, so an arrow
  key moved which cell was *marked* focusable while the browser's focus, the
  focus ring and every assistive technology stayed on the day the calendar
  opened on. And days outside the visible month were dimmed with
  `opacity: 0.45`, which composites the body ink against the panel to a colour
  that fails WCAG AA in **all five themes** (measured: light 2.93:1, dark
  3.93:1, midnight 4.25:1, twilight 4.05:1, contrast 3.36:1); they now take
  `--color-fg-subtle`, which is 4.76:1 at worst and — unlike a composite of one
  token over another — is a pairing `token-pairs.json` declares, so the static
  contrast gate measures it from here on. The weekday initials move to the same
  semantic token for the same reason: they sat on the raw `--color-neutral-500`
  step, which two palettes deliberately lift `--color-fg-subtle` above, and the
  weekday row is `aria-hidden`, so an undeclared pairing there is permanently
  invisible to axe.

  Worth stating why all three survived this long, because it generalises: the
  calendar only exists inside an open `Popover`, nothing in the repo opens one,
  and the visual baselines capture the resting state. So the component had no
  picture in either lane and axe never reached its subtree — the same blind spot
  that hid `NavIcon`'s fallback tile in 0.7.0. The week rows are real elements
  rather than `display: contents`, and the geometry is unchanged: the month box
  keeps the row gap, each row keeps its seven equal columns and the column gap,
  both from the one token the flat grid used for both axes, so all 42 cell boxes
  and the panel size measure byte-identical before and after. Opacity also
  dimmed the cell's *background*, so an out-of-month day that is selected or
  inside a range used to render as a washed-out chip and now paints at full
  strength — a selected day should read as selected whichever month owns it.

### Removed

- **`Menu`'s `triggerStyle` and `panelStyle`, and `Popover`'s `panelStyle`.** An
  inline-style prop on a framework component is an escape hatch that exists only
  while the stylesheet cannot reach the thing, and a marked root reaches both: the
  trigger by descending from the root, the portalled panel through its `data-owner`.
  `UserMenu` was the last consumer of all three.

- **`--color-fg-on-brand` is deleted from the token vocabulary.** It was
  declared in all five themes and read by nothing: the on-brand ink already has
  a name, `--color-brand-primary-contrast`, and 0.7.0's accent split settled
  that it is the *only* token allowed on a brand-primary surface. A second,
  unread token for the same concept was dead vocabulary every theme had to keep
  filling. No component and no declared pairing referenced it, so nothing an
  app renders changes; a `theme.css` that set it was setting a variable nothing
  consumed, and still is — just without the manifest suggesting otherwise.

## 0.7.0 — 2026-08-18

Two bodies of work, and the larger one repaints every app — read **Changed**
first.

That larger one is the first half of the frontend design system. The ceiling it
addresses was never a missing-components problem: react-core consumed raw ramp
steps directly, so there was no `--surface`, no `--border`, no
`--muted-foreground`, a third theme meant re-deriving every mapping by hand, and
an app's `theme.css` could redefine token *values* and nothing else. This release
lays the semantic layer over the ramp without removing it, publishes the
vocabulary as machine-readable data for the first time, ships five themes where
there were two, and clears every contrast defect the instrumentation found on the
way — including one that turned out to be a defect in the vocabulary rather than
in a colour.

The smaller one is friction reported from an app whose workbench would not boot.
The defect was one variable resolving to the wrong address, and every layer that
could have said so stayed quiet: the gate did not read the seam, compose reported
an exit code without the log that explained it, and there was no way to run the
boot chain without a Docker daemon to find out which half was broken.

### Changed

- **The four light status tones darken, so badge and alert copy reaches AA.**
  `--color-status-success` `#16a34a` → `#15803d`, `warning` `#d97706` →
  `#b45309`, `danger` `#dc2626` → `#b91c1c`, `info` `#0284c7` → `#0369a1` —
  each a step down its own Tailwind ramp, so the palette keeps its provenance
  instead of gaining four bespoke values. They measured 3.07:1 to 4.41:1 against
  their own soft backgrounds and now measure 4.79:1 to 5.91:1. Every `Badge` and
  `Alert` in every app changes colour; nothing changes shape.

- **The accent is two tokens, and `--color-brand-primary` now means only one of
  them.** It was serving as a filled surface behind
  `--color-brand-primary-contrast` (`Button`, avatars, the selected day, the
  brand mark) *and* as ink or a boundary on the app's own surfaces (the selected
  tab, the active nav item, the sub-nav underline, the spinner, the selected
  combobox option, hub-card hover, the input focus ring, and `accent-color` on
  `Checkbox`/`Radio`/`Switch`). In a dark theme those pull one token in opposite
  directions — the surface use needs it dark enough to hold a white label, the
  ink use needs it light enough to read on a dark canvas — and no value satisfies
  both. The dark button label at 3.68:1 and the dark selected tab at 3.98:1 were
  therefore one defect with two symptoms.

  `--color-brand-primary` is now the accent as a *filled surface*, and the only
  thing that may sit on it is `--color-brand-primary-contrast`.
  `--color-fg-accent` is the accent as *ink or a boundary* against one of the
  app's own surfaces. Thirteen call sites inside react-core moved to the ink
  token; the four genuine filled-surface uses did not. **The dark primary button
  label stays white** — the split is what makes flipping it to near-black
  unnecessary, and flipping a shipped label is a visible identity change.

  An app that themed `--color-brand-primary` keeps working and keeps controlling
  every filled accent surface, but no longer controls accent *text*; set
  `--color-fg-accent` alongside it to move both. The dark accent surface deepens
  (`#3b82f6` → `#1d4ed8`) so the white label reaches 6.70:1, and the dark accent
  wash deepens slightly to give the ink room — it was at 4.52:1, which is not a
  margin.

- **`accent-color` on `Checkbox`, `Radio` and `Switch` follows the ink token,
  not the surface token.** The browser picks the check and thumb colour itself,
  so the contrast that matters is the control against the page. Left on the
  surface token these three would have regressed from 3.98:1 to 2.83:1 against
  the dark canvas the moment that token deepened — a fix creating a defect two
  components away, and one no declared pairing would have caught.

### Fixed

- **A pinned theme was overridden by the OS dark preference.** The token sheet's
  `prefers-color-scheme` block was scoped `:root:not([data-theme='light'])`,
  which was equivalent while `light` and `dark` were the only themes and became a
  defect the moment a third existed: it matches `[data-theme='contrast']`,
  outranks it on specificity — two compound parts against one — and so laid the
  dark colours over a theme the app had explicitly pinned whenever the OS
  preferred dark. It now matches the *absence* of the attribute, which is the
  only form that stays correct as themes are added, and that shape is asserted by
  a test rather than left to the generator's comment.

- **Every theme block now declares `color-scheme`.** Without it, native chrome
  the framework cannot restyle — the `<select>` option popup, a natively drawn
  scrollbar, a text caret — renders from the wrong palette: a white popup over a
  black page. This was previously unverifiable rather than merely unchecked,
  because the shared reader behind the token gates returned custom properties
  only, so a `color-scheme` assertion would have passed vacuously.

- **The five contrast defects in the shipped sheet are cleared, and both
  allowance lists are empty.** Light `warning` (3.07:1), `success` (3.15:1),
  `info` (3.84:1) and `danger` (4.41:1) badge copy, and the dark primary button
  label (3.68:1), all cleared 3.0 for large text and failed 4.5 for normal text —
  and badge copy and button labels are normal text. Every declared pairing in
  every theme now reaches AA, `contrast` reaches AAA on all nineteen, and axe
  finds no contrast violation in any of the 155 specimen runs it now performs
  across all five themes.

- **`.app.env` could never supply a variable a compose `environment:` block also
  names — and nothing said so.** Compose resolves `environment:` over
  `env_file:`, so a declared variable listed in both takes its value from the
  developer's gitignored `.env` and the `.app.env` Studio renders is discarded.
  Not merely a stale-override risk: with **no `.env` at all**, `FOO: ${FOO:-}`
  still wins with an empty string, so there is no configuration in which the
  declared value arrives — while the generated AGENTS.md tells apps never to edit
  `.app.env` because "Studio owns environment-specific values". The template's
  compose files now state the precedence rule where the block is written, and
  `.env.example` says what it is and is not for.

- **A passing check's adoption hint is no longer announced only in machine
  mode.** `routes-drift` passes by *skipping* on an app that has not adopted
  route types (ADR 0092), and the "add `"routes": "terp-routes"`" hint reached
  only `--format json`'s `output_tail` — an opt-in nobody is told about does not
  get adopted. Output prefixed `note:` now prints in text mode on a pass too;
  everything else stays quiet, because a passing check's output is otherwise a
  whole test log.

- **`terp docker dev` no longer passes compose's contentless failure straight
  through.** A failed one-shot surfaced as `service "x" didn't complete
  successfully: exit 1` — twice, because two waiters observe one failed
  condition — while the cause (`Connection refused`) sat in a container log
  nobody was told to read. The command owns the topology, so on a non-zero exit
  it now reads `compose ps`, names every service that exited non-zero (once,
  however many waiters reported it) and prints its last 50 lines. Best-effort by
  construction: a daemon that has gone away must not replace the real error with
  an error about diagnosing it.

- **`copier update` no longer overwrites generated-and-committed artifacts with
  the scaffold's stubs.** `frontend/src/routes.gen.d.ts` is written by `terp
  routes` from the app's own module manifests and the template's copy is a
  one-route stub, so an update replaced a whole route table with `"/"` and turned
  every typed navigation into a compile error nowhere near its cause;
  `environment.schema.json` and `escape-hatch-budget.json` are the app's own
  declarations and ratchet, and the template's are empty. All three are now
  `_skip_if_exists`. Documentation the app also edits stays updatable on purpose
  — an app that never receives a corrected explanation is how several of these
  seams came to be misunderstood.

### Added

- **A semantic token layer, over the primitive ramp rather than instead of it.**
  97 → 112 tokens. `--color-bg-*`, `--color-fg-*`, `--color-border-*` and
  `--color-interactive-*` name what a colour is *for*; a `--color-sidebar-*`
  namespace lets the shell sit on its own elevation and read as chrome rather
  than content; `--color-chart-1` … `-5` give charts a palette where there was
  none. Also added, all theme-invariant and therefore declared once in `:root`:
  z-index (the shell hardcoded 30/40/50, `Popover` 60 and toasts 100 — a
  collision surface), breakpoints (the `768px` query was duplicated verbatim in
  `AppShell` and `DataView`), motion durations and easings, line-height,
  letter-spacing and border-width. Space gained 5/7/10/12/16/20 and font size
  gained 2xl/3xl/display; both stopped short before, which is why a page `h1`
  rendered at 1.125rem with no display size above it.

  `--color-neutral-*` and the rest of the ramp stay public and keep working, so
  an app themed against them is untouched. Semantic tokens carry explicit
  per-theme values rather than aliasing the ramp — that is what lets the ramp
  change later without dragging every semantic name with it.

- **`@terpjs/contract/tokens.manifest.json`** — the token vocabulary as
  machine-readable data, exported from the package for the first time. Every
  token with its category, its value in every theme, and whether any theme
  overrides it; the theme list itself; and the foreground/background pairings the
  contrast gate enforces. Three consumers could not get this any other way: a
  theme editor had to hard-code its own list because `tokens.json` is
  Style-Dictionary-shaped and was never exported, an agent editing a theme had to
  infer names out of `node_modules` with no way to tell which tokens are safe to
  theme or which must stay legible against which, and a human had no list at all.
  Generated in the same run as the stylesheet from the same sources, so the two
  cannot disagree, and CI diffs both.

- **Five themes: `light`, `dark`, `midnight`, `twilight` and `contrast`.**
  `midnight` is near-black with cooler neutrals for low light and OLED;
  `twilight` is warm violet-tinted, and its neutrals sit in a different hue
  family, which is what proves a theme is a palette and not a lightness setting;
  `contrast` is high-contrast light, and every one of its declared text pairings
  reaches AAA rather than AA. Each is a complete colour set — a theme that
  forgets a colour is refused, not silently inherited.

  Themes are registered in `themes.json` rather than discovered by file, because
  four things about a theme cannot be read off its source: which theme the OS
  dark preference selects, whether it reads light or dark to native chrome, what
  contrast it promises, and what to call it. A theme may declare a floor above
  AA, which is how `contrast` earns its name by measurement instead of by
  description.

- **`ThemeProvider`, `ThemeToggle` and `Theme` widen to all five, plus
  `system`.** `defaultTheme="midnight"` is how an app ships on a named theme —
  one prop, no other change. The toggle offers every shipped theme with its own
  glyph and a translated label in both bundled locales. The `Theme` union stays a
  hand-written copy rather than reading the manifest at runtime, because
  react-core publishes unbuilt TypeScript and imports nothing but React;
  resolving a sibling package's JSON module would change the consumption model
  for every consumer. A parity test holds the copy to the published list in both
  directions — a theme the sheet ships that the union omits is a palette no app
  can select, and a theme the union offers that the sheet has no block for sets
  `data-theme` to a value nothing matches while the control reports the choice
  took.

- **`--color-fg-accent`** — see **Changed**. The accent as ink or a boundary on
  the app's own surfaces, split out of `--color-brand-primary` because one token
  cannot serve both roles and reach AA in a dark theme.

- **`terp upgrade --check` reports how far an app's scaffolding trails its
  packages.** An app could sit on current libraries, seven-releases-old
  scaffolding and a third version in `node_modules` at once — still working
  around a slot restriction a later release lifted, briefed by a stale
  `AGENTS.md` from the narrower contract — with every gate green throughout. Two
  of those three records were already gated; the template ref was not, and no CLI
  module was aware it existed. It is a report and not a gate, because scaffolding
  legitimately lags a release: three shapes get three answers, and the up-to-date
  case is reported too, since when the packages are current nothing else in the
  toolchain mentions the scaffolding again.

- **`terp verify --only env-seams`** — a new check in every profile, and in the
  template's CI. It reports a declared variable that a compose `environment:`
  block overrides, naming the variable, the file, the services and which seam
  wins; and a `"resolvedBy": "container"` variable whose value is a loopback
  address. Both readings are of checked-in files, so it needs **no Docker
  daemon and not even the `docker` binary** (`docker compose config` is a worse
  oracle despite being daemon-free: it inlines `env_file` into `environment`,
  erasing the distinction being reported). One finding per variable with every
  affected service listed, never one per service — a shared backend anchor puts
  the same override on every service that merges it, and restating one fact six
  times with the recipe repeated buries what is actually wrong.

- **`"resolvedBy": host | container | browser` in `environment.schema.json`.** An
  address is resolved by exactly one party and one value cannot be right for two:
  `127.0.0.1:8000` is the API from a shell and the container's *own* loopback
  from inside the compose network. It is not derivable from a variable's name or
  type, which is why an app can follow the pattern the template appears to teach
  and still be wrong — `OIDC_REDIRECT_URI` is a legitimate `.env` forward
  precisely because the **browser** resolves it. The manifest now records the
  distinction so the check can enforce it instead of guessing. The framework
  reads the annotation from the manifest directly, so the check works on any
  Studio; the matching Studio release stops stripping it from its own view of the
  manifest and refuses an unrecognised value rather than silently opting the
  variable out of the loopback check.

- **`terp smoke`** — the workbench's backend boot chain, in-process, with no
  Docker daemon: migrate, seed, the API, and every one-shot the app added, in
  `depends_on` order against a throwaway SQLite file. It answers "is this my app
  or is this my environment?", which previously meant hand-assembling that chain
  by reading the topology out of `docker-compose.yml` and translating each
  container path and container address by hand. Both translations are read from
  the compose file, never guessed: a bind mount says what `/app/app` means here,
  and `http://api:8000` — a name that resolves only on the compose network — is
  pointed at the port the API was actually bound to. Services that are not the
  backend image are skipped (Postgres is replaced by SQLite; the Vite dev server
  says nothing about whether the backend boots), which is what removes the daemon
  requirement and lets it run in CI. `--plan` prints the translated chain without
  running it.

- **`terp guide environment`** — the two seams, the direction of precedence, the
  host/container/browser distinction, and what to do when a feature adds a
  variable. The generated AGENTS.md carries the rules and points here.

- **`.app.env.example` in the template.** `.app.env` does not exist in a fresh
  checkout and `env_file` is `required: false`, so its absence was invisible: all
  of local development ran on `.env` plus compose defaults, and the first time a
  value actually diverged was in a Studio-managed environment — the worst place
  to meet the precedence rule. `cp .app.env.example .app.env` makes the inner
  loop use the seam production uses.

## 0.6.1 — 2026-08-14

Friction reported from an app weighing — and then taking — the 0.6.0 upgrade:
the notes that are supposed to justify an upgrade could not be read until after
it, and the release's new rule was simultaneously over- and under-broad in ways
that only surfaced against a real schema graph.

### Fixed

- **`schemas_avoid_positional_tuples` now judges the wire shape, not the
  spelling — and reports every offence in one boot.** Three defects in the
  0.6.0 rule, found together:

  *The runtime half missed the exact shape it exists for.* Its walk over model
  annotations kept only bare classes, so a discriminated-union member — not
  `isinstance(_, type)` — stopped the walk dead, and a `prefixItems` field
  inside that member sailed through unflagged. The boot check now validates the
  **generated OpenAPI document itself**: whatever route a type takes into the
  contract — a union member, a type alias, a generic parameter, a custom
  `__get_pydantic_core_schema__` — its schema is in the document, and a
  positional array shape (`prefixItems`, or the list form of `items`) is
  refused there. That is also what this rule's runtime half was documented to
  do all along.

  *It refused variadic tuples, which are not positional.* `tuple[X, ...]` emits
  byte-identical JSON Schema to `list[X]` — it is the immutable spelling of a
  homogeneous sequence, the natural annotation for a frozen value object — so
  refusing it forced source rewrites with provably zero wire effect while the
  message asserted something false. Both halves now exempt it (the document
  check gets this for free: nothing positional is emitted); a fixed tuple
  nested *inside* one (`tuple[tuple[str, int], ...]`) is still refused.

  *The runtime half raised on the first offence.* An app with many offending
  fields was handed fix-one-reboot-repeat, once per field. One boot now names
  every offending location in a single error, so the whole cleanup is priced
  before the first edit.

- **The lockstep gate now covers the frontend half.** `platform-install` read
  only `metadata.distributions()` — backend wheels — so an app with
  `@terpjs/react-core` pinned a release behind `terp-core` passed the gate and
  the full profile green: a fresh CI install would build the frontend against a
  platform combination that was never released, with the gate as evidence. The
  changelog's "the gate enforces the lockstep" claim was, for an app,
  unenforced on the npm side. The check now also reads **every** app manifest
  that declares a `@terpjs/*` package (discovered, never a named list — the
  template ships pins in both `frontend/package.json` and
  `conformance/package.json`) plus the installed copy under `node_modules` when
  present, so repinning without reinstalling is caught too. `@terpjs/spec` is
  excluded on the same grounds as `terp-spec`: its own release cadence. The
  upgrade recipe's step 3 now names both manifests instead of only the frontend
  one.

- **`terp upgrade --check` now says how to read the *target's* notes, not the
  installed ones.** The release notes ship inside the terp-core wheel so that
  `terp guide changelog` answers offline — which also means the installed copy
  ends at the installed version and structurally cannot describe the release the
  upgrade recipe asks you to judge. Step 1 of the recipe said "read what
  changed" and pointed at that copy; on an app at 0.5.x with 0.6.0 available,
  the step was impossible at the exact moment it mattered, and the reader's only
  move was to go hunting for the repository. Step 1 now prints
  `uvx --from terp-cli==<target> terp guide changelog`: an ephemeral CLI
  resolved from the same index (terp-cli pins terp-core exactly, so the target's
  CHANGELOG comes with it) that prints the target's notes without touching the
  app's environment or its pins. `terp guide changelog` itself now states where
  its notes end and prints the same escape hatch, for the reader who starts
  there instead of at the upgrade check.

### Added

- **Every distribution now says where it comes from.** No terp-\* wheel carried
  `[project.urls]`, so "where do these packages come from" — the first question
  of the hunt above — was answerable only by searching. Every backend pyproject
  now declares `Repository` and `Changelog` URLs, so `pip show terp-core`
  answers it in one step; the npm packages already carried `repository`, and the
  release gate now holds both halves
  (`tests/architecture/test_release_versions.py`).

  Requires spec `0.24.0`.

## 0.6.0 — 2026-08-14

### Added

- **A schema field can no longer cross the wire as a positional tuple
  (`backend/schemas_avoid_positional_tuples`).** A tuple-annotated field serialises
  into the contract as an array whose element types are positional (`prefixItems`, or
  the list form of `items`), and client generators disagree on that shape — so an app
  that exposes a tuple anywhere in its API cannot type its own calls against its own
  API. The reason this earns a rule is the failure mode, not the frequency: the error
  surfaces at the *call site* as an opaque generic mismatch, nowhere near the field
  that caused it, naming two types that print identically unless error truncation is
  disabled. It is a one-line fix per field once you know, and an afternoon until you
  do. Compliant shapes are a nested schema with named fields (when the positions
  differ in meaning) or a homogeneous `list[...]` (when they do not).

  Two layers, and each catches what the other cannot. The build-time half
  (`terp.arch`) reads the annotation and follows a tuple through unions, containers
  and mapping values, so `list[tuple[str, str]]` is caught as readily as a bare one.
  The runtime half walks the composed route table at boot and refuses a positional
  array in the generated document — which also covers a tuple arriving through a type
  alias, a generic parameter, or a custom `__get_pydantic_core_schema__`, none of
  which a source scan can see. Scope is the API boundary only: a DTO, or any model
  used as a request body or response; a tuple in service-internal code is untouched.
  Requires spec `0.23.0`.

- **Route paths and params are checked at compile time, from generated types (ADR 0092).**
  0.5.10 closed half of this: `useRouteParam` stopped a typo'd param from silently reading
  `undefined` *at runtime*. The other half is why the ADR exists — the router is built at
  runtime from the module manifests, so TanStack's type registry is empty and **nothing**
  could check a route path or a param name; a typo'd path was a dead link that shipped
  green, against the platform's own line that a red typecheck means the app does not work.
  The manifests are static data, so the check is now generated from them:
  - `terp routes` (a `terp-routes` bin from `@terpjs/contract`) parses each
    `src/modules/<name>/module.tsx`, reads the `path` literals out of every
    `defineModuleManifest(...)`, and writes a **committed** `src/routes.gen.d.ts` that
    augments `TerpRouteTable` — deduped, sorted, LF-only, so a committed artifact diffs
    cleanly.
  - Three checked seams consume it: `useRouteParams("/records/:recordId")` (exact, per
    route), `useRouteParam(name)` (checked against every declared param name), and
    `useTerpNavigate()` (an undeclared path is a type error; a parameterised route requires
    its params, in the manifest's `:id` spelling, translated to the router's `$id`).
  - `routes-drift` gates it in every verify profile, ordered **before** the typecheck: a
    stale table otherwise reads as a pile of errors in the app's own screens when the real
    fault is one unregenerated artifact. `--check` re-renders and compares, so it needs no
    git, catches a hand-edit, and prints the command that fixes it. `terp dev` regenerates
    as a preflight beside the OpenAPI export.
  - Extraction fails closed: a `path` that is not a plain string literal is refused with
    its file and line, never skipped. A partial table is worse than none — it turns a real
    path into a type error and teaches authors to distrust the check.
  - Opt-in for an existing app: with no `routes` script wired, the preflight and the gate
    are no-op successes carrying the adoption hint (the shape `api-docs-drift` has for an
    uncommitted `docs/`), so upgrading the framework cannot break `terp dev` or turn a gate
    red. The template ships the script, the committed table and the CI step, so a new app
    is gated from its first commit.

  Two things this deliberately does not do. The table covers the app's own manifests only,
  so it never drifts because a dependency's internals changed; packaged-area screens (the
  admin area) read their params through an internal untyped helper, since an app that
  declares no params of its own must not fail on framework code it does not own. And the
  guarantee is itself gated — a compile-time assertion in the example app fails if the
  check ever stops being a check, because that failure is otherwise invisible.

## 0.5.10 — 2026-08-14

Friction reported from building registry and catalog modules on Terp — the
frontend batch. The common shape: the platform had the right opinion and made the
author work around it — a sanctioned component the contract refused, a singleton read
spelled as a one-element list, a normal state spelled as exception control flow, and a
whole class of routing mistakes no layer could turn red.

### Added

- **`useRouteParam` — the fail-closed route-param read (ADR 0092).** `buildAppRouter`
  realises routes at runtime from manifests, so TanStack's type registry is empty in
  every Terp app: no route path or param name is checked anywhere, and the idiomatic
  read was an unchecked cast — `useParams({ strict: false }) as { recordId?: string }`
  — carried by the framework's own admin detail screens. A typo silently yielded
  `undefined` and shipped green, against the platform's own "a red typecheck means the
  app does not work". `useRouteParam("recordId")` returns the declared param and throws
  a directive error for an undeclared name; both admin screens adopt it. The full fix —
  a committed, drift-gated `routes.gen.d.ts` in the `terp openapi` shape — is designed
  in ADR 0092 and lands separately.
- **`useRecord` — the singleton counterpart of `useResource`.** Every detail screen
  spelled its one record as a one-element collection (`list: async () =>
  [unwrap(await client.GET(...))]`, then `items[0]`) — including both packaged admin
  detail screens, now converted. `useRecord({ get }, deps)` returns
  `{ item, loading, error, cause, reload, mutate }`, implemented over `useResource` so
  the two state machines cannot drift. A `get` resolving `null` is a normal absent
  state, not an error — compose with `unwrapOptional`.
- **`unwrapOptional` — absence as data on the client.** `GET .../latest` answering 404
  is a normal state for a snapshot nobody published yet, but expressing it meant
  `try/catch` around `unwrap` filtering on `status === 404` at every call site.
  `unwrapOptional` returns the data, or `null` on a 404, and throws the same `ApiError`
  for every other failure — `BaseService.find` (0.5.9) beside `get`, answered for the
  client.
- **`DataView` rows carry their own state: `getRowTone`.** A validation-driven table
  could only express "this row is refused" as a Badge inside some column — the wrong
  altitude; the *row* is in that state, not one of its cells. `getRowTone={(row) =>
  tone | null}` tints the row/card with the tone's soft token (the exact tokens `Badge`
  uses, so the vocabulary stays one) and stamps `data-tone`; a toned row outranks the
  selection tint.

### Changed

- **`Card` is now allowed directly in `OverviewPage` / `DetailPage` body slots
  (`standard` layout contract).** The README called `Card` "the sanctioned visual
  separation between sections" while the contract refused it in every governed body
  slot — the two disagreed, and the workaround (wrap it in a `Stack`) cost one
  structure-free element. The allowlists now include it, and the previously
  undocumented nesting rule is stated where the contract lives: both halves govern the
  slot's **direct children only**; an allowed container's subtree is the app's to
  compose.
- **`InMemoryDataViewRepository.searchFields` is compile-checked against `getValue`.**
  A misspelled entry resolved to `undefined` for every row, so search silently never
  matched it — no error at any layer. The options are now generic over the field union:
  annotate `getValue`'s field parameter (`(row, field: keyof Ticket & string) =>
  row[field]`) and `searchFields` is checked at compile time (`NoInfer` keeps a typo
  from widening the union). An unannotated `getValue` keeps today's unchecked-`string`
  behavior, so no existing code changes. A runtime dead-field warning was considered
  and rejected: a legitimately optional field that is `undefined` for every current row
  is indistinguishable from a typo.

### Fixed

- **`NavLinkContext` / `useNavLink` are actually importable.** 0.5.4's changelog listed
  them as published, but they were never exported from the package barrel — an app
  could not import what the changelog promised. Exported, with `NavLinkRenderer`.
- **The `DataViewRepository` doc example compiles.** The JSDoc example omitted the
  required `getValue` option; it (and the quick-start) now show the annotated pattern
  that makes `searchFields` compile-checked.
- **`terp seed --seed` says what it is.** The help read as "override where the seed
  lives"; it is a *stage selector* — point it at any `callable(session)` the app
  exposes (`terp seed --seed app.demo:install`) to run only that stage. Help text and
  module docstring now say so; a workbench that already seeded the baseline never needs
  a second full pass.

## 0.5.9 — 2026-08-13

Friction reported from building a publish validator on Terp. All three fixes
share a shape: a platform default that is right for most code and slightly wrong for
code that **reports** rather than aborts — a validator owing its caller every reason at
once, and a route that judges a document instead of storing one. Each moves a guarantee
out of prose or absent code and into something the platform states and enforces.

### Added

- **`ErrorDetail` puts structured reasons in the error envelope.** An `AppError`'s
  `code` classifies the refusal; it cannot also classify each *reason* for it. A
  validator that reported three problems at once therefore flattened three stable
  codes and three document paths into one English `detail`, and the only way for a UI
  to highlight the field that failed was to substring-match prose — a contract nobody
  promised and every message edit breaks. `AppError(..., details=[ErrorDetail(code,
  loc, msg), ...])` now renders a `details` array beside `detail`, shaped like
  FastAPI's own 422 entries so a frontend handles both in one branch. Strictly
  additive: an error carrying no details renders exactly the three documented keys, so
  every existing client is unaffected.
- **`BaseService.find` resolves a row without raising.** Asking "does this id resolve
  *for this caller*?" was spelled `try: … get(…) … except NotFoundError: return None`,
  re-implemented in every service that composes a sibling — and an `except` that later
  grows to span two lookups starts swallowing the wrong one with no sign. `find`
  returns `Model | None` through the *same* `base_query` as `get`, so absence becomes
  data without widening what a caller may see; `get` is now `find(...)` plus the
  raise. Reach for `get` when absence ends the request, `find` when it is one input
  among several.
- **`@read_only` declares "unsafe verb, pure computation".** Terp derives write
  authority from the HTTP method, which is right for almost every route and blind to
  one: the handler that is a `POST` because its *input* is a body, not because it
  writes — validating a candidate document, previewing an import, costing a plan.
  Such a route was pure only by the absence of a write, a guarantee made of missing
  code that holds until an edit adds a line and that no rule and no reviewer is
  prompted to check. `terp.core.read_only` states the intent and both halves of the
  platform enforce it: the new `declared_read_only_routes_do_not_write` rule refuses a
  decorated handler that calls a mutating service method, and `create_app`'s read-only
  binder marks the request read-only so the `BaseService` chokepoint refuses a write
  the rule could not see statically. The same argument `append_only = True` answers for
  a table, answered for a route. Authorization is deliberately untouched — a decorated
  `POST` is still authorized at the write tier, because declaring purity narrows what
  the handler may do, never what the caller must hold.

## 0.5.8 — 2026-08-13

Friction reported from building two modules on Terp, all of the same shape: the
platform knew the answer and made the author find it. Every fix here moves a message
from diagnosis to prescription.

### Added

- **`append_only = True` on a service states that a table is immutable once written.**
  A ledger row, an immutable revision, a captured snapshot achieved immutability by
  *not mounting an update route* — a guarantee that lives in the absence of code and
  evaporates the day someone adds one, with nothing to review against. Declaring it
  puts the refusal at the write chokepoint instead: `update` / `delete` and any
  bespoke `_save` of an existing row fail closed with the uniform 409, whatever the
  route surface looks like. The wrong thing is no longer the easy thing.
- **`terp fmt` formats the files this change touched, not the whole tree.** `ruff
  format .` is the right formatter with the wrong blast radius: on a project whose
  history predates the current ruff version it rewrites files the change never
  touched, so the review diff arrives half signal and half churn and the author's only
  recourse is to `git checkout` each unrelated file — a manual step at exactly the
  moment they were automating one. `terp fmt` defaults to the git-changed set
  (modified, staged, untracked), takes `--check` for the CI shape, and keeps `--all`
  for the deliberate whole-tree pass. Outside a git work tree it formats nothing
  rather than everything.

### Changed

- **The write chokepoint dumps JSON-column fields in JSON mode.** A typed value object
  stored in a JSON column — the natural shape for a document a module validates once
  and stores whole — was dumped in pydantic's *python* mode, so a `UUID` / `datetime` /
  `Enum` inside it reached the JSON serializer as a Python object and died at `flush`
  with `TypeError: Object of type UUID is not JSON serializable`: a message naming
  neither the field, nor the column, nor the fix (a `PlainSerializer` annotation the
  guide never mentioned). The chokepoint knows the column types, so it now dumps
  exactly the JSON-backed fields in `json` mode and leaves every other column its
  native Python value.
- **`terp migrate make` answers both of its walls, in one paste.**
  Autogenerate needs a database at head to diff against, and the settings default is
  in-memory SQLite, so every module author meets this refusal once per module —
  forever, and the recipe was theirs to invent. It now prints the exact two commands
  that work against a throwaway file database (with the PowerShell spelling), names
  the label they passed, and points at `--no-autogenerate` for the hand-authored case.
  The *second* wall got the same treatment: the file database the first refusal sends
  you to is empty, therefore behind head, so `make` failed again — and answering with
  "run `terp migrate status`" would have made one intent cost three round trips. The
  behind-head error now leads with `upgrade` then `make`, spelled against the database
  URL the author is already using. Both recipes are in `terp guide migrations`, so an
  author who reads first meets neither.
- **`no_oversized_python_files` proposes a cut, not just a number.** Naming the cap
  leaves the expensive half — finding the seam — to the author, using information the
  checker already has: it parsed the file, so the connected components of its
  top-level definitions are free. The violation now names the largest group of
  definitions that nothing outside it references, which is a group that can move as a
  unit without leaving a dangling name behind. When a file's definitions all reference
  one another there is no honest seam, and the message stays the bare cap rather than
  inventing a cut that would produce two coupled files instead of one long one.
- **`module_dependency_graph_is_acyclic` reads real imports, not only declarations.**
  A cycle closed by an import whose `ModuleSpec(requires=...)` entry had not been added
  yet was invisible to the gate and surfaced at app startup as a circular-import
  traceback — which names files, not the design mistake, and arrives minutes after the
  edit that caused it. The graph is now declared edges *union* actual imports, so the
  cycle is reported the moment it is written; the message names the cycle path and
  offers an app-level contracts module as the place to lift the vocabulary the two
  modules disagree over.
- **`terp guide service` prices the cost of a pure validator.** A validator that needs
  a fact from another module's table is the common case, and with no pattern written
  down the tempting answer is to hand the validator a session — putting a read outside
  the chokepoint and making it untestable without a database. The guide now shows the
  constructor-threading shape: the calling service looks the fact up, the validator
  stays pure, and the sibling dependency is visible in the manifest as a declared edge.

## 0.5.7 — 2026-08-12

A seam for a feature that lives one layer up: Terp Studio's Themes settings screen
needs a file to write a chosen theme into, and until now there wasn't one.

### Added

- **The frontend starter ships an empty `theme.css` overlay, imported right after
  `@terpjs/contract`'s tokens.** Studio applies a theme to a scaffolded project by
  overwriting one file with a `:root { --token: value; ... }` block; without a
  dedicated file, applying a theme meant hand-editing `main.tsx` or inventing a
  per-project convention. `theme.css` starts empty — the project renders with the
  framework's default tokens until a theme is applied — and only ever redefines the
  tokens a theme customises, so the normal CSS cascade covers everything else. Hand
  edits are safe: Studio only applies a theme when the workspace has no uncommitted
  changes, and the change lands as a normal, reviewable edit, never an auto-commit —
  but they are overwritten the next time a theme is applied.

## 0.5.6 — 2026-08-12

Deployments get a database they can choose, and four silences get a voice. The thread
running through it: the platform already knew the thing, and only said it somewhere
nobody was standing — or, in three cases, said nothing at all until an app hit it.

### Added

- **The production profile reads `DATABASE_URL` from a seam.** It was hardcoded to the
  bundled `db` sidecar, so the only supported topology was the one the profile shipped
  with, and a client who already operates PostgreSQL — a cluster, a DBA, a managed cloud
  database with its own backup and DR regime — had to fork the profile, which moves a
  deployment concern into application source and diverges forever. One line changes:
  `DATABASE_URL: ${DATABASE_URL:-postgresql+psycopg://…@db:5432/…}`. Unset is
  byte-identical to before (`docker compose up` by hand still works with nothing else
  configured); set points the app at any PostgreSQL, and an override drops the
  then-unused sidecar. `POSTGRES_PASSWORD` keeps its fail-fast `:?` guard where it
  belongs — on the `db` service — so a bundled deployment still refuses to start without
  it. Pinned in both the template and the example profile by
  `tests/architecture/test_prod_profile.py`.
- **Production says out loud when idempotency is per worker.** A per-instance store is
  *correct* for a single production instance, so refusing it outright would break a
  deployment that is not wrong — but its absence was silent, and the failure when the
  assumption stops holding is the worst kind: scaling to a second replica turns "this
  mutation runs once" into "once per worker a retry happens to land on", with no error,
  no failed request, and nothing connecting the duplicate rows back to the `--scale` that
  caused them. Boot now states the property it is actually running with and names
  `create_app(require_shared_idempotency_store=True)` as the flag that turns it into a
  refusal. A deployment that already holds the guarantee is not nagged, and local runs
  say nothing.
- **`terp_audit`, the test seam events already had.** A service-level test asserting on a
  durable audit trail found `select(AuditEvent)` returning `[]` — the default sink only
  logs, so nothing was ever written, and *an assertion about an empty result passes*. The
  test reported that audit worked; what it had established was that no sink was
  installed. `terp_audit` (typed `InstallAudit`, the twin of `InstallEvents`) closes the
  asymmetry, and `terp guide testing` now says what an empty audit assertion actually
  proves.
- **`terp guide soft-delete`.** `OwnedMixin` has `ownership` and `TenantScopedMixin` has
  `tenancy`; the third trait had no topic at all, so its rules were only findable after
  you had already made the mistake.

### Fixed

- **`terp migrate make` no longer answers the first question in raw Alembic.** `terp new
  module x` then `terp migrate make x` is the documented workflow, and on the settings
  default (in-memory SQLite) it failed in a 25-line traceback ending in "Target database
  is not up to date" — which names neither the cause nor the fix, and never says
  `DATABASE_URL`. Authoring a revision is a script-tree job, but *autogenerating* one
  diffs the live database; the stateful-command set is now conditional, so
  `make --no-autogenerate` still works with no database configured while the default
  gets the same readable refusal `upgrade` and `check` already give. A
  configured-but-behind database gets `DatabaseBehindForAutogenerateError`, raised in the
  orchestrator so a direct `terp.migrations.make` caller (Studio) gets it too.
- **`SoftDeleteMixin` stops telling you to write the filter the gate refuses.** Its
  docstring still said core installs no global filter and "the caller filters
  `deleted_at IS NULL` explicitly" — true when the trait was written, false since
  `apply_row_scope` took the filter over, and the worst kind of stale: an agent composing
  the mixin reads the mixin, and this one sent it to hand-write the exact predicate
  `no_manual_scope_filtering` refuses. A test pins the docstring to the behaviour
  asserted in the same file.
- **`@terpjs/conformance` now publishes compiled JavaScript.** It exported `./src/index.ts`
  like its siblings, but unlike them it is loaded by Playwright's runner from inside
  `node_modules`, where Node refuses to strip types at all — so an installing app got
  "No tests found" while this repo, whose own suite imports `../src`, saw nothing wrong.
  `prepack` builds the artifact and CI asserts it exists.
- **A generated app's CI generates its typed client before type-checking.** The client is a
  build artifact and git-ignored, so a fresh checkout has none; Vite erases type-only
  imports, so `build` passed and only `tsc` failed — invisible on the blank scaffold and a
  permanent failure the moment a module first calls the API.
- **The lockstep ratchet reads every template manifest, not one named path.** The
  conformance suite pins `@terpjs/conformance` in a second `package.json.jinja` that no
  test looked at; it sat four releases stale. Manifests are now discovered, and a test
  asserts the discovery is not quietly empty.

## 0.5.5 — 2026-08-11

A CLI that can answer "which Terp is this?", a gate that refuses to answer anything when
the install is incoherent, and a release pipeline that can no longer half-publish. The
theme is the same in all three: the platform knew something and only said it where nobody
was listening.

### Added

- **`terp --version`.** Reports the whole lockstep set, not one number — every installed
  `terp-*` distribution, discovered from the environment rather than a hand-kept list, and
  any package that disagrees named with the fix. Terp is pinned by hand across two
  manifests, so the natural failure is a forgotten pin leaving one package a release
  behind, and until now nothing detected it.
- **`terp guide changelog`.** This file, from an installed app: an upgrade you cannot read
  about is one you will not take.
- **`terp upgrade --check`.** Whether a newer Terp exists, without editing a manifest to
  find out.
- **`terp inspect capabilities` reports each capability's version**, so a mixed install is
  visible from the surface that lists what is installed.
- **`platform-install` check in every `terp verify` profile.** A mixed set is a forgotten
  pin, not a supported combination, so a gate run against it proves nothing in either
  direction — a green is not evidence and a red may belong to the mismatch. `terp
  --version` had warned about this since earlier in this release; a warning inside a
  command nobody runs before shipping is not a control. It now refuses, first, and the
  generated project's CI runs the same check before spending the gate.
- **`forwarded_filters_are_declared`.** A filter forwarded to a service that never
  declared it silently returned unfiltered rows. Enforced at runtime *and* build time.

### Fixed

- **A read filter named but valued `None` no longer skips its own declaration check.** The
  name was checked after the value, so the fail-open path was reachable with an empty
  filter.
- **The release can no longer publish to one registry and not the other.** PyPI and npm
  are both immutable, so a version only one accepted can neither be completed nor
  withdrawn — it is burned while still being pinnable, and a lockstep release burns it for
  all sixteen distributions at once. `publish-npm` now runs after `publish-pypi`, the leg
  that builds an artifact and can therefore fail on one, so a rejection leaves nothing
  published and the version free to re-cut. The PyPI publisher pin also moved forward: it
  was frozen at a digest whose bundled twine rejects the metadata today's build backend
  emits, which is exactly how `terp-spec` 0.21.0 was lost.
- **The backend build contexts carry the files the packages force-include.** `terp-core`
  force-includes the repo-root `CHANGELOG.md` (so `terp guide changelog` works from an
  installed app), which fails the image build outright in a context that copies only
  `packages/`. Nothing local catches this: neither the gate nor CI's gate job builds a
  wheel.

## 0.5.4 — 2026-07-31

Five findings from the first app to build real screens on the frontend surface, plus the
tooling half of 0.5.3's isolation story. Every one of them was silent: a documented route
that never matched, a link that reloaded the page, an envelope field CI keys off that was
never a count, a guide teaching an API that does not compile, and a green strict run that
proved less than it looked like.

### Added

- **`--terp-report-runtime-installs`.** Strict isolation resets *before* fixtures run, so
  an autouse installer in a project's own `conftest.py` hands every test a runtime it
  never asked for and a strict run agrees every time — the blind spot 0.5.3 could only
  warn about in prose. The flag compares the state each test starts from with the state
  it ends with and reports, per seam, the tests that installed it. Read the shape of the
  answer: one or two test ids under a seam is a test installing what it needs; every id
  in a package under one seam is a fixture installing it for them.
- **`routerPath()` (`@terpjs/react-core`).** The route spelling the contract documents
  (`/things/:id`) now mounts, alongside TanStack's own `$id`.
- **`NavLinkContext` / `useNavLink()` (`@terpjs/react-core`).** Published by
  `buildAppRouter`, so framework chrome can link through the router.

### Changed

- **`Breadcrumbs` and `HubCard` link through the router by default.** They previously
  emitted a raw `<a href>` — the construct the boundary lint refuses in module code — so
  every crumb click was a full page reload. Passing `renderLink` still overrides; outside
  a Terp router the anchor remains the fallback.
- **`Badge` takes its text as children**, the way every other component in the catalog
  does. `label` keeps working; the two are mutually exclusive in the type.
- **The boundary lint's machine envelope states the verdict** (`"ok": true | false`).
  `terp_findings` was always a *format version* (ADR 0083), but a field named like a
  count, sitting next to `findings`, was read as one by every first reader — including
  CI. The version stays; the answer is now next to it.
- **`terp guide dataview` teaches the real API.** Three of its lines did not compile
  (`InMemoryDataViewRepository` options, a `keyField` prop that never existed, column
  keys). The guide's snippets are now a typechecked `.tsx` fixture pinned to the guide
  text by a test, so neither half can move without the other.
- **`@terpjs/contract`'s `ModuleRoute.path` documents the translation** each adapter
  performs, instead of an example that only worked in one of them.

## 0.5.3 — 2026-07-31

Four findings from the first app to adopt 0.5.2's shipped test isolation, fixed where
they belong: three in the isolation story itself, one in `terp migrate`.

### Added

- **Strict test isolation (`terp_strict_isolation`).** Snapshot-and-restore is faithful,
  and that is its blind spot: a runtime installed *before* the first test — a stray
  `import app.main` at collection time, a module-scope `create_app()` — is part of the
  snapshot, so it is restored before every test and covers every test equally. The suite
  stays green together and red alone, and 0.5.2's autouse fixture could not see it,
  because nothing had leaked. Set `terp_strict_isolation = true` (or pass
  `--terp-strict-isolation`) and the snapshot is followed by a reset: every test starts
  from the platform baseline, so a test that only ever passed on ambient state fails
  where it stands. It is opt-in because a suite may *deliberately* compose once at
  import, and the platform does not break that under anyone; new projects from the
  template start with it on, and the framework now runs its own suites that way.

### Changed

- **`terp_events` carries a real signature.** The fixture that exists so an app never
  has to import the non-public `configure_events` was handing back a
  `Callable[..., None]` wrapper typed `(catalog: object, *, dispatcher: object | None)`
  — no completion, and no type error for the wrong catalog. It now *is*
  `configure_events`, typed as the exported `InstallEvents` protocol
  (`EventCatalog`, `EventDispatcher | None`), so the app pays nothing for the
  indirection. Annotate the fixture parameter `InstallEvents`.

- **`terp migrate` refuses an in-memory database.** With no `DATABASE_URL` configured,
  the settings default is in-memory SQLite — so `terp migrate upgrade` printed
  `upgraded: [...]` against a database that ceased to exist when the process did, and
  `terp migrate check`, one line later in the same shell, reported the app behind its
  code. Both outputs were true; the pair was actively misleading, which is worse than
  either failure alone. The stateful commands (`upgrade`, `downgrade`, `stamp`,
  `status`, `check`, `adopt-schemas`, `grant-runtime`) now refuse an in-memory URL —
  any spelling of it — and name the fix. The script-tree half (`make`, `merge`,
  `heads`, `upgrade --sql`) never needed a database and is unaffected.

- **`terp guide testing` leads with what you must still do yourself.** The topic opened
  with "you get isolation for free — no conftest.py line, no opt-in" and only reached
  "isolation does not *install* a runtime your test needs" in the fourth bullet. That
  distinction is the entire migration, and the headline read as "delete your conftest".
  Inverted, with a per-seam table (all six: restored automatically vs installed by you).

## 0.5.2 — 2026-07-31

Four things an app could get wrong with no failure to look at. A declaration that
reality does not back, a reality no declaration mentions, and a test suite whose green
depends on collection order all share one shape: nothing breaks, so nobody looks. This
release turns each of them into a refusal at the earliest moment the answer is complete.

### Added

- **Process-global runtime isolation ships with the platform.** `terp-core` now
  registers a pytest plugin (`terp.core.testing`, under `pytest11`), so every app gets
  the `terp_runtime_isolation` autouse fixture without a `conftest.py` line — plus
  `terp_events` (switch the bus on for one test) and `terp_default_runtime` (state the
  baseline instead of inheriting it). `create_app` installs six runtimes into process
  globals, and in a test process the last app composed is still installed when the next
  test runs: a unit test against a bare engine inherits a durable audit sink, and a test
  asserting an event was emitted can pass only because an earlier import configured the
  bus. The framework had always carried the fixture in its own repo-root `conftest.py`
  and never shipped it, so every app had to first meet the hazard as a suite that passes
  together and fails alone. The fixture snapshots and restores rather than resetting, so
  an existing suite pays nothing. Seams register themselves
  (`terp.core.runtime`), and the gate holds the registry against the kernel's own
  `reset_*_runtime` functions so a seventh seam cannot be added and quietly left out.

- **A declaration no base reads is refused** — at class definition (`TypeError`) and
  again at boot (`BootError`). A service that sets `event_map` but forgot to inherit
  `EventEmittingService` is real, correct, reviewed, and does nothing. A base names what
  it consumes (`consumes_declarations`); the kernel needs no knowledge of any
  capability's declaration to spot an inert one. The boot check is not redundant with
  the class check: `__init_subclass__` can only compare against the bases imported so
  far, and "forgot to inherit the base" is usually "never imported the capability", so
  boot is the first point where the answer is complete.

- **A subscription with no handler is refused at boot.** `ModuleSpec.subscribes` says
  the module reacts to an event, while the handler registers as a side effect of
  importing its file. Forget that import — the most ordinary refactor there is — and the
  manifest keeps claiming the subscription while the module hears nothing: no error, no
  log line, just work that never happens. The event-bus registry now reports what it is
  listening for, and `create_app` refuses a claim nothing backs.

- **`backend/emitted_events_are_declared`** (Terp Standard 0.20.0) — a module emits only
  the events its `ModuleSpec` declares. The `emits` list is the module's published
  contract: what the control plane validates, what an operator reads, what another team
  subscribes against. An undeclared emit makes it quietly untrue — the event really does
  go out. Build-time only by recorded decision: an emit call carries no module identity,
  so only the source layout knows which manifest owed the declaration.

### Fixed

- **`terp guide events` names its own package.** The recipe used `EventEmittingService`
  and `LifecycleEventMap` without saying they live in a separate distribution; it now
  gives the line (`uv add terp-cap-eventbus`). It also shows the compliant *conditional*
  emit — the lifecycle map only answers "every write of this shape emits this event",
  and with no shape written down for a state transition the tempting move is to emit
  from a router or a task, outside the write's transaction. Extend `_after_write`, where
  the map already lives.

- **Coverage is measured from process start.** `pytest --cov` instruments after pytest
  has loaded its `pytest11` entry-point plugins, so the kernel imported by terp-core's
  new testing plugin ran untraced and the gate read 89 %. The gate now runs
  `coverage run -m pytest`, and the plugin keeps its own `terp.core` imports inside the
  fixtures so it is never the thing that forces the issue.

- **Pinned spec: 0.20.0**, which catalogs `emitted_events_are_declared`.

## 0.5.1 — 2026-07-30

### Fixed

- **`terp verify` reads the libc gate npm installs by.** The `node_modules` platform
  diagnosis matched a lockfile entry on `os` and `cpu` only. A Linux bundler ships a
  `-gnu` *and* a `-musl` binding for the same os/cpu and npm installs exactly one, so on
  a glibc container the musl packages read as absent and the diagnosis failed all three
  frontend checks on a perfectly healthy tree — before the real command ran, so it also
  hid whatever the truth was, and its prescribed `npm ci` could never clear it. An entry
  constrained to the other flavour is now absent by design, like any other
  foreign-platform entry. A check that cries wolf is worse than no check.

## 0.5.0 — 2026-07-30

Modules get a declared way to depend on each other, machines get a credential of their
own, and least privilege gets cheaper than widening a role. Three questions an app used
to answer by hand — "may this module import that one?", "is this caller a person?",
"how do I grant one permission?" — become platform answers with a check behind them.

### Added

- **A module may declare a dependency on a sibling** (ADR 0087). `ModuleSpec.requires`
  gains its second, larger meaning: the exhaustive list of siblings this module may
  import. An undeclared sibling import stays refused
  (`backend/no_cross_module_imports`); a declared one is allowed, but only into the
  dependency's public surface (`backend/cross_module_imports_use_public_surface`) and
  only if the graph stays acyclic (`backend/module_dependency_graph_is_acyclic`, also
  refused at boot). The alternative was what every real app does instead: a
  hand-rolled seam per edge, invisible to review.
- **A machine is a first-class subject kind** (ADR 0088). Service accounts get a signed
  `kind` claim and a client-credentials grant at `POST /token`, so which store answers
  a token is decided by what the credential *is* rather than by lookup order. Machine
  tokens are revocable on the same epoch mechanism as user sessions, and a credential
  carries an end date by default.
- **`terp grant`** (ADR 0089) — grant, list and revoke a permission by the name an
  operator already uses (an email, a service-account name), validated against the app's
  own catalog and written through the audited service. A grant below the permission's
  minimum role warns loudly instead of storing a row that can never fire.
- **`terp inspect capabilities`** — the adoptable-capability surface, marked with what
  this app already has and what one `uv add` would add. The registry is pinned against
  the real packages, so it cannot drift.
- **Declared request-scoped filters and sorts on `BaseService`** — a service names the
  columns a caller may narrow or order a read by, and the comparison each one permits.
  Anything undeclared is refused rather than ignored, and no filter can widen past the
  service's own scoping.
- **`backend/table_ownership_is_not_split`** (ADR 0090) — a table's model and the
  migration that creates it must live in the same package. Split them and per-package
  scoping hides the table from *both* histories, so drift detection goes quiet on a
  table nobody migrates.
- **`terp guide permissions`** — when to reach for a permission instead of a role.

### Fixed

- **`terp verify` names the cause when `node_modules` came from another platform.** The
  gate died with a raw Node stack naming neither cause nor fix; the lockfile already
  records which optional binary belongs on which platform, so the diagnosis is exact.
- **The production nginx `/api` upstream is substituted at start-up**, so one image
  serves both compose (service name) and a runtime that co-locates the containers in
  one pod (localhost).
- **The 100 % coverage bar is restored.** Coverage only ran in CI, so a batch of work
  accumulated 35 uncovered lines. Two of them turned out to be unreachable guards and
  were removed rather than pragma'd.

### Changed

- **Pinned spec: 0.19.0**, which catalogs the three dependency rules and the owning-package rule.
- **The advertised platform surface is drift-proof** — what the docs claim Terp offers
  is checked against what it ships.

## 0.4.0 — 2026-07-29

A wrong database schema stops being a silent failure. A migration history that was
rewritten rather than extended is refused at build time, a database holding a revision
the code no longer defines is refused at boot, and every generated app gets that boot
guard instead of only the example app.

### Added

- **`backend/migration_history_is_intact`** — a migration history must be one unbroken
  chain from a single first revision, with every revision reachable from it. A deleted
  or renamed parent, a second baseline, and a closed cycle each strand every database
  that applied the old chain, while a database rebuilt from the rewritten history stays
  perfectly consistent with the models — so no drift check can see it.
- **`assert_no_orphaned_revisions`** — the runtime half: an app refuses to serve against
  a database holding a revision the code no longer defines, and reports that distinctly
  from "behind on migrations", because the two need opposite fixes.

### Fixed

- **Generated apps install the migration boot guard.** `migration_check` was wired into
  the example app only, so a rendered project served against a wrong schema until the
  first request that touched the affected table.
- **`terp check` is scoped to the app package** instead of also walking vendored and
  tooling directories.
- **Generated projects pin LF line endings.** On a Windows checkout Git rewrote every
  container-written file to CRLF, turning a real 281/7 change into a 948/674 commit and
  defeating review-by-diff and `git blame`.
- **Self-naming enum members are no longer flagged as hardcoded credentials.**

### Changed

- **Pinned spec: 0.18.0**, whose migration-history rule requires a real baseline.
- **One vitest major across the whole workspace**, and the high-severity frontend
  advisories are cleared.

## 0.3.0 — 2026-07-27

The Terp Standard becomes a dependency you install rather than a repository you
clone, and the deep-import rule starts guarding the scope the packages are
actually published under.

### Fixed

- **`frontend/no-deep-imports` refuses the published scope.** The rule only ever
  matched `@terp/*/src/*` and `@terp/*/dist/*`, so from the moment the frontend
  packages were renamed to `@terpjs/*` an
  `import x from "@terpjs/react-core/src/…"` walked straight past the one rule
  meant to stop it. Deep imports of the published packages are refused again.

### Changed

- **The Terp Standard is consumed as a published package** (ADR 0086). The
  backend resolves `terp-spec` from PyPI and the boundary lint resolves
  `@terpjs/spec` from npm, both pinned by version instead of a git tag — no
  `[tool.uv.sources]` entry and no `github:` dependency. `test_repo_split_readiness`
  now proves both lockfiles resolved the pinned release from a registry, and
  the two ecosystems may not drift apart.
- **Pinned spec: 0.16.0**, which records every rule's enforcing tool under the
  `@terpjs/*` scope the packages publish under.

## 0.2.0 — 2026-07-27

Second release: the enforcement harness grows fifteen rules, and the frontend
stops leaking the host's chrome and locale into a themed app.

### Added

- **Fifteen new architecture rules in `terp.arch`**, each catalog-attributed to the
  Terp Standard and each shipping its `uv run terp guide <rule>` fix recipe:
  - *Time* — `no_naive_datetime` (a naive `datetime` is a silent bug in a
    multi-region app) and `datetime_columns_are_timezone_aware` (a column that
    drops the offset loses the fact permanently).
  - *Optimistic concurrency* — `update_schemas_inherit_base_update_schema` and
    `no_manual_version_assignment`, closing the two ways an app can bypass the
    lost-update guard.
  - *Query correctness* — `offset_queries_declare_ordering` (an unordered
    `OFFSET` silently repeats and skips rows across pages) and
    `path_id_params_are_uuid`.
  - *Migrations* — `alembic_downgrades_not_empty`, so a downgrade path is real
    rather than a stub that pretends to roll back.
  - *Source hygiene* — `no_print`, `no_star_imports`, `no_eval_or_exec`,
    `no_blocking_sleep`, `no_mutable_default_args`, `no_todo_fixme`,
    `no_empty_tests` and `no_oversized_python_files`.

### Changed

- **Terp Standard pinned to v0.14.0** (from v0.13.0) in both consumers — the
  `terp-spec` distribution and `@terpjs/eslint-boundaries` — with the
  `SPEC_VERSION` constants moved in lockstep.
- **npm publishing now uses Trusted Publishing (OIDC)**; the long-lived
  `NPM_TOKEN` secret is gone from the release pipeline.

### Fixed

- **Native browser chrome now follows the token palette.** `color-scheme` is
  declared for both themes, so the `<select>` option popup, natively-drawn
  scrollbars and text carets stop rendering light chrome inside a dark app;
  scrollbars are themed to match.
- **Rows-per-page is a themed menu, not a native `<select>`** — the one control
  in `DataView` that still opened OS-drawn chrome.
- **A stray horizontal scrollbar in `DataViewTable`**, caused by the column
  resize handle being offset past the table's own edge.

### Upgrading from 0.1.0

The fifteen new rules apply to your app the moment you bump. Expect
`uv run terp check` to report findings that 0.1.0 never looked for — each names
the file, the line and the fix recipe. Under 0.x this ships as a minor bump, but
budget it as real migration work rather than a drop-in upgrade.

## 0.1.0 — 2026-07-23

First tagged release of the platform: the secure-by-default backend kernel
(`terp.core`), the base-profile + opt-in capabilities, the `terp.arch` enforcement
harness, the `terp` CLI, packaged per-package Alembic migrations, the frontend contract
(`@terp/contract`) and the first frontend stack (`@terp/react-core` + boundary lint +
conformance suite), the copier client template, the Docker dev workbench, and the
production deployment profile (multi-stage wheel images + hardened compose profile +
`docs/DEPLOYMENT.md`). See ADRs 0001–0082, including the new `terp-cap-redis` shared-store adapters for Redis-backed idempotency, throttling, and cache state.

Late additions on that line:

- **Background jobs preserve row ownership.** The ownership architecture rule
  now rejects a job-bearing app module whose declared CRUD service model omits
  `OwnedMixin`, and `create_app` refuses the same shape at composition. A system
  actor remains an audit identity, not blanket cross-owner maintenance authority;
  such workflows stop for a reviewed maintenance capability instead of deleting
  the owner gate.
- **Centralized first-run frontend design system.** `@terp/react-core` now owns
  stable control typography and intrinsic button sizing, icon-only themed
  preference menus, body-portaled/clamped overlays, normalized number inputs,
  compact page headers, equal-track `HubCard`s, and record-labelled DataView
  navigation. `AppShell` now has a home-linked brand, fixed-size collapsed icon
  slots, a scrollbar-free rail, and a scroll-locked/focus-contained mobile
  drawer; its `renderLink` receives an additive third context argument with the
  framework-owned expanded/collapsed styles (existing two-argument callbacks
  remain valid), and `renderBrandLink` is optional. Packaged users/groups admin
  now follows overview -> dedicated create/detail routes with breadcrumbs,
  page actions and confirmation-gated destructive changes. Nested `HubPage`s
  accept `parents`; the inherited `breadcrumbs` prop remains a compatibility
  alias.
- **`terp verify` — the one-command gate over declared profiles.** The project's
  whole verification surface as data: `--profile quick` (static enforcement:
  architecture gate, boundary lint, typecheck), `full` (the merge bar: + backend
  tests, the delegated AppSec baseline, the production build — exactly the
  template CI's blocking checks), `release` (+ API-docs drift, black-box
  conformance). `--list` prints the manifest a driving tool configures its gate
  from (id, category, command, input scope per check); `--only <check>` runs a
  subset (the change-scoped rerun seam); `--format json` emits the `terp_verify`
  envelope with every Terp Standard check report the checks published carried
  structurally.
- **Check reports (Terp Standard v0.7.0, `app-check-report.schema.json`).**
  `terp check --format check-report` and `terp-boundaries-lint --format
  check-report` emit the spec's self-describing check report — the certified
  `spec_version`, the checker identity, the run verdict, the evaluated-rule
  inventory as catalog ids, and findings in the finding format's shape
  (`fix_hint` = the `terp guide` recipe) — so a consumer joins per-rule verdicts
  to the catalog through one contract on both surfaces. The legacy
  `--format json` report and `terp_findings` envelope keep their published
  shapes; the certified spec version is a build-time constant
  (`terp.arch.SPEC_VERSION`, `SPEC_VERSION` in `@terp/eslint-boundaries`) held
  equal to the pinned spec release by the framework gate.
- **App-declared environment variables.** Every app ships an
  `environment.schema.json` manifest (empty by default) declaring the run-time
  variables it reads beyond the platform-owned set; both compose profiles
  forward the declared keys through one optional `env_file` seam (`.app.env`,
  `required: false`, gitignored/dockerignored). Deploy pipelines render exactly
  the declared keys — undeclared variables stay impossible, secret-marked ones
  stay out of plain records. Guarded by `test_prod_profile.py` /
  `test_compose_workbench.py`.
- **Per-rule verdicts are joinable to the Terp Standard (ADR 0083).**
  `terp check --format json` now publishes `rules` — the evaluated-rule
  inventory that matches the execution mode (the live registry; the budget
  ratchet only when a budget was supplied) — so a driving tool (the Studio's
  spec matrix) can join verdicts to catalog ids without ever claiming "pass"
  for a rule the pinned toolchain never ran. On the frontend, the new
  `terp-boundaries-lint` bin (the analog of `terp check --format json`)
  replaces the `eslint . && terp-boundaries-budget` chain: it runs the app's
  own ESLint config **and** the escape-hatch budget ratchet in one command
  (both halves always run — drift can no longer hide behind a failing lint)
  and publishes one findings envelope on stdout — the evaluated inventory
  (`catalogRuleIds()`), a `not_applicable` list for opt-in rules the app has
  not enabled (`frontend/layout-contract` without a checked-in
  `layout-contract.json`), findings attributed to stack-neutral catalog ids
  via `catalogRuleId` (budget drift as `frontend/escape-hatch`), and an
  `unattributed` bucket that is surfaced, never dropped — while the human
  report stays on stderr. `terp-boundaries-budget --format json` emits the
  same envelope standalone. The template and example lint script is now
  `terp-boundaries-lint`.

- **The two-layer doctrine is classified per rule (ADR 0084, Terp Standard
  v0.5.0).** Every catalog entry now carries a mandatory, machine-checked
  `runtime.applicability` (`required` / `not-applicable` / `deferred`): 21
  rules declare their fail-closed runtime control (15 controls that already
  existed — the write-chokepoint strip, the session re-scope, the boot
  validators, the catalog chokepoints — are now *declared* instead of
  folklore), 31 source-form rules are exempt with per-rule rationales, and 6
  known seam gaps are explicit `deferred` entries (including pagination and
  the missing-migration-history case, whose previously declared "runtime
  halves" did not actually refuse those violations). Tests fail closed on a
  missing, contradictory, or unresolvable classification, and the blanket
  "every rule has a runtime half" wording is retired from the platform docs.
  The spec repository's CI gains a `certify-against-reference` job that runs
  this repo's parity + corpus certification against every candidate spec
  change, closing the pinned-release adoption gap from the other side.

- **The Terp Standard's AppSec scope is explicit and the generic baseline is
  enforced (ADR 0085).** The catalog claims Terp-specific secure-architecture
  rules, not complete application security: generic vulnerability classes a
  stock analyzer detects well (command injection, unsafe deserialization,
  weak crypto randomness) are delegated to the mandatory ruff-bandit (`S`)
  baseline the platform repo already runs — and generated projects now
  inherit it (template `pyproject.toml` config + blocking CI step + an
  in-project ratchet that parses the stanza and pins the CI step), with
  `tests/guardrails/test_appsec_baseline.py` holding the delegation in place
  fail-closed and the template-acceptance job running the baseline on
  rendered output. Classes no stock analyzer detects (path traversal,
  secrets in logs, browser-storage auth material) stay addressed
  constructively, never claimed as detected. Baseline findings stay
  tool-attributed, never mapped to catalog ids.
