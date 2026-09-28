import { expect, type APIResponse, type Locator, type Page } from "@playwright/test";

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
 * One 429 the app answered while a spec was running: the throttle, as the server already
 * described it.
 */
export interface ThrottleRecord {
  /** The request that was refused. */
  url: string;
  /** Seconds until the window resets (`Retry-After`), or null when the header is absent. */
  retryAfter: number | null;
  /** The cap that was hit (`X-RateLimit-Limit`), or null. */
  limit: number | null;
}

/**
 * Every page being watched, and the first throttle each one saw.
 *
 * A WeakMap rather than a field on the page: the harness has no fixture of its own to hang
 * state on, and a suite that opens several pages must not have one page's verdict explain
 * another's.
 */
const THROTTLES = new WeakMap<Page, ThrottleRecord>();
const WATCHED = new WeakSet<Page>();

function header(value: string | undefined): number | null {
  if (value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Record the first 429 *page* receives, so a later failure can say what actually happened.
 *
 * The rate limiter is one fixed window keyed by client IP and applied to every request
 * (240/60s by default, health checks included), so a conformance run that logs in, navigates
 * and asserts can reach the cap on a shared runner — and every symptom of that is an element
 * that never appears. The server already says so precisely: a typed `rate_limited` envelope
 * with `Retry-After` and the `X-RateLimit-*` triple. Nothing in this harness read it, so the
 * failure surfaced as a timeout on an unrelated locator, which is a debugging session about
 * the wrong thing.
 *
 * FIRST rather than last: the first refusal is the one that broke the flow, and the ones
 * after it are its consequences.
 */
export function watchForThrottling(page: Page): void {
  if (WATCHED.has(page)) return;
  WATCHED.add(page);
  page.on("response", (response) => {
    if (response.status() !== 429 || THROTTLES.has(page)) return;
    const headers = response.headers();
    THROTTLES.set(page, {
      url: response.url(),
      retryAfter: header(headers["retry-after"]),
      limit: header(headers["x-ratelimit-limit"]),
    });
  });
}

/** The throttle *page* saw, if it saw one. */
export function throttleSeen(page: Page): ThrottleRecord | undefined {
  return THROTTLES.get(page);
}

/**
 * Re-throw *error* as a throttle when the page was rate-limited, otherwise unchanged.
 *
 * Wrapping rather than replacing: a 429 seen during a run does not prove it caused this
 * particular failure, so the original error stays in the message. What changes is that the
 * reader is told a throttle happened at all, which is the fact that was on the wire and
 * unread.
 */
export function explainThrottling(page: Page, error: unknown): unknown {
  const throttle = THROTTLES.get(page);
  if (throttle === undefined) return error;
  const wait = throttle.retryAfter === null ? "" : `, Retry-After ${throttle.retryAfter}s`;
  const cap = throttle.limit === null ? "" : ` (cap ${throttle.limit} requests/window)`;
  return new Error(
    `the run was rate-limited (429${wait})${cap}: ${throttle.url}\n` +
      "  One fixed window keyed by client IP covers every request, so a whole suite " +
      "sharing a runner can exhaust it and every symptom looks like a missing element.\n" +
      "  Raise the cap for the workbench via SecurityConfig(rate_limit=RateLimit(...)), " +
      "or serialise the suite.\n" +
      `  The assertion that failed: ${error instanceof Error ? error.message : String(error)}`,
  );
}

/** Run *body*, and explain a failure as a throttle when the page saw one. */
async function orThrottle<T>(page: Page, body: () => Promise<T>): Promise<T> {
  try {
    return await body();
  } catch (error) {
    throw explainThrottling(page, error);
  }
}

/**
 * Fail with the throttle named when *response* is a 429, otherwise return it unchanged.
 *
 * The page-level watcher cannot see this one: an `APIRequestContext` emits no response
 * events, so a suite that drives the API directly would still report `expect(response.ok())`
 * as a bare false. The server's own envelope says exactly what happened; this reads it.
 */
export function assertNotThrottled(response: APIResponse): APIResponse {
  if (response.status() !== 429) return response;
  const headers = response.headers();
  const retryAfter = headers["retry-after"];
  const limit = headers["x-ratelimit-limit"];
  throw new Error(
    `the run was rate-limited (429${retryAfter === undefined ? "" : `, Retry-After ${retryAfter}s`})` +
      `${limit === undefined ? "" : ` (cap ${limit} requests/window)`}: ${response.url()}\n` +
      "  One fixed window keyed by client IP covers every request, so a whole suite " +
      "sharing a runner can exhaust it.\n" +
      "  Raise the cap for the workbench via SecurityConfig(rate_limit=RateLimit(...)), " +
      "or serialise the suite.",
  );
}

/**
 * Where the base-profile screens are found: the `data-terp` markers `@terpjs/react-core` pins
 * in its marker inventory (`markers.test.ts`), whose renames are release notes. Never an
 * accessible name, for two reasons.
 *
 * A name is in the app's language, and the project template starts an app in Dutch. A helper
 * looking for "Sign in" was therefore a helper for English apps: every other app failed its
 * own conformance suite on the login screen before it had written a line of its own. A marker
 * is the same string in every locale.
 *
 * And a name is not always fixed even in one language. The account menu's trigger takes its
 * name from the signed-in user's own email and role when the sidebar is expanded, because an
 * `aria-label` REPLACES subtree text in the accessible name and would leave a voice-control
 * user with nothing to say that matches what they see (WCAG 2.5.3, Label in Name); only the
 * collapsed icon rail carries a label. So its name varies with the shell state AND the user.
 *
 * Locating by marker alone would drop the one thing a name-based locator proved for free:
 * that the control HAS a name. `getByLabel("Email")` could not find an unlabelled field, so
 * the suite failed on exactly the defect a screen-reader user would hit. `expectNamed` puts
 * that back without choosing a language: every control a helper touches must be visible,
 * expose the role a user perceives, and carry a non-empty accessible name. An unlabelled field
 * still fails here, in any locale.
 *
 * These are the framework's own screens, and the helpers drive nothing else. An app that
 * replaces the sign-in screen (`renderTerpApp({ login: … })`) owns that screen, and its specs
 * write their own sign-in steps, by the screen's own accessible names, instead of calling
 * `login()` and `logout()`. It does not put these markers on its screen to be found: a
 * `data-terp` marker is react-core's identity for a component, which its stylesheet is keyed
 * on and its layout contract checks, so a marker an app writes forges both. When the heading
 * is not there, the helpers fail saying so ({@link notTheFrameworkSignIn}).
 */
const LOGIN_HEADING = '[data-terp="login-title"]';
const LOGIN_EMAIL = '[data-terp="login-email"] [data-terp="input"]';
const LOGIN_PASSWORD = '[data-terp="login-password"] [data-terp="input"]';
const LOGIN_SUBMIT = '[data-terp="login-submit"] [data-terp="button"]';
const USER_MENU_TRIGGER = '[data-terp="user-menu"] [data-terp="menu-trigger"]';
const SIGN_OUT = '[data-terp="user-menu-sign-out"] [data-terp="menu-item"]';
const PRIMARY_NAVIGATION = '[data-terp="appshell-nav"]';

type Role = Parameters<Page["getByRole"]>[0];

/**
 * Visible, exposing *role*, and named — in whatever language the app speaks. *missing* is what
 * the failure says first when the element never becomes visible.
 */
async function expectNamed(locator: Locator, role: Role, missing?: string): Promise<void> {
  await expect(locator, missing).toBeVisible();
  await expect(locator).toHaveRole(role);
  await expect(locator).toHaveAccessibleName(/\S/);
}

/**
 * What a helper says when the framework's sign-in heading is not where it looked.
 *
 * An agent reads this, not the source, so it states what was observed, which screens the
 * helpers drive, and the two ways forward for an app that replaced the sign-in screen, and
 * it closes the way that looks shortest: writing the framework's markers into the app's
 * screen.
 */
function notTheFrameworkSignIn(when: "signing-in" | "signed-out", page: Page): string {
  const observed =
    when === "signing-in"
      ? `The framework's sign-in screen is not on the page at ${page.url()}`
      : `After signing out, the framework's sign-in screen did not appear at ${page.url()}`;
  const otherwise =
    when === "signing-in"
      ? "the page never showed the sign-in screen: check the address the suite drives."
      : "signing out did not return to the sign-in screen, which is the failure to look into.";
  return [
    `${observed}: no ${LOGIN_HEADING} became visible.`,
    "  login(), submitLogin() and logout() drive react-core's own sign-in screen only.",
    "  If this app replaces it (renderTerpApp({ login: … })), that screen is the app's own, and so",
    "  are its sign-in steps. Either:",
    "    - sign in and out from the spec by the screen's own accessible names (getByLabel,",
    "      getByRole) instead of calling these helpers; or",
    "    - drop the `login` option, so the framework's screen renders again.",
    "  Do not add data-terp markers to the app's screen to be found: they are react-core's",
    "  identity for its own components, which its stylesheet and layout contract key on.",
    `  If the app does not replace it, ${otherwise}`,
  ].join("\n");
}

/**
 * The sign-in screen's heading: on screen exactly while nobody is signed in. A spec asserts
 * against this rather than against a heading's text, which is the app's to translate.
 */
export function loginHeading(page: Page): Locator {
  return page.locator(LOGIN_HEADING);
}

/**
 * The app shell's primary navigation: rendered once, in the sidebar or the header, and only
 * behind a session. A spec asserts against this rather than against the landmark's name.
 */
export function primaryNavigation(page: Page): Locator {
  return page.locator(PRIMARY_NAVIGATION);
}

/**
 * Load the app, then fill and submit the sign-in form — holding every control to a name — and
 * judge nothing about the outcome. {@link login} is this plus "the shell replaced the sign-in
 * screen"; a spec about a sign-in that must be REFUSED (bad credentials, a deactivated account)
 * calls this and asserts its own outcome.
 */
export async function submitLogin(
  page: Page,
  credentials: { email: string; password: string },
): Promise<void> {
  watchForThrottling(page);
  await orThrottle(page, async () => {
    await page.goto("/");
    const heading = page.locator(LOGIN_HEADING);
    await expectNamed(heading, "heading", notTheFrameworkSignIn("signing-in", page));
    const email = page.locator(LOGIN_EMAIL);
    await expectNamed(email, "textbox");
    await email.fill(credentials.email);
    const password = page.locator(LOGIN_PASSWORD);
    await expectNamed(password, "textbox");
    await password.fill(credentials.password);
    const submit = page.locator(LOGIN_SUBMIT);
    await expectNamed(submit, "button");
    await submit.click();
  });
}

/**
 * Sign in through the framework's sign-in screen. App-agnostic: that screen and the session are
 * base-profile (the same in every Terp app that keeps the screen, in every locale it ships), so
 * this is the reusable entry point any app's conformance suite composes. Success is the sign-in
 * screen being replaced by the app shell; callers assert their own landing content afterwards.
 *
 * An app that replaces the screen (`renderTerpApp({ login: … })`) signs in from its own specs,
 * by that screen's accessible names, and does not call this; here it fails saying so.
 */
export async function login(
  page: Page,
  credentials: { email: string; password: string } = ADMIN,
): Promise<void> {
  await submitLogin(page, credentials);
  await orThrottle(page, () =>
    expect(page.locator(LOGIN_HEADING)).toHaveCount(0, {
      timeout: 15_000,
    }),
  );
}

/**
 * Sign out through the shell's account menu and assert the session is gone. Base-profile: the
 * user menu (avatar at the bottom of every Terp app's sidebar) opens Settings and Sign out;
 * sign-out revokes the token server-side (ADR 0031), so this is reusable across apps. Success
 * is the app shell being replaced by the framework's sign-in screen, so an app that replaces
 * that screen signs out from its own specs too, and here it fails saying so.
 */
export async function logout(page: Page): Promise<void> {
  watchForThrottling(page);
  await orThrottle(page, async () => {
    const trigger = page.locator(USER_MENU_TRIGGER);
    await expectNamed(trigger, "button");
    await trigger.click();
    const signOut = page.locator(SIGN_OUT);
    await expectNamed(signOut, "menuitem");
    await signOut.click();
    const heading = page.locator(LOGIN_HEADING);
    await expectNamed(heading, "heading", notTheFrameworkSignIn("signed-out", page));
  });
}
