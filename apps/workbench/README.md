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
npm run visual     # screenshots + axe, against the committed baselines
npm run visual:update   # re-record the screenshots, after an intended change
npm run typecheck
```

57 specimens in 8 groups. The accessibility lane runs them in **every** shipped theme (285
axe runs across five palettes); the screenshots cover the **two default** themes (114
comparisons) — see "Which themes get which lane" below. Plus one check that every specimen is
present exactly once, and one that the contrast allowance list has not grown a new theme.

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

And one flag, for the specimens that render something open: `overlay: true`. See "Overlays
paint outside their box" below — it changes how both lanes capture the specimen, and keeps it
off the catalog page.

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

Three framework surfaces are invisible to a per-specimen lane by default, and each escapes by
a different mechanism. `Popover` portals its panel to `document.body`, so the panel is not even
a descendant of the specimen. `ConfirmDialog` opens a native `<dialog>` with `showModal()`,
which renders in the top layer. The toast viewport is `position: fixed` at the corner of the
screen. The screenshot lane clips to the specimen element's bounding box and the axe lane
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

**Six specimens sit behind the auth seam** — four components' worth (`UserMenu`,
`ProfileView`, `ResourceList`'s write gate, `LoginView`), with `UserMenu` and `ResourceList`
contributing two each. They mount a `TerpProvider` against the dev server, whose
`workbench-mock-auth` middleware (`vite.config.ts`) answers the boot refresh and `/me` with
one fixed administrator — the determinism rule applied to the session, so these render
identically on every run with no backend. `ModuleNav` is the one component that needs a
router (it reads the live pathname to mark the active tab); its specimen supplies a memory
router pinned to one path, which is also what puts the active state in the picture.

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
a retry is how a suite stops being evidence.

**Baselines are split by platform** (`visual/__screenshots__/<platform>/`). Font
rasterisation and antialiasing differ between Windows and Linux by far more than any
tolerance that would still catch a real change, so a single shared set leaves whichever
platform did not record it permanently red. Each platform records and compares its own.

Only the `win32` set is recorded today, which makes the screenshot lane **local-only**. CI
(`.github/workflows/frontend.yml`) runs the workbench typecheck and the accessibility lane —
axe needs no recorded baseline — and picks up the screenshot lane once a `linux` set is
recorded on the runner. Until then, a component migration's zero-diff evidence is something
a human produced locally, and the write-up should say so rather than implying a gate caught
it.

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
