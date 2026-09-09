import type { components } from "./schema";

/**
 * The auth/session contract every frontend stack implements identically (design §7.1,
 * item 4): token handling, the current user, and UI permission gating that honours the
 * backend roles. Implementations wrap the generated `@terpjs/contract` client; they never
 * invent their own auth semantics.
 *
 * Wire types (`Credentials`, `AccessToken`) are reused from the generated schema, so the
 * contract cannot drift from the backend auth surface.
 */

/** Login body — the backend `LoginRequest` (email + password). */
export type Credentials = components["schemas"]["LoginRequest"];

/** Login response — the backend `AccessToken` (`access_token` + `token_type`). */
export type AccessToken = components["schemas"]["AccessToken"];

/**
 * The signed-in user as the UI needs it — the backend `CurrentUser`, returned by
 * `GET /api/v1/me` (ADR 0044) and reused from the generated schema so it cannot drift.
 * The role is on the wire as the numeric `role_rank` (the comparable primitive the UI
 * gates on) plus a display `role_name` (ADR 0004 / 0022).
 */
export type CurrentUser = components["schemas"]["CurrentUser"];

/** Coarse capability the UI gates on; the adapter maps it to the backend role tiers. */
export type Action = "read" | "write" | "admin";

export interface AuthSession {
  /** Exchange credentials for a session; resolves to the signed-in user. */
  login(credentials: Credentials): Promise<CurrentUser>;
  /** End the session (revokes the token at the backend, ADR 0031). */
  logout(): Promise<void>;
  /** Re-validate the stored token; resolves to the user, or null if signed out. */
  refresh(): Promise<CurrentUser | null>;
  /** The cached current user, or null when signed out. */
  currentUser(): CurrentUser | null;
  /** True while the provider is resolving an existing session (e.g. boot refresh). */
  loading(): boolean;
  /**
   * True when the boot session check got no answer at all — the backend did not
   * respond before the timeout, or the connection failed.
   *
   * Distinct from `currentUser() === null`, which is the *answer* "nobody is signed
   * in". Collapsing the two is what made a dead backend indistinguishable from a
   * signed-out visitor, and since the fetch to a dead proxy target never settles
   * rather than failing, the symptom was a permanently blank page with nothing in the
   * console. `RequireAuth` renders its `unreachable` slot on this.
   */
  unreachable(): boolean;
  /**
   * UI gate: may the current user perform `action`? (Honours the backend roles.)
   *
   * `module` names the module the action happens in. Pass it and a per-module rung the caller
   * holds there raises the answer, which is what the server's guard does (ADR 0121) — omit it
   * and the gate is the global rank alone. Omitting it on a module's own screen is the shape
   * that hid a module the caller could actually reach.
   */
  can(action: Action, module?: string): boolean;
}
