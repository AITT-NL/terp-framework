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

31 specimens in 7 groups. The accessibility lane runs them in **every** shipped theme (155
axe runs across five palettes); the screenshots cover the **two default** themes (62
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

## How the visual suite is kept honest

**One screenshot per specimen, not per page.** A page-sized baseline is the obvious thing to
write and the wrong thing to have: any change anywhere re-records it, so the diff never names
a component and reviewers learn to accept the update. Per-specimen shots mean a `Card`
padding change fails `card-titled` and `card-bare` in both themes and nothing else.

**The theme is in the URL.** The page reads `?theme=<name>` and sets `data-theme` on
`<html>` directly rather than going through `ThemeProvider`, which persists to
`localStorage` — a toggled theme would leak between runs and make a baseline depend on run
order. An address that fully determines the render is the whole trick. The theme names come
from the contract's published token manifest (`src/themes.ts`), so a theme added there is
renderable here with no edit to this app.

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
platform did not record it permanently red. Each platform records and compares its own; CI
compares the Linux set. Within one platform, `maxDiffPixelRatio: 0.01` absorbs a pixel or two
of antialiasing drift without absorbing a real change — a token edit moves far more than that.

Verified by mutation rather than assumed: changing `--color-brand-primary` from `#2563eb` to
`#dc2626` fails `light-button-variants` on 2679 pixels (ratio 0.03). The dark baseline
correctly passes, because the dark block declares its own brand colour — the two themes are
genuinely independent.

## Accessibility

`visual/a11y.spec.ts` runs axe over every specimen in every shipped theme at WCAG 2.0/2.1 A
and AA —
realising the `a11y` lane the Terp Standard recommends and nothing implemented. Scoped per
specimen for the same reason the screenshots are: a page-wide run produces a list of
violations with no owner, and the first thing anyone does with an unattributed list is stop
reading it.

Every rule is held at zero except `color-contrast`, which has a recorded, shrink-only list of
known-failing specimens. Those are the same token pairings `tokens.contrast.test.js` measures
— axe reaching the same verdict from the painted pixels is corroboration, not duplication, and
it reaches further: the declared-pairs list names five pairings, and axe finds them in nine
specimens, because every specimen containing a primary button fails in dark and every specimen
containing a `Badge` fails in light. Emptying both lists is the semantic token layer's
acceptance criterion.

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
