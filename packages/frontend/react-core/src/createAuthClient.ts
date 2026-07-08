import { createTerpClient, type TerpClient } from "@terp/contract";

/** Returns the current bearer token, or null when signed out. */
export type TokenGetter = () => string | null;

/** Optional hooks for the authenticated client. */
export interface AuthClientOptions {
  /**
   * Try to exchange the httpOnly refresh cookie for a fresh access token (ADR 0054). Called once
   * when an authenticated, non-auth endpoint returns 401; a returned token is installed by the
   * provider, then the original request is replayed with the new bearer.
   */
  refreshAccessToken?: () => Promise<string | null>;
  /**
   * Called when a request that carried a token is rejected with 401 and refresh also failed — i.e.
   * the session was revoked server-side or the refresh cookie is absent/expired. The provider
   * clears the session here so the app falls back to the login screen instead of leaving a
   * signed-in shell over empty data.
   */
  onUnauthorized?: () => void;
}

/**
 * Create a {@link TerpClient} that attaches `Authorization: Bearer <token>` to every
 * request, reading the live token from `getToken`. A token set after login (or cleared
 * on logout) is honoured without re-creating the client, and unauthenticated requests
 * simply omit the header. Cookies are sent too, so the httpOnly refresh token can ride
 * `/auth/refresh` without exposing it to JS. A 401 to an authenticated non-auth request
 * first tries one refresh+replay; if that fails, `onUnauthorized` clears the stale session.
 */
export function createAuthClient(
  baseUrl: string,
  getToken: TokenGetter,
  options: AuthClientOptions = {},
): TerpClient {
  const client = createTerpClient({ baseUrl, credentials: "include" });
  const retryRequests = new Map<string, Request>();
  let refreshInFlight: Promise<string | null> | null = null;
  client.use({
    onRequest({ request, id, schemaPath }) {
      const token = getToken();
      if (token) {
        request.headers.set("Authorization", `Bearer ${token}`);
      }
      if (token && !isAuthEndpoint(schemaPath)) {
        retryRequests.set(id, request.clone());
      }
      return request;
    },
    async onResponse({ id, response, schemaPath }) {
      const retryRequest = retryRequests.get(id);
      retryRequests.delete(id);
      if (
        response.status !== 401 ||
        getToken() === null ||
        isAuthEndpoint(schemaPath) ||
        retryRequest === undefined
      ) {
        return response;
      }
      const refreshed = await refreshOnce(options.refreshAccessToken, () => refreshInFlight, (next) => {
        refreshInFlight = next;
      });
      if (refreshed) {
        retryRequest.headers.set("Authorization", `Bearer ${refreshed}`);
        const replayed = await fetch(retryRequest);
        if (replayed.status === 401) {
          // The subject was revoked between refresh and replay: the session is dead even
          // though the refresh succeeded — clear it so the app falls back to login.
          options.onUnauthorized?.();
        }
        return replayed;
      }
      options.onUnauthorized?.();
      return response;
    },
    onError({ id }) {
      // A network failure produces no onResponse; drop the retained clone here so the
      // retry map cannot grow unboundedly under flaky connectivity.
      retryRequests.delete(id);
    },
  });
  return client;
}

function refreshOnce(
  refreshAccessToken: AuthClientOptions["refreshAccessToken"],
  getInFlight: () => Promise<string | null> | null,
  setInFlight: (next: Promise<string | null> | null) => void,
): Promise<string | null> {
  if (!refreshAccessToken) return Promise.resolve(null);
  const existing = getInFlight();
  if (existing) return existing;
  const next = refreshAccessToken().finally(() => setInFlight(null));
  setInFlight(next);
  return next;
}

function isAuthEndpoint(schemaPath: string): boolean {
  return (
    schemaPath === "/api/v1/auth/login" ||
    schemaPath === "/api/v1/auth/logout" ||
    schemaPath === "/api/v1/auth/refresh"
  );
}
