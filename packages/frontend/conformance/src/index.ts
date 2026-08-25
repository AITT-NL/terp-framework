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
  // By LABEL, not by placeholder. The login fields were placeholder-only until the labels
  // landed, and a placeholder was the only handle they had — which is the same defect from
  // the other side: a name that vanishes the moment a user types is not a name. Selecting
  // the way a user perceives the field is also what keeps this suite honest about
  // accessibility, since a field with no accessible name now fails here rather than being
  // reachable by a workaround.
  await page.getByLabel("Email", { exact: true }).fill(credentials.email);
  await page.getByLabel("Password", { exact: true }).fill(credentials.password);
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
 *
 * The trigger is located by its marker rather than by an accessible name, and that is a fix
 * rather than a shortcut. The name is deliberately not fixed: expanded, the button renders the
 * user's own email and role as visible text and takes its name from them, because an
 * `aria-label` REPLACES subtree text in the accessible name and would leave a voice-control
 * user with nothing to say that matches what they see (WCAG 2.5.3, Label in Name). Only the
 * collapsed icon rail carries a label, where the avatar is aria-hidden and the button would
 * otherwise have no name at all. So the name varies with the shell state AND with the signed-in
 * user, which makes it the wrong axis for an app-agnostic helper; `data-terp` is the stable one,
 * being a pinned inventory whose renames are release notes.
 */
export async function logout(page: Page): Promise<void> {
  await page.locator('[data-terp="user-menu"] [data-terp="menu-trigger"]').click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
}
