import { expect, type Page } from "@playwright/test";

/**
 * The administrator the base-profile flows sign in as. The default matches the bundled example
 * workbench's seed; a generated repo points these at its own seeded admin via
 * `TERP_E2E_ADMIN_EMAIL` / `TERP_E2E_ADMIN_PASSWORD` (or passes credentials to `login`)
 * without editing the suite.
 */
export const ADMIN = {
  email: process.env.TERP_E2E_ADMIN_EMAIL ?? "admin@acme.test",
  password: process.env.TERP_E2E_ADMIN_PASSWORD ?? "correct horse battery staple",
};

/**
 * A writer (rank at/above the write threshold) and a read-only user, for an app's RBAC flows that
 * assert write-gated controls appear for a writer and hide for a viewer. The defaults match the
 * bundled example workbench's seed and are overridable per app via the matching `TERP_E2E_*`
 * variables.
 */
export const EDITOR = {
  email: process.env.TERP_E2E_EDITOR_EMAIL ?? "editor@acme.test",
  password: process.env.TERP_E2E_EDITOR_PASSWORD ?? "correct horse battery staple",
};

export const VIEWER = {
  email: process.env.TERP_E2E_VIEWER_EMAIL ?? "viewer@acme.test",
  password: process.env.TERP_E2E_VIEWER_PASSWORD ?? "correct horse battery staple",
};

/**
 * Sign in through the real login screen. App-agnostic: the login screen and session are
 * base-profile (identical in every Terp app), so this is the reusable entry point any app's
 * conformance suite composes. Success is the sign-in screen being replaced by the app shell;
 * callers assert their own landing content afterwards.
 */
export async function login(
  page: Page,
  credentials: { email: string; password: string } = ADMIN,
): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.getByPlaceholder("Email").fill(credentials.email);
  await page.getByPlaceholder("Password").fill(credentials.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toHaveCount(0, {
    timeout: 15_000,
  });
}

/**
 * Sign out through the shell's account menu and assert the session is gone. Base-profile: the
 * user menu (avatar at the bottom of every Terp app's sidebar) opens Settings and Sign out;
 * sign-out revokes the token server-side (ADR 0031), so this is reusable across apps. Success
 * is the app shell being replaced by the sign-in screen.
 */
export async function logout(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
}
