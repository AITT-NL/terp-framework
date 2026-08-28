import { expect, type APIResponse, type Page } from "@playwright/test";

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
 * Sign in through the real login screen. App-agnostic: the login screen and session are
 * base-profile (identical in every Terp app), so this is the reusable entry point any app's
 * conformance suite composes. Success is the sign-in screen being replaced by the app shell;
 * callers assert their own landing content afterwards.
 */
export async function login(
  page: Page,
  credentials: { email: string; password: string } = ADMIN,
): Promise<void> {
  watchForThrottling(page);
  await orThrottle(page, async () => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });
  // By LABEL, not by placeholder. The login fields were placeholder-only until the labels
  // landed, and a placeholder was the only handle they had — which is the same defect from
  // the other side: a name that vanishes the moment a user types is not a name. Selecting
  // the way a user perceives the field is also what keeps this suite honest about
  // accessibility, since a field with no accessible name now fails here rather than being
  // reachable by a workaround.
  await page.getByLabel("Email", { exact: true }).fill(credentials.email);
  await page.getByLabel("Password", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await orThrottle(page, () =>
    expect(page.getByRole("heading", { name: "Sign in" })).toHaveCount(0, {
      timeout: 15_000,
    }),
  );
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
  watchForThrottling(page);
  await orThrottle(page, async () => {
    await page.locator('[data-terp="user-menu"] [data-terp="menu-trigger"]').click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });
}
