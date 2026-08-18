import { defineConfig, devices } from "@playwright/test";

// Visual baselines for the component library.
//
// Unlike the app suites, this config owns its server: it starts the workbench itself, so a
// baseline run needs no stack, no database and no login. That is what makes it usable as a
// gate on a styling change — the thing it renders is the package source, nothing more.
//
// Everything that could make a screenshot differ between two runs of the same commit is
// pinned here: a fixed viewport and scale factor, one browser, a forced colour scheme per
// navigation (the page reads `?theme=`), disabled animations, and no retries locally. The
// spinner keyframes in particular would make every run differ without `animations:
// "disabled"` — which Playwright applies for `toHaveScreenshot` by default and is set
// explicitly here so it survives someone reading only this file.

const PORT = 5175;

export default defineConfig({
  testDir: "./visual",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // No retries: a visual test that passes on retry is a flaky baseline, and hiding that
  // behind a retry is how a suite stops being evidence.
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  // Baselines are split by platform on purpose. Font rasterisation and antialiasing differ
  // between Windows and Linux by far more than any tolerance that would still catch a real
  // change, so one shared set means whichever platform did not record it is permanently red.
  // Each platform records and compares its own. Only the win32 set is recorded today, so
  // the screenshot lane is local-only: CI runs the a11y lane (which needs no baseline) and
  // will run this one once a linux set is recorded on the runner.
  snapshotPathTemplate: "{testDir}/__screenshots__/{platform}/{arg}{ext}",
  use: {
    baseURL: `http://localhost:${PORT}`,
    ...devices["Desktop Chrome"],
    viewport: { width: 1280, height: 900 },
    deviceScaleFactor: 1,
    trace: "on-first-retry",
  },
  expect: {
    toHaveScreenshot: {
      animations: "disabled",
      caret: "hide",
      scale: "css",
      // Two knobs, and they are not interchangeable — pinning one and inheriting the other is
      // how this gate went blind. `threshold` decides whether a single pixel counts as
      // different at all (a normalised YIQ colour distance); `maxDiffPixelRatio` decides how
      // many counted pixels are tolerable. Only the ratio used to be set here, so Playwright's
      // default `threshold: 0.2` applied — permissive enough that a status token moving from
      // `#16a34a` to `#15803d` produced *zero* differing pixels and all 62 baselines passed a
      // change that visibly repaints every badge in every app. Phase 2d found that by changing
      // ten specimens and being told nothing had moved.
      //
      // The earlier mutation check did not catch it because it swapped blue for red, which
      // clears a 0.2 threshold easily. A gate verified only against a large change is verified
      // only for large changes.
      //
      // 0.02 counts any colour shift a reviewer could see while still ignoring the one-bit
      // antialiasing drift the ratio is there to absorb.
      threshold: 0.02,
      maxDiffPixels: 0,
    },
  },
  webServer: {
    command: "npm run dev",
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
