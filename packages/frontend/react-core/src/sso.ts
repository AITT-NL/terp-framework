import type { TerpClient, TerpClientFor } from "@terpjs/contract";

import { unwrap } from "./unwrap";

/**
 * The SSO seam over the OIDC capability's SPA-shaped endpoints (ADR 0058):
 *
 * - `GET  /api/v1/oidc/{provider}/authorize` opens a flow and returns the IdP
 *   authorize URL the client navigates to; and
 * - `POST /api/v1/oidc/{provider}/callback` relays what the IdP appended to the
 *   redirect URI and mints a normal Terp session (`access_token` + the same
 *   httpOnly refresh cookie a password login sets).
 *
 * The endpoints are app-mounted (the OIDC capability is opt-in), so they are not
 * part of the baked base-profile contract; the wire shapes below mirror the
 * capability's DTOs, which the shipped capability keeps stable.
 */

/** Response of `GET /oidc/{provider}/authorize` — the URL to navigate to. */
interface AuthorizationRequest {
  provider: string;
  authorization_url: string;
}

/** Response of `POST /oidc/{provider}/callback` — a normal Terp access token. */
interface SsoAccessToken {
  access_token: string;
  token_type: string;
}

/** The OIDC capability's SPA endpoints, typed for the shared contract client. */
interface OidcPaths {
  "/api/v1/oidc/{provider}/authorize": {
    get: {
      parameters: { path: { provider: string }; query?: never; header?: never; cookie?: never };
      requestBody?: never;
      responses: {
        200: {
          headers: { [name: string]: unknown };
          content: { "application/json": AuthorizationRequest };
        };
      };
    };
  };
  "/api/v1/oidc/{provider}/callback": {
    post: {
      parameters: { path: { provider: string }; query?: never; header?: never; cookie?: never };
      requestBody: { content: { "application/json": { code: string; state: string } } };
      responses: {
        200: {
          headers: { [name: string]: unknown };
          content: { "application/json": SsoAccessToken };
        };
      };
    };
  };
}

/** A configured SSO provider, as the login screen presents it. */
export interface SsoProvider {
  /** Provider name as mounted on the backend (the `{provider}` path segment). */
  name: string;
  /** Display label for the provider button (defaults to the name). */
  label?: string;
}

/** Default SPA path prefix the IdP redirects back to: `/auth/callback/{provider}`. */
export const DEFAULT_SSO_CALLBACK_PATH = "/auth/callback";

function oidcClient(client: TerpClient): TerpClientFor<OidcPaths> {
  return client as unknown as TerpClientFor<OidcPaths>;
}

/** Open an SSO flow: fetch the IdP authorize URL for `provider`. */
export async function fetchSsoAuthorizationUrl(
  client: TerpClient,
  provider: string,
): Promise<string> {
  const data = unwrap(
    await oidcClient(client).GET("/api/v1/oidc/{provider}/authorize", {
      params: { path: { provider } },
    }),
  );
  return data.authorization_url;
}

/** Finish an SSO flow: relay the IdP's `code`/`state` and receive a Terp access token. */
export async function completeSsoCallback(
  client: TerpClient,
  provider: string,
  payload: { code: string; state: string },
): Promise<string> {
  const data = unwrap(
    await oidcClient(client).POST("/api/v1/oidc/{provider}/callback", {
      params: { path: { provider } },
      body: { code: payload.code, state: payload.state },
    }),
  );
  return data.access_token;
}

/** What the IdP appended to the redirect URI, parsed from the current location. */
export interface SsoCallbackParams {
  provider: string;
  code: string;
  state: string;
}

/** True when `pathname` sits under the SSO callback prefix (an IdP redirect landed here). */
export function isSsoCallbackLocation(
  location: { pathname: string },
  callbackPath: string = DEFAULT_SSO_CALLBACK_PATH,
): boolean {
  const prefix = callbackPath.endsWith("/") ? callbackPath : `${callbackPath}/`;
  return location.pathname.startsWith(prefix);
}

/**
 * Parse an in-flight SSO redirect out of a location. Returns the provider + code/state
 * when `pathname` is `{callbackPath}/{provider}` and both query params are present,
 * else null (a normal boot, or an IdP error redirect carrying no code).
 */
export function parseSsoCallback(
  location: { pathname: string; search: string },
  callbackPath: string = DEFAULT_SSO_CALLBACK_PATH,
): SsoCallbackParams | null {
  const prefix = callbackPath.endsWith("/") ? callbackPath : `${callbackPath}/`;
  if (!location.pathname.startsWith(prefix)) {
    return null;
  }
  const provider = decodeURIComponent(location.pathname.slice(prefix.length).replace(/\/+$/, ""));
  if (provider.length === 0 || provider.includes("/")) {
    return null;
  }
  const query = new URLSearchParams(location.search);
  const code = query.get("code");
  const state = query.get("state");
  if (!code || !state) {
    return null;
  }
  return { provider, code, state };
}
