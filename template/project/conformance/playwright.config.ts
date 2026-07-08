import { defineConfig, devices } from "@playwright/test";

// Runs against an ALREADY-RUNNING stack — the Docker workbench (`terp docker dev` /
// `docker compose up`) or `terp dev`. Point TERP_E2E_BASE_URL at your running frontend; it
// defaults to the workbench's web port.
const baseURL = process.env.TERP_E2E_BASE_URL ?? "http://localhost:5173";

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
