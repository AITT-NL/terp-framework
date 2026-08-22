import fs from "node:fs";
import { fileURLToPath } from "node:url";

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
// not a preference. The element shot clips to the specimen's bounding box, and four framework
// surfaces paint outside it, each by a different mechanism: `Popover` portals its panel to
// `document.body`, a `<dialog>` opened with `showModal()` renders in the top layer, the toast
// viewport is fixed to the corner of the screen, and the `Combobox` listbox is simply
// `position: absolute` and overflows the box. Clipping those produces a
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
          // Off linux this specimen has no baseline to compare against, and the default for a
          // missing one is to write it and fail — which converts "nobody could record this"
          // into a committed baseline nobody verified. Skipped instead, by name. See
          // `LINUX_ONLY` below for why the list is data and what asserts it.
          test.skip(
            LINUX_ONLY.has(specimen.id) && process.platform !== "linux",
            `${specimen.id} has linux baselines only`,
          );
          // A per-specimen viewport, before the navigation so the first layout is the right
          // one. Declared on the specimen, so the baseline still depends on the specimen
          // alone — see `viewport` in src/specimens.tsx for the declarations it exists to
          // make reachable at all.
          if (specimen.viewport !== undefined) {
            await page.setViewportSize(specimen.viewport);
          }
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

/**
 * Specimens whose baselines exist for **linux only**, by name.
 *
 * Not a preference and not a tolerance: Chrome and chrome-headless-shell are blocked by group
 * policy on the machine these were authored on, so the only recorder available was the
 * containerised linux image CI also compares in. A specimen added under that constraint gets one
 * platform's baselines and cannot get the other's until someone with a working Windows browser
 * records them.
 *
 * The reason this is DATA rather than a note in a commit message is what happens otherwise.
 * Playwright's default for a missing baseline is to WRITE it and then fail, `__screenshots__` is
 * in no ignore file, and the workbench README tells a contributor to `git add -A` — so a Windows
 * developer running the lane produces a full set of win32 baselines recorded from whatever the
 * code did that afternoon, staged automatically, indistinguishable in review from a real
 * recording. The gap was already there before this list existed (242 linux against 238 win32)
 * with nothing naming it and the README asserting "Both sets are recorded".
 *
 * So: skipped off linux, and the count is asserted below. Removing a name from this set without
 * recording its win32 baselines turns the suite red on Windows instead of silently writing them.
 */
const LINUX_ONLY = new Set([
  "app-shell-brand-pair",
  "app-shell-header-nav",
  "app-shell-nav-groups",
  "app-shell-nav-groups-collapsed",
  "app-shell-header-nav-groups",
  "app-shell-nav-groups-drawer",
]);

test("the linux-only baseline set is exactly the set that is missing on win32", () => {
  // The ratchet. This reads the two directories rather than trusting the list, so a name that
  // quietly gained win32 baselines has to leave the set, and a specimen that quietly lost them
  // has to join it or fail here. Without this the set decays into a blanket exemption — the
  // shape `_UNINDEXED_MODULES` and the marker worklists are all written to avoid.
  //
  // No browser, like the image-tag check below: reading two directories is the whole check.
  const root = fileURLToPath(new URL("./__screenshots__", import.meta.url));
  const namesIn = (platform: string) =>
    new Set(
      fs
        .readdirSync(`${root}/${platform}`)
        .map((file) => file.replace(/^(light|dark)-/, "").replace(/\.png$/, "")),
    );
  const linux = namesIn("linux");
  const win32 = namesIn("win32");
  const missingOnWin32 = [...linux].filter((name) => !win32.has(name)).sort();
  expect(missingOnWin32).toEqual([...LINUX_ONLY].sort());
  // And nothing may exist on win32 alone: that would mean a baseline recorded on a developer
  // machine that CI has never compared against.
  expect([...win32].filter((name) => !linux.has(name)).sort()).toEqual([]);
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

test("records and compares against the same browser build", () => {
  // The linux baselines in this directory were recorded in a specific Playwright image, and
  // CI compares against them inside that same image — which only holds while the image tag
  // and the version in package-lock.json name the same release. Nothing else notices if they
  // part company: the run stays green until a browser change moves a glyph by a pixel, and
  // then every baseline fails at once. The instinct that provokes is to re-record, which
  // converts a version mismatch into a committed one and buries it for good.
  //
  // Three files say the tag must track the version — this config, the README and the
  // workflow. A "must" that nothing checks is the thing this suite exists to disbelieve, so
  // it is checked here, in the lane whose evidence depends on it.
  //
  // No browser, like the theme-allowance test in the a11y lane: reading two files is the
  // whole check, and giving it a page would only make it slower and able to fail for
  // unrelated reasons.
  const repoRoot = fileURLToPath(new URL("../../..", import.meta.url));
  const lock = JSON.parse(fs.readFileSync(`${repoRoot}/package-lock.json`, "utf8"));
  const pinned = lock.packages["node_modules/@playwright/test"]?.version;
  expect(pinned, "@playwright/test is not pinned in package-lock.json").toBeTruthy();

  const workflow = fs.readFileSync(`${repoRoot}/.github/workflows/frontend.yml`, "utf8");
  const tags = [...workflow.matchAll(/mcr\.microsoft\.com\/playwright:v([\d.]+)-\w+/g)].map(
    (match) => match[1],
  );
  // An empty list would pass a naive equality check on every element, and would mean the
  // containerised step had been renamed or removed — which is exactly when this gate stops
  // being true without saying so.
  expect(tags.length, "no playwright image tag found in frontend.yml").toBeGreaterThan(0);
  for (const tag of tags) {
    expect(tag, `image tag v${tag} does not match the pinned @playwright/test ${pinned}`).toBe(
      pinned,
    );
  }
});
