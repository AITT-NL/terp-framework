import { defineConfig, devices } from "@playwright/test";

// Runs against an ALREADY-RUNNING stack, at the address in TERP_E2E_BASE_URL — and there is
// deliberately no default. The host port a stack answers on is assigned per checkout
// (`terp ports assign`), so any number written here is some other checkout's port, or some
// other application's, and a suite that drives it reports on the wrong app or on nothing.
//
// `uv run terp verify --profile release --only conformance` sets it from this checkout's
// assignment, which is how CI runs the suite. To run it directly, name the running frontend.
const baseURL = process.env.TERP_E2E_BASE_URL;
if (!baseURL) {
  throw new Error(
    "TERP_E2E_BASE_URL is not set, so this suite has no stack to drive.\n" +
      "  Run it through the gate, which reads the address from this checkout's assigned web port:\n" +
      "    uv run terp verify --profile release --only conformance\n" +
      "  Or name the running frontend yourself (`uv run terp dev` prints its address when it starts):\n" +
      "    TERP_E2E_BASE_URL=<that address> npm test",
  );
}

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
