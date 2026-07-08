import { defineConfig, devices } from "@playwright/test";

// The suite runs against an ALREADY-RUNNING Terp stack — the Docker workbench
// (`docker compose -f apps/example/docker-compose.yml up`) or `terp dev`. CI brings the stack
// up first; locally, point TERP_E2E_BASE_URL at your running frontend (e.g. the workbench port).
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
