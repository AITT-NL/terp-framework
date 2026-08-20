# Changelog

All notable changes to the Terp platform. Terp releases **in lockstep**: every backend
distribution (`terp-core`, `terp-arch`, `terp-cli`, `terp-migrations`, `terp-cap-*`) and
every frontend package (`@terpjs/contract`, `@terpjs/react-core`,
`@terpjs/eslint-boundaries`, `@terpjs/conformance`) carries the same version and
publishes from the same tag
(`v<version>`); the gate enforces the lockstep (`tests/architecture/test_release_versions.py`).

The full rationale trail lives in [docs/decisions/](docs/decisions/) — one ADR per
decision, 0001 onwards.

## 0.8.0 — 2026-08-18

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
