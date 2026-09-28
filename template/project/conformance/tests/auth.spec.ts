import { expect, test } from "@playwright/test";
import { login, loginHeading, logout, primaryNavigation } from "@terpjs/conformance";

// This app's seeded administrator (see app/seed.py). Override via TERP_E2E_ADMIN_* for other
// environments (e.g. a staging seed).
const ADMIN = {
  email: process.env.TERP_E2E_ADMIN_EMAIL ?? "admin@example.test",
  password: process.env.TERP_E2E_ADMIN_PASSWORD ?? "correct horse battery staple",
};

// Base-profile auth — identical in every Terp app: a signed-out visitor is gated to the login
// screen, the seeded admin signs in to reach the app shell, and can sign out again. This suite is
// yours to grow: add module specs alongside this file using the @terpjs/conformance login/logout
// helpers (see the notes/tasks specs in the Terp example app for the pattern).
//
// Nothing here is found by its text. The sign-in screen and the shell speak whatever language
// this app ships — Dutch, as generated — so `loginHeading` and `primaryNavigation` locate them by
// the framework's markers, and `login`/`logout` hold every control they touch to having an
// accessible name without naming it. Your own module specs are the place for your own wording.
//
// The helpers drive the framework's own sign-in screen. If this app replaces it
// (`renderTerpApp({ login: … })`), that screen is the app's, and so are its sign-in steps: sign
// in and out here by the screen's own accessible names instead of through `login`, `logout` and
// `loginHeading`. Do not give it the framework's `data-terp` markers to be found by: they are
// react-core's identity for its own components, which its stylesheet and layout contract key on.
//
// One fixed rate-limit window keyed by client IP covers every request the app answers, so a long
// suite on a shared runner can exhaust it — and every symptom of that is an element that never
// appears. `login`/`logout` already say so when it happens. For a flow of your own, wrap it:
// `watchForThrottling(page)` once, then `assertNotThrottled(response)` on a direct API call, so a
// throttled run fails with the throttle named instead of a timeout on an unrelated locator.

test("an unauthenticated visitor is gated to the sign-in screen", async ({ page }) => {
  await page.goto("/");
  await expect(loginHeading(page)).toBeVisible();
  await expect(primaryNavigation(page)).toHaveCount(0);
});

test("the seeded admin can sign in and sign out", async ({ page }) => {
  await login(page, ADMIN);
  await expect(primaryNavigation(page)).toBeVisible();
  await logout(page);
  await expect(primaryNavigation(page)).toHaveCount(0);
});
