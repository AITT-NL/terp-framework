import { expect, test } from "@playwright/test";

import {
  ADMIN,
  EDITOR,
  login,
  loginHeading,
  logout,
  primaryNavigation,
  submitLogin,
} from "../src/index";

// Base-profile auth — reusable across ANY Terp app (the login screen + session are identical
// everywhere): a signed-out visitor is gated to the login screen, the seeded admin can sign in
// and reach the app shell, sign out again, and bad credentials are refused — all over the real
// deny-by-default backend, not a mock.
//
// Every element is found by the markers the helpers use and none by its text, so this suite
// runs unchanged against an app in any locale. The example app it runs on in CI is English;
// the project template's app is Dutch, and the template's own copy of these flows is what
// proves the point there.

test("an unauthenticated visitor is gated to the sign-in screen", async ({ page }) => {
  await page.goto("/");
  await expect(loginHeading(page)).toBeVisible();
  // The authenticated app shell (its primary navigation) is not reachable without a session.
  await expect(primaryNavigation(page)).toHaveCount(0);
});

test("the seeded admin can sign in and reach the app shell", async ({ page }) => {
  await login(page, ADMIN);
  await expect(primaryNavigation(page)).toBeVisible();
});

test("a signed-in session survives a page reload", async ({ page }) => {
  await login(page, ADMIN);
  await expect(primaryNavigation(page)).toBeVisible();

  await page.reload();

  // ADR 0054: the access token is still memory-only, but the httpOnly refresh cookie restores
  // a fresh access token on boot, so a normal reload keeps the user in the app shell.
  await expect(primaryNavigation(page)).toBeVisible();
  await expect(loginHeading(page)).toHaveCount(0);
});

test("a signed-in user can sign out and is returned to the sign-in screen", async ({ page }) => {
  // As the editor, not the admin. Signing out revokes EVERY session the account holds (the
  // token epoch moves, ADR 0031), and the tests in this run are parallel: signing the admin out
  // pulled the session from under whichever admin test was mid-flight — the reload test above,
  // or a standard probe's bearer token — and failed it for a reason that has nothing to do with
  // what it tests. No other test in this suite signs in as the editor.
  await login(page, EDITOR);
  await expect(primaryNavigation(page)).toBeVisible();
  await logout(page);
  // The session is gone: the app shell is no longer reachable, only the login screen.
  await expect(primaryNavigation(page)).toHaveCount(0);
});

test("bad credentials are refused", async ({ page }) => {
  // A non-existent account, so a failed attempt never locks out the seeded admin.
  await submitLogin(page, { email: "nobody@acme.test", password: "definitely-not-the-password" });
  // The refusal is announced (role="alert") and says something, in whatever language it is.
  const refusal = page.locator('[data-terp="login-error"]');
  await expect(refusal).toBeVisible();
  await expect(refusal).toHaveRole("alert");
  await expect(refusal).not.toBeEmpty();
  await expect(primaryNavigation(page)).toHaveCount(0);
});
