import {
  createContext,
  useEffect,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import type {
  Action,
  AuthSession,
  Credentials,
  CurrentUser,
  paths as ContractPaths,
  TerpClient,
  TerpClientFor,
} from "@terpjs/contract";
import { createTerpClient } from "@terpjs/contract";

import {
  canPerform,
  DEFAULT_RANK_THRESHOLDS,
  type RankThresholds,
} from "./capabilities";
import { createAuthClient } from "./createAuthClient";
import {
  completeSsoCallback,
  DEFAULT_SSO_CALLBACK_PATH,
  fetchSsoAuthorizationUrl,
  isSsoCallbackLocation,
  parseSsoCallback,
  type SsoCallbackParams,
} from "./sso";

/**
 * The SSO login session (ADR 0058): `begin` opens a provider flow (navigates the
 * browser to the IdP), and `error` carries a failed callback completion so the
 * login screen can surface it. Only meaningful in apps that mount the OIDC
 * capability; a password-only app simply never calls `begin`.
 */
export interface SsoSession {
  /** Start an SSO login: fetch the IdP authorize URL and navigate to it. */
  begin(provider: string): Promise<void>;
  /** The failure of the last SSO attempt (callback completion), or null. */
  error: unknown;
}

interface TerpContextValue {
  baseUrl: string;
  client: TerpClient;
  auth: AuthSession;
  sso: SsoSession;
}

const TerpContext = createContext<TerpContextValue | null>(null);

export interface TerpProviderProps {
  /** Backend API origin, e.g. "https://api.example.com". */
  baseUrl: string;
  /** Role-rank thresholds for {@link AuthSession.can}; defaults to the bundled ladder. */
  thresholds?: RankThresholds;
  /**
   * SPA path prefix the IdP redirects back to after an SSO login (ADR 0058); the
   * provider completes a `{ssoCallbackPath}/{provider}?code&state` landing on boot.
   * Must match the `redirect_uri` configured on the backend's OIDC providers.
   */
  ssoCallbackPath?: string;
  children: ReactNode;
}

async function loadCurrentUser(client: TerpClient): Promise<CurrentUser> {
  const { data, error } = await client.GET("/api/v1/me/", {});
  if (error || !data) {
    throw new Error("failed to load the current user");
  }
  return data;
}

/**
 * Provides a typed `@terpjs/contract` client and an {@link AuthSession} to the tree. The
 * session implements the contract over the generated client: login exchanges credentials
 * for a token and loads `/me`, logout revokes it (ADR 0031), and `can` gates the UI on
 * the server-validated role rank. The bearer token lives in memory for the provider's
 * lifetime.
 */
export function TerpProvider({
  baseUrl,
  thresholds = DEFAULT_RANK_THRESHOLDS,
  ssoCallbackPath = DEFAULT_SSO_CALLBACK_PATH,
  children,
}: TerpProviderProps) {
  const tokenRef = useRef<string | null>(null);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [ssoError, setSsoError] = useState<unknown>(null);

  // Captured once per provider lifetime (before the URL is cleaned), so a StrictMode
  // double boot effect cannot replay the single-use OIDC state against the backend.
  const ssoPendingRef = useRef<
    { params: SsoCallbackParams | null; atCallback: boolean } | undefined
  >(undefined);
  if (ssoPendingRef.current === undefined) {
    ssoPendingRef.current =
      typeof window === "undefined"
        ? { params: null, atCallback: false }
        : {
            params: parseSsoCallback(window.location, ssoCallbackPath),
            atCallback: isSsoCallbackLocation(window.location, ssoCallbackPath),
          };
  }

  const clearSession = useCallback(() => {
    tokenRef.current = null;
    setUser(null);
  }, []);

  const refreshClient = useMemo(
    () => createTerpClient({ baseUrl, credentials: "include" }),
    [baseUrl],
  );

  // Single-flight: concurrent callers (a StrictMode double boot effect, the 401 middleware
  // racing the boot refresh) share one /refresh round-trip instead of racing the rotation.
  const refreshInFlightRef = useRef<Promise<string | null> | null>(null);

  const refreshAccessToken = useCallback((): Promise<string | null> => {
    const existing = refreshInFlightRef.current;
    if (existing) return existing;
    const attempt = refreshClient
      .POST("/api/v1/auth/refresh", {})
      .then(({ data, error }) => {
        if (error || !data) {
          return null;
        }
        tokenRef.current = data.access_token;
        return data.access_token;
      })
      .catch(() => null)
      .finally(() => {
        refreshInFlightRef.current = null;
      });
    refreshInFlightRef.current = attempt;
    return attempt;
  }, [refreshClient]);

  // One client per provider; its middleware reads the live token from the ref, sends refresh
  // cookies, and on a 401 tries one refresh+replay before clearing the session (ADR 0054/0031).
  const client = useMemo(
    () =>
      createAuthClient(baseUrl, () => tokenRef.current, {
        refreshAccessToken,
        onUnauthorized: clearSession,
      }),
    [baseUrl, clearSession, refreshAccessToken],
  );

  const login = useCallback(
    async (credentials: Credentials): Promise<CurrentUser> => {
      const { data, error } = await client.POST("/api/v1/auth/login", {
        body: credentials,
      });
      if (error || !data) {
        throw new Error("login failed");
      }
      tokenRef.current = data.access_token;
      const me = await loadCurrentUser(client);
      setUser(me);
      return me;
    },
    [client],
  );

  const logout = useCallback(async (): Promise<void> => {
    try {
      await client.POST("/api/v1/auth/logout", {});
    } finally {
      clearSession();
    }
  }, [client, clearSession]);

  const refresh = useCallback(async (): Promise<CurrentUser | null> => {
    const startingToken = tokenRef.current;
    const token = await refreshAccessToken();
    if (!token) {
      if (tokenRef.current === startingToken) clearSession();
      return null;
    }
    const me = await loadCurrentUser(client).catch(() => null);
    if (!me) {
      if (tokenRef.current === token) clearSession();
      return null;
    }
    setUser(me);
    return me;
  }, [client, clearSession, refreshAccessToken]);

  // Finish an in-flight SSO redirect: clean the URL first (the code/state are single-use
  // and must not survive a reload), then exchange them for a normal Terp session.
  const completePendingSso = useCallback(
    async (pending: SsoCallbackParams): Promise<void> => {
      try {
        const token = await completeSsoCallback(client, pending.provider, pending);
        tokenRef.current = token;
        const me = await loadCurrentUser(client);
        setUser(me);
      } catch (error) {
        tokenRef.current = null;
        setSsoError(error);
      }
    },
    [client],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const boot = async (): Promise<void> => {
      const landing = ssoPendingRef.current;
      ssoPendingRef.current = { params: null, atCallback: false };
      if (landing?.atCallback && typeof window !== "undefined") {
        window.history.replaceState(window.history.state, "", "/");
      }
      if (landing?.params) {
        await completePendingSso(landing.params);
        return;
      }
      if (landing?.atCallback) {
        // The IdP redirected back without a usable code (e.g. the user denied
        // consent): a failed SSO attempt, not a normal boot.
        setSsoError(new Error("SSO sign-in was not completed"));
        return;
      }
      await refresh();
    };
    void boot().finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [completePendingSso, refresh]);

  const auth = useMemo<AuthSession>(
    () => ({
      login,
      logout,
      refresh,
      currentUser: () => user,
      loading: () => loading,
      can: (action: Action) =>
        user ? canPerform(user.role_rank, action, thresholds) : false,
    }),
    [login, logout, refresh, user, loading, thresholds],
  );

  const beginSso = useCallback(
    async (provider: string): Promise<void> => {
      setSsoError(null);
      const url = await fetchSsoAuthorizationUrl(client, provider);
      window.location.assign(url);
    },
    [client],
  );

  const sso = useMemo<SsoSession>(
    () => ({ begin: beginSso, error: ssoError }),
    [beginSso, ssoError],
  );

  const value = useMemo<TerpContextValue>(
    () => ({ baseUrl, client, auth, sso }),
    [baseUrl, client, auth, sso],
  );

  return <TerpContext.Provider value={value}>{children}</TerpContext.Provider>;
}

function useTerp(): TerpContextValue {
  const ctx = useContext(TerpContext);
  if (!ctx) {
    throw new Error("useTerpClient / useAuth must be used within a <TerpProvider>");
  }
  return ctx;
}

/**
 * The typed API client, authenticated with the current session token.
 *
 * Pass your app's generated `paths` to type calls to your OWN endpoints. It is the one
 * shared client (the base-profile login / me / logout calls in {@link TerpProvider} use the
 * same instance), re-typed to your contract:
 *
 * ```ts
 * import type { paths } from "./api/schema"; // openapi-typescript output of your backend
 * const client = useTerpClient<paths>();
 * const { data } = await client.GET("/api/v1/invoices/", {});
 * ```
 *
 * The default types the base-profile endpoints bundled in `@terpjs/contract`.
 */
export function useTerpClient<AppPaths extends {} = ContractPaths>(): TerpClientFor<AppPaths> {
  return useTerp().client as unknown as TerpClientFor<AppPaths>;
}

/** @internal The configured backend origin for sanctioned transport hooks. */
export function useTerpBaseUrl(): string {
  return useTerp().baseUrl;
}

/** The current {@link AuthSession}: login / logout / refresh / currentUser / can. */
export function useAuth(): AuthSession {
  return useTerp().auth;
}

/** The current {@link SsoSession}: begin an SSO login, or read the last SSO failure. */
export function useSso(): SsoSession {
  return useTerp().sso;
}
