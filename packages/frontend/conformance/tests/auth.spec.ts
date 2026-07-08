import { expect, test } from "@playwright/test";

import { ADMIN, login, logout } from "../src/index";

// Base-profile auth — reusable across ANY Terp app (the login screen + session are identical
// everywhere): a signed-out visitor is gated to the login screen, the seeded admin can sign in
// and reach the app shell, sign out again, and bad credentials are refused — all over the real
// deny-by-default backend, not a mock.

test("an unauthenticated visitor is gated to the sign-in screen", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  // The authenticated app shell (its primary navigation) is not reachable without a session.
  await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0);
});

test("the seeded admin can sign in and reach the app shell", async ({ page }) => {
  await login(page, ADMIN);
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
});

test("a signed-in session survives a page reload", async ({ page }) => {
  await login(page, ADMIN);
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();

  await page.reload();

  // ADR 0054: the access token is still memory-only, but the httpOnly refresh cookie restores
  // a fresh access token on boot, so a normal reload keeps the user in the app shell.
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sign in" })).toHaveCount(0);
});

test("a signed-in user can sign out and is returned to the sign-in screen", async ({ page }) => {
  await login(page, ADMIN);
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await logout(page);
  // The session is gone: the app shell is no longer reachable, only the login screen.
  await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0);
});

test("bad credentials are refused", async ({ page }) => {
  await page.goto("/");
  // A non-existent account, so a failed attempt never locks out the seeded admin.
  await page.getByPlaceholder("Email").fill("nobody@acme.test");
  await page.getByPlaceholder("Password").fill("definitely-not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Sign-in failed")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0);
});
