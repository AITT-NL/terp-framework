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
  // Each platform records and compares its own; CI compares the Linux set.
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
      // Antialiasing differs by a pixel or two across machines for the same render. A small
      // ratio absorbs that without absorbing a real change: a token or spacing edit moves
      // far more than 1% of a specimen's pixels.
      maxDiffPixelRatio: 0.01,
    },
  },
  webServer: {
    command: "npm run dev",
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
