import { expect, test } from "@playwright/test";
import { login, logout } from "@terp/conformance";

// This app's seeded administrator (see app/seed.py). Override via TERP_E2E_ADMIN_* for other
// environments (e.g. a staging seed).
const ADMIN = {
  email: process.env.TERP_E2E_ADMIN_EMAIL ?? "admin@example.test",
  password: process.env.TERP_E2E_ADMIN_PASSWORD ?? "correct horse battery staple",
};

// Base-profile auth — identical in every Terp app: a signed-out visitor is gated to the login
// screen, the seeded admin signs in to reach the app shell, and can sign out again. This suite is
// yours to grow: add module specs alongside this file using the @terp/conformance login/logout
// helpers (see the notes/tasks specs in the Terp example app for the pattern).

test("an unauthenticated visitor is gated to the sign-in screen", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0);
});

test("the seeded admin can sign in and sign out", async ({ page }) => {
  await login(page, ADMIN);
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await logout(page);
  await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0);
});
