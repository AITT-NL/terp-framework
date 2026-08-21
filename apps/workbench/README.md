# @terpjs/workbench

Every component `@terpjs/react-core` ships, in every variant it has, in every theme, on one
page — plus the visual baselines taken from it.

Private and never published. It exists because two things were missing: a catalog (the
react-core README lists components in prose, so "what does this look like, and what states
does it have" had no answer short of reading the source), and a way to *see* a styling change
(the package ships no runnable surface, so a token or component edit was reviewed by reading
a diff).

```bash
npm run dev        # the workbench at http://localhost:5175
npm run visual     # all four lanes at once — see the flake note before trusting a red run
npm run visual:screens  # one lane at a time, which is what CI does and what is reliable
npm run visual:a11y
npm run visual:keyboard
npm run visual:computed
npm run visual:update   # re-record the screenshots, after an intended change
npm run typecheck
```

`npm run visual` is the convenient command and **not** the trustworthy one on a busy
machine: it starts all four lanes in one Playwright process, which is itself the
contention condition described under "No retries" below. CI never runs it — the workflow
runs the four lanes as four separate steps. Reach for the per-lane scripts when a result
has to mean something.

87 specimens in 8 groups. The accessibility lane runs them in **every** shipped theme (435
axe runs across five palettes); the screenshots cover the **two default** themes (174
comparisons) — see "Which themes get which lane" below. Plus one check that every specimen is
present exactly once, one that the contrast allowance list has not grown a new theme, one that
the CI image tag still names the Playwright version in `package-lock.json`, a three-test
keyboard lane for where a keystroke sends focus, and a four-test computed lane for the
resolved values none of the other three can see. **619 checks.**

Nothing derives those numbers, so they are only as good as the last person to add a specimen:
`5N` axe runs, `2N` screenshots, three standalone checks (presence, theme allowance, image
tag), three keyboard tests and four computed ones — at N=87, 435 + 174 + 3 + 3 + 4.

One of those 87 earns a note, because it is the only specimen whose subject is a token
rather than a component: `dataview-compact`. Comfortable density is the token sheet's
`:root` value, so every other DataView specimen renders identical geometry whether the
density tokens are read or hardcoded — which is exactly how four of them came to be
published with no reader at all. Stamping `data-density="compact"` is what makes them
observable: the compact view comes out 36px shorter than `dataview-full`, 32 of that from
cell padding and 4 from the search input's control height, which no DataView rule sets.

## The keyboard lane

`visual/keyboard.spec.ts`, and it is deliberately tiny. The screenshots capture the resting
state and axe reads a static tree, so neither says anything about where focus GOES when a key is
pressed — and stage 4 found two defects of exactly that shape while migrating overlays: a
calendar cursor that moved `tabIndex` without moving DOM focus, and a menu whose Tab handler
closed the panel while leaving focus on the node it was about to unmount.

One of those two cannot be gated by a unit test at all, which is why this is a browser lane
rather than more jsdom. The repaired calendar was still wrong across a month boundary, because
that move re-keys the week rows and unmounts the focused cell — and the browser then moves focus
to `<body>`, while jsdom leaves it on the detached node. The same unit test passes against the
bug and against the fix; measured both ways before this file existed.

It holds cases where a keystroke's effect on focus IS the contract, and nothing else. Anything
about appearance belongs in a baseline; anything about the static tree belongs to axe.

## The computed lane

`visual/computed.spec.ts`, and it exists because of a blind spot in the sentence above. "Anything
about appearance belongs in a baseline" is only true of appearance a baseline can *see*, and this
config sets `animations: "disabled"` — deliberately, so the spinner keyframes do not make every
run differ. The cost of that, which was not written down anywhere until now: **every duration and
easing in the sheet is invisible to the screenshot lane.** A transition at 150ms, at 400ms, or
gone entirely produces byte-identical baselines. axe reads a static tree and says nothing about
computed style either.

Phase 4 walked straight into it. Wiring the published motion scale into the sheet replaced 29
literal `150ms ease` / `100ms ease` pairs with `var()` reads, and a `var()` inside a shorthand
fails in one specific way: if the substitution is invalid, the whole declaration becomes invalid
at computed-value time and falls back to the property's **initial** value — `transition: all 0s
ease 0s`. Every element still paints identically at rest, every baseline still passes, axe still
finds nothing, and every transition in the package is silently dead. A structural test over the
sheet proves it *names* a token; only reading what the browser resolved can tell the difference.
Verified both ways before this file was trusted: a typo'd token name resolves
`transition-property` to `all`, and the lane fails on that assertion rather than on the number,
which is why the number is not the only thing asserted.

Its reduced-motion test gates a measurement the sheet had only claimed. That block's comment
says "measured, not assumed: under `prefers-reduced-motion` the sidebar, a nav link and a hub
card title all compute `transition-duration` 0s" — and nothing checked it. The three shapes
matter: `[data-terp]` reaches a marked element, while a nav link and a breadcrumb link are bare
`<a>`s that the block reaches only through selectors of their own. Reduced motion had already
been silently ignored once for exactly that reason.

Its third test is the honest half of `scrollbar-gutter: stable`, and it is worth reading before
writing anything else here, because the obvious version of it is vacuous and looks fine.
**This Chromium reserves no layout space for the viewport scrollbar at all.** With the
declaration removed, a solo specimen page and the many-screens-tall catalog both report a root
box of 1280 in a 1280 viewport, and the specimen card comes out at 1232 on both — so there is
no sideways jump in this browser to prevent, and an assertion that the two page shapes agree
passes identically before and after. It measures the browser, not the sheet. What is checkable
is the reservation itself: with the declaration the root box is 1270 on both shapes. The "no
jump" property is left to the browsers that take scrollbar space, which is most desktop Chrome
and Firefox on Windows and Linux — the users, just not the lane.

Two traps that cost time there, recorded so they cost it once. `documentElement.clientWidth`
cannot see any of this: for the root element it reports the viewport, so it reads 1280 whether
or not a gutter is reserved. Use `getBoundingClientRect()`. And making the harness model a
space-taking scrollbar is possible — Chromium takes a flag — and is deliberately not done,
because it would also give every **inner** scroll container a space-taking bar, starting with
the DataView's horizontal overflow, which is a change to component layout wearing a harness
change's clothes.

Its fourth test reads the three button cursors, which are the plainest case of a declaration no
lane can see: Playwright does not paint a pointer into a screenshot and axe does not read one,
so `cursor: pointer`, `not-allowed` and `progress` had no gate of any kind. The pair worth
checking is the last two. A loading button IS disabled — the component sets both — and the
disabled rule lives in `terp.state`, so a `data-loading` rule in `terp.base` loses on layer
order and the cursor silently stays `not-allowed`: it tells a user "you may not" where the truth
is "not yet". Verified by moving the rule into `terp.base`, where the resolved value comes back
`not-allowed` and both this lane and `styles.test.ts` fail.

Same scoping discipline as the keyboard lane: cases where the **resolved value** is the contract,
and nothing else.

## Why it is not inside react-core

`@terpjs/react-core` sets no `files` field, so npm packs everything in its directory — a
workbench living there would ship to every consumer. Keeping it outside also means it imports
react-core *by package name*, exactly as an app does, so it exercises the public export
surface rather than reaching into `src/`. Three of the first specimens written here failed to
typecheck against the real component props, which is the surface doing its job.

## Adding a specimen

Add an entry to `SPECIMEN_GROUPS` in `src/specimens.tsx`. The page and the visual suite both
render from that list, so there is nothing else to wire — a new entry gets a section on the
page, a baseline in each default theme, and an axe run in every theme.

Three rules, because both consumers depend on them:

- **Deterministic.** No `Date.now()`, no random ids, no live data. A specimen that renders
  differently on two runs makes its baseline worthless and trains people to re-record.
- **Controlled, not interactive.** Render stateful controls at a fixed value, so the shot is
  the state named in the title. Interaction belongs in an e2e suite.
- **One concern per specimen.** `button-variants` and `button-disabled` are separate so a
  disabled-state change cannot mask a variant change inside one baseline.

And two flags, both of which change how the lanes capture a specimen and both of which keep
it off the catalog page. `overlay: true` for a specimen that renders something open — see
"Overlays paint outside their box" below. And `viewport: { width, height }` for one whose
subject only exists at a width the pinned 1280x900 is not — see "A viewport of its own".

## How the visual suite is kept honest

**One screenshot per specimen, not per page.** A page-sized baseline is the obvious thing to
write and the wrong thing to have: any change anywhere re-records it, so the diff never names
a component and reviewers learn to accept the update. Per-specimen shots mean a `Card`
padding change fails `card-titled` and `card-bare` in both themes and nothing else.

**And one specimen per render, because clipping is not isolation.** Screenshotting one
element out of a full catalog page looks like it delivers the paragraph above, and does not.
A specimen sits wherever the specimens above it leave it, and that offset is usually
fractional — `text-inputs` sat at `y=2186.890625`. The fractional part decides the subpixel
phase every 1px border and glyph inside that box is rasterised at, so **adding a specimen
anywhere above re-records unrelated baselines below.** Measured, not inferred: adding fifteen
specimens moved `text-inputs` to `y=2457.703125` and repainted 4846 of its pixels, moved
`app-shell` and repainted 15222, and left `button-variants` — sitting at an integer `y=168` —
untouched. Six baselines changed for a change to none of their components.

That is the per-specimen promise failing in precisely the situation it exists for, and it
fails toward the same habit the pinned threshold exists to prevent: a reviewer who sees six
unrelated baselines move alongside a new specimen learns to accept baseline updates
wholesale. So the visual suite navigates to `?only=<id>`, which renders that specimen alone
at a fixed origin. Each test already did its own navigation, so this costs nothing, and a
specimen's baseline now depends on that specimen and nothing else. Verified by mutation both
ways: inserting a specimen above everything now changes no other baseline, and the
one-Tailwind-step token check below still fails the specimens it should.

Both lanes navigate that way. The a11y lane did keep loading the whole catalog for a while,
which cost it 250 full-page renders per run and eventually started timing out under parallel
load — a failure that reads as an accessibility violation and is a cold page. axe measures the
same thing either way, because the solo page reuses the same background and specimen card and
the run is scoped to one specimen regardless.

The bare address still renders the whole catalog. That is what a human opens, and what the
"every specimen is present exactly once" check reads.

## Overlays paint outside their box

Four framework surfaces are invisible to a per-specimen lane by default, and each escapes by a
different mechanism. `Popover` portals its panel to `document.body`, so the panel is not even a
descendant of the specimen. `ConfirmDialog` opens a native `<dialog>` with `showModal()`, which
renders in the top layer. The toast viewport is `position: fixed` at the corner of the screen.
And the plainest case is the one a maintainer is most likely to miss: an anchored panel that is
merely `position: absolute` inside the specimen — the `Combobox` listbox — still paints past the
element's bounding box, so it needs the flag exactly as much as a portal does. The screenshot lane clips to the specimen element's bounding box and the axe lane
scopes to it with `.include()`, so for all three the shot comes out as the trigger with nothing
next to it — and for `ConfirmDialog` as a *dimmed empty card*, because the `::backdrop` covers
the clip while the dialog does not. That is worse than having no specimen, because it looks
like coverage.

`overlay: true` changes three things:

- **The screenshot becomes a viewport shot** rather than an element shot. Nothing is lost:
  `?only=` has already reduced the page to one specimen at one fixed origin, and the viewport
  is pinned at 1280×900 with `deviceScaleFactor: 1`, so the baseline still depends on this
  specimen and nothing else. The per-specimen promise is kept by the address rather than by the
  clip.
- **axe widens from the specimen element to `body`**, which is where the portalled panel
  actually lives. `body` and not the whole page on purpose, so the document-level rules
  (`html-has-lang`, `document-title`) stay out — they belong to this app's shell, and the lane
  is a gate on react-core.
- **The catalog page shows a link instead of the node.** An open `ConfirmDialog` locks
  `document.body` scroll and makes every other specimen inert, and that page is both what a
  person browses and what the "every specimen is present exactly once" check reads. Open menus
  would also fight over focus, since a `Menu` moves focus to its first item on mount. The card
  and its `data-specimen` handle stay, so the presence check still counts it.

Verified by mutation, and by the half that matters: an unlabelled `<img>` placed inside the
portalled `Popover` panel is a real `image-alt` failure at WCAG 2.0 A, and the element-scoped
run reports **zero violations** for it in all five themes while the `body`-scoped run fails all
five. The widening is not tidiness; without it an open-panel specimen is a green run that
examined the trigger.

One sensitivity these specimens inherit rather than introduce: an open calendar renders a whole
month, so its baseline depends on the recording machine's timezone in the same way the closed
trigger's formatted date already did. Within one platform's baseline set that is stable, which
is the same footing the rest of the set stands on.

**The theme is in the URL.** The page reads `?theme=<name>` and sets `data-theme` on
`<html>` directly rather than going through `ThemeProvider`, which persists to
`localStorage` — a toggled theme would leak between runs and make a baseline depend on run
order. An address that fully determines the render is the whole trick. The theme names come
from the contract's published token manifest (`src/themes.ts`), so a theme added there is
renderable here with no edit to this app.

Two of them earn a different note, about what a MISSING specimen costs. The card layout
had none — the switch is internal state, driven by a media query at 768px or a toolbar
click, and the viewport is pinned at 1280 — so a pairing it renders had never been
measured by anything. The first card specimen failed `color-contrast` immediately, on
muted card text over a status-toned card, a defect that had shipped since the layout
existed. Note what axe could and could not do with it: it named **one** of the four
theme/tone combinations that fail, because a specimen renders two tones and the other
two failures live in tones it does not paint. Fixing what axe named would have left
three real failures standing. So the sub-components are rendered directly, at fixed
props — they are all exported — rather than by growing test-only props on `DataView`.

**Six specimens sit behind the auth seam** — four components' worth (`UserMenu`,
`ProfileView`, `ResourceList`'s write gate, `LoginView`), with `UserMenu` and `ResourceList`
contributing two each. They mount a `TerpProvider` against the dev server, whose
`workbench-mock-auth` middleware (`vite.config.ts`) answers the boot refresh and `/me` with
one fixed administrator — the determinism rule applied to the session, so these render
identically on every run with no backend. `ModuleNav` is the one component that needs a
router (it reads the live pathname to mark the active tab); its specimen supplies a memory
router pinned to one path, which is also what puts the active state in the picture.

## A viewport of its own

The config pins the viewport at 1280x900 so a baseline cannot depend on a window size. That is
right, and it also puts a whole class of declaration out of reach of both lanes: anything that
only applies at a width the pin is not. `styles.test.ts` said so about the shell in as many
words — the mobile variant needs 768 or less, the sidebar's `flex-shrink` bites only between
the breakpoint and wide — and asserted those rules as **text**, because "no baseline can hold
it" was true.

`viewport: { width, height }` on a specimen holds them. The per-specimen promise is untouched,
because the size is declared next to the node rather than being a property of the machine or
the run, and Playwright gives each test its own context so one specimen's viewport cannot leak
into another's. Verified: adding the first two viewport specimens left all 164 existing
baselines byte-identical.

Two of them exist now, and both were confirmed to paint their subject rather than assumed to:

- `app-shell-mobile` at 420x900 — the shell below its own breakpoint, drawer closed, which is
  the first picture of the mobile variant anywhere. Moving `appshell-main`'s tightened padding
  one step to the desktop value repaints 1,309 pixels here, in both themes, and nothing else.
- `app-shell-narrow` at 820x900 — the band just above the breakpoint, where the sidebar's
  `flex-shrink: 0` is the only thing keeping the rail at 15rem. Removing it repaints 124,797
  pixels here and leaves the other three shell specimens untouched.

The second one carries a lesson worth keeping: a narrower window was **not enough**. A flex row
under no pressure never asks an item whether it may shrink, so the specimen needs content with
a real min-content width — it renders a wide `DataView` — and with a short paragraph instead it
would have been a green baseline over an unexercised declaration, which is the shape this whole
file exists to distrust.

Like `overlay`, a viewport specimen renders a link on the catalog page instead of its node. At
the catalog's width the render would be the *wrong* composition under a title announcing the
right one, and a reader takes a picture at its word.

What a viewport cannot fix, and it is worth knowing before reaching for one: the mobile drawer's
own geometry and its backdrop are still text-only assertions, because on mobile the sidebar
renders only while the drawer is **open** and `drawerOpen` is internal state with no way in —
the same wall `defaultCollapsed` was added to get past for the icon rail, where four rules had
shipped unpainted behind it.

## Which themes get which lane

The two lanes cover different theme sets on purpose, and the asymmetry is the point.

**axe runs in every theme.** A new palette is exactly where an undeclared foreground/background
pairing goes wrong, and the static gate in `@terpjs/contract` can only measure pairings someone
thought to declare. This lane earned that scope immediately: it found five real defects in the
themes added in Phase 2c that the static gate could not see — the accent used as *text* on a
surface (selected tabs, active nav, the spinner) and `--color-neutral-500` as muted copy. Both
were fixed in the palettes rather than recorded as allowances.

**Screenshots cover the base theme and the OS-dark theme only** — what an app renders when
nobody chooses. Named themes differ from those in colour values alone; markup and geometry are
identical. A third, fourth and fifth set of per-specimen shots would therefore re-prove the
geometry the first two already prove, while tripling what a reviewer has to accept for a
one-line padding change — the same argument that made these shots per-specimen instead of
per-page. Widening it is a one-word change in `src/themes.ts` if Phase 3 turns out to need
per-theme geometry evidence.

**No retries.** A visual test that passes on retry is a flaky baseline, and hiding that behind
a retry is how a suite stops being evidence. Which means a flake has to be treated as a defect in
the harness, and one is on record: at 285 axe runs under eight parallel workers, three
contrast-theme input specimens failed `color-contrast` together on one full run, and all three
passed in isolation and on the next full run. axe resolves the computed foreground and background
of what the browser actually painted, so until layout and text rendering have finished it is
measuring a moving target — and the way that surfaces is a contrast violation on a specimen whose
colours are fine. The axe lane now awaits `document.fonts.ready` before analysing, which the
screenshot lane had always done and this one had not. Stated honestly: a flake that does not
reproduce cannot be shown to be fixed. If it returns, that asymmetry is no longer the explanation
and the next thing to suspect is the worker count.

It returned, and the worker count is the explanation. Recording it because the paragraph above
asked for exactly this and could not supply it: the flake now has a **reproducible trigger**.
Running the win32 suite and the linux suite at the same time on one 8-core machine — each
Playwright picking its own default of half the cores, so sixteen browser workers and two dev
servers over eight cores — failed `color-contrast` on four light-theme specimens together
(`actions/button-variants`, `actions/button-disabled`, `actions/button-with-icon`,
`actions/popover`). The same lane, in the same container, on the same commit, run alone: **391
passed**. Nothing in the palettes changed between the two runs.

So the shape is confirmed and the earlier diagnosis stands — axe measures what the browser has
painted so far, and a machine too busy to finish painting yields a contrast reading for a
specimen whose colours are fine. `document.fonts.ready` narrowed the window; it cannot close it,
because fonts being loaded is not the same as layout being settled. Two consequences worth
carrying: a red `color-contrast` result is only evidence when the lane had the machine to
itself, and the rule against running the Python suite and a browser lane together is really a
rule against running a browser lane beside **anything** heavy, including another browser lane.
Neither is a reason to add retries — a lane that needs a retry to pass is not evidence, and the
fix here is scheduling rather than tolerance.

It returned a third time, and the trigger is narrower than "two suites": **one** bare
`npx playwright test` is enough. That command runs every lane in a single Playwright
process — 619 tests over eight workers, the screenshot lane's dev server and page loads
competing with the axe lane's — and it failed `color-contrast` on three twilight specimens
together (`chrome/page-loading`, `chrome/page-error`, `chrome/hub-card-bare`). The axe lane
alone, same commit: all 81 twilight runs passed. The *identical* full command, run again:
573 passed. Same shape as before, one worker pool rather than two.

Which makes the scheduling rule concrete rather than advisory, and it had been missing its
commands: CI already runs the lanes as separate steps, so it never meets this
condition, while the README's own headline command did. There are per-lane scripts now.
A rule with no command behind it is only obeyable by remembering it.

**Baselines are split by platform** (`visual/__screenshots__/<platform>/`). Font
rasterisation and antialiasing differ between Windows and Linux by far more than any
tolerance that would still catch a real change, so a single shared set leaves whichever
platform did not record it permanently red. Each platform records and compares its own.

Both sets are recorded, so all four lanes run in CI (`.github/workflows/frontend.yml`).
The `win32` set comes from a developer machine; the `linux` set was recorded in
`mcr.microsoft.com/playwright:v1.62.0-noble`, and CI runs the screenshot lane **inside that
same image** rather than on the bare runner. That last part is the load-bearing half: a
GitHub runner shares Ubuntu's kernel with the image but not its font packages, and fonts are
the entire reason the sets are split in the first place. Comparing in the environment that
recorded is what makes the lane reproducible instead of hopeful.

The image tag tracks the Playwright version pinned in `package-lock.json`. Bumping one
without the other records against one browser build and compares against another, which
shows up as every baseline failing at once — a symptom worth recognising, because the
instinct it provokes is to re-record, and re-recording would bury the mismatch.

Before this, only `win32` was recorded and the lane was local-only, so a component
migration's zero-diff evidence was something a human produced on one machine. Phase 3's
fifty commits were gated that way; the `linux` set is what turns the same claim into
something CI can make.

**Two comparison knobs, both pinned.** `threshold` decides whether a single pixel counts as
different at all — a normalised YIQ colour distance — and `maxDiffPixels` decides how many
counted pixels are tolerable. They are not interchangeable, and pinning one while inheriting
the other is how this gate went blind for a while: only the pixel allowance was set, so
Playwright's default `threshold: 0.2` applied, and a status token moving one Tailwind step
(`#16a34a` → `#15803d`) produced **zero** differing pixels. Every baseline passed a change that
visibly repaints every badge in every app. Phase 2d found it by repainting ten specimens and
being told nothing had moved.

Now `threshold: 0.02` with `maxDiffPixels: 0`. Zero-tolerance is viable because within one
platform the render is deterministic — verified over three consecutive runs — and cross-platform
drift is already handled by separate baseline sets rather than by a tolerance.

Verified by mutation rather than assumed, and note what the *earlier* mutation missed: swapping
`--color-brand-primary` from `#2563eb` to `#dc2626` fails `light-button-variants` on 2679 pixels,
but blue-to-red clears a 0.2 threshold easily, so it only ever proved the gate catches *large*
changes. The check that matters is the small one: reverting the light success token by a single
Tailwind step now fails `badge-tones`, `alert-tones` and `detail-list`, and under the old
settings failed nothing at all.

## Accessibility

`visual/a11y.spec.ts` runs axe over every specimen in every shipped theme at WCAG 2.0/2.1 A
and AA —
realising the `a11y` lane the Terp Standard recommends and nothing implemented. Scoped per
specimen for the same reason the screenshots are: a page-wide run produces a list of
violations with no owner, and the first thing anyone does with an unattributed list is stop
reading it.

Every rule is held at zero, `color-contrast` included: `KNOWN_CONTRAST_FAILURES` is `[]` and
has been since 0.7.0 emptied it, as has `BELOW_AA` in `tokens.contrast.test.js`. The list
remains in the file as a shrink-only ratchet, and a companion test refuses to let a theme
added after the lane existed record an allowance at all — so the empty list is enforced, not
merely current.

The two lanes measure the same pairings from different ends, which is corroboration rather
than duplication, and axe reaches further: when the lists were last non-empty the static gate
named five pairings and axe found them in nine specimens, because every specimen containing a
primary button failed in dark and every one containing a `Badge` failed in light.

Writing this found a defect in the workbench rather than the framework: three specimens
rendered `Input`, `Select` and `Textarea` bare, with no accessible name, which is a genuine
WCAG failure. `field-states` passed throughout, because a `Field` supplies the name — so the
suite was right and the specimens were wrong. They now carry `aria-label`.

## Running the browser on a locked-down Windows machine

If `npm run visual` fails with `browserType.launch: spawn UNKNOWN`, the Playwright browsers
are installed under `%LOCALAPPDATA%\ms-playwright` and local policy is refusing to execute
them from there. The binary is present and complete; it simply cannot be spawned. Install them
somewhere policy allows and point Playwright at it:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "<a path outside AppData>"
npx playwright install chromium
```

Linux CI is unaffected and needs none of this.
