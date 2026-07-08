import { defineConfig, devices } from "@playwright/test";

// This app's own end-to-end flows (its modules: notes, tasks, projects, journals) against an
// ALREADY-RUNNING stack — the Docker workbench (`docker compose -f ../docker-compose.yml up`) or
// `terp dev`. The app-agnostic base-profile flows (auth gating, session lifecycle) live in
// @terp/conformance and run separately; this suite composes that package's helpers (login, seeded
// role credentials) with the app's own module expectations.
const baseURL = process.env.TERP_E2E_BASE_URL ?? "http://localhost:5173";

export default defineConfig({
  testDir: "./e2e",
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
