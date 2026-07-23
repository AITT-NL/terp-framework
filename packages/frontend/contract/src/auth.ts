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
  /** UI gate: may the current user perform `action`? (Honours the backend roles.) */
  can(action: Action): boolean;
}
