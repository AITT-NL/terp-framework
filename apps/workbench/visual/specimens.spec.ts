import { expect, test } from "@playwright/test";

import { ALL_SPECIMENS } from "../src/specimens";

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

const THEMES = ["light", "dark"] as const;

test.describe("component specimens", () => {
  for (const theme of THEMES) {
    test.describe(theme, () => {
      for (const specimen of ALL_SPECIMENS) {
        test(`${specimen.groupId}/${specimen.id}`, async ({ page }) => {
          await page.goto(`/?theme=${theme}`);
          const target = page.locator(`[data-specimen="${specimen.id}"]`);
          // Wait for the element rather than a timeout: react-core compiles from source
          // through Vite, so a cold dev server takes a moment on the first navigation.
          await target.waitFor({ state: "visible" });
          // Fonts settle after first paint; an unsettled webfont swap is the classic source
          // of a one-line-height diff.
          await page.evaluate(() => document.fonts.ready);
          await expect(target).toHaveScreenshot(`${theme}-${specimen.id}.png`);
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
