import { expect, test } from "@playwright/test";

import { ALL_SPECIMENS } from "../src/specimens";
import { SCREENSHOT_THEMES } from "../src/themes";

// One screenshot per specimen per theme, rather than one per page.
//
// A page-sized baseline is the obvious thing to write and the wrong thing to have: any change
// anywhere re-records it, so the diff never names a component and reviewers learn to accept
// the update. Per-specimen shots mean a padding change to `Card` fails `card-titled` and
// `card-bare` in both themes and nothing else.
//
// The theme is a URL parameter the page reads, so each case is a fresh navigation with the
// theme fully determined by the address — no toggling, no localStorage, no run-order
// dependence.
//
// `?only=<id>` renders that specimen alone, at the same fixed origin every time. Without it
// a specimen sat wherever the ones above left it — usually a fractional y — and that offset
// decides the subpixel phase its borders and glyphs rasterise at, so adding a specimen
// anywhere above silently re-recorded unrelated baselines below. See `requestedSpecimen` in
// src/main.tsx for the measurements. Each test already navigates once, so this costs
// nothing and makes a per-specimen baseline depend on its specimen alone.
//
// Two themes, not all of them, and on purpose: `SCREENSHOT_THEMES` is the base theme plus the
// one the OS dark preference selects — what an app renders when nobody chooses. The named
// themes differ from these only in colour values, so a third set of per-specimen shots would
// re-prove the geometry the first two already prove while tripling what a reviewer has to
// accept for a one-line padding change. Their legibility is measured instead, statically over
// every declared pairing and by axe over every painted specimen. See `src/themes.ts`.

// An `overlay` specimen is shot as a VIEWPORT rather than as an element, and the reason is
// not a preference. The element shot clips to the specimen's bounding box, and the three
// framework overlays each paint outside it by a different mechanism: `Popover` portals its
// panel to `document.body`, a `<dialog>` opened with `showModal()` renders in the top layer,
// and the toast viewport is fixed to the corner of the screen. Clipping those produces a
// baseline of the trigger with the panel missing — or, for `ConfirmDialog`, a dimmed empty
// card, because the `::backdrop` covers the clip and the dialog does not. That is worse than
// having no baseline, because it looks like coverage.
//
// A viewport shot loses nothing the element shot gave us, because `?only=` already reduced
// the page to one specimen at one fixed origin, and the viewport itself is pinned
// (1280x900, deviceScaleFactor 1) in playwright.config.ts. So the baseline still depends on
// this specimen and nothing else — the per-specimen promise is kept by the address, not by
// the clip.
test.describe("component specimens", () => {
  for (const theme of SCREENSHOT_THEMES) {
    test.describe(theme, () => {
      for (const specimen of ALL_SPECIMENS) {
        test(`${specimen.groupId}/${specimen.id}`, async ({ page }) => {
          await page.goto(`/?theme=${theme}&only=${specimen.id}`);
          const target = page.locator(`[data-specimen="${specimen.id}"]`);
          // Wait for the element rather than a timeout: react-core compiles from source
          // through Vite, so a cold dev server takes a moment on the first navigation.
          await target.waitFor({ state: "visible" });
          // Fonts settle after first paint; an unsettled webfont swap is the classic source
          // of a one-line-height diff.
          await page.evaluate(() => document.fonts.ready);
          await expect(specimen.overlay === true ? page : target).toHaveScreenshot(
            `${theme}-${specimen.id}.png`,
          );
        });
      }
    });
  }
});

test("every specimen is present and uniquely identified", async ({ page }) => {
  // The per-specimen tests above would silently pass over a typo'd id if the locator matched
  // nothing — `waitFor` would fail, but a duplicate id would instead screenshot the first of
  // two elements and never mention the second. Both are caught here once.
  await page.goto("/?theme=light");
  const ids = ALL_SPECIMENS.map((specimen) => specimen.id);
  expect(new Set(ids).size, "specimen ids must be unique").toBe(ids.length);
  for (const id of ids) {
    await expect(
      page.locator(`[data-specimen="${id}"]`),
      `specimen ${id} should render exactly once`,
    ).toHaveCount(1);
  }
  await expect(page.locator("[data-specimen]")).toHaveCount(ids.length);
});
