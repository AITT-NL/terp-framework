// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LoginView } from "./LoginView";
import { TerpProvider, useAuth } from "./TerpProvider";
import { parseSsoCallback } from "./sso";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

function CurrentEmail() {
  const auth = useAuth();
  return <p>{auth.currentUser()?.email ?? "signed out"}</p>;
}

describe("parseSsoCallback", () => {
  it("parses a provider callback landing", () => {
    expect(
      parseSsoCallback({ pathname: "/auth/callback/dex", search: "?code=c1&state=s1" }),
    ).toEqual({ provider: "dex", code: "c1", state: "s1" });
  });

  it("returns null for a normal boot or a code-less landing", () => {
    expect(parseSsoCallback({ pathname: "/", search: "" })).toBeNull();
    expect(parseSsoCallback({ pathname: "/auth/callback/dex", search: "?error=denied" })).toBeNull();
    expect(parseSsoCallback({ pathname: "/auth/callback/", search: "?code=c&state=s" })).toBeNull();
    expect(
      parseSsoCallback({ pathname: "/auth/callback/a/b", search: "?code=c&state=s" }),
    ).toBeNull();
  });
});

describe("SSO login (ADR 0058)", () => {
  it("renders provider buttons and navigates to the IdP authorize URL", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const request = input as Request;
      if (request.url.endsWith("/api/v1/auth/refresh")) return json({}, 401);
      if (request.url.endsWith("/api/v1/oidc/dex/authorize")) {
        return json({ provider: "dex", authorization_url: "https://idp.test/authorize?x=1" });
      }
      return json({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    const assign = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({
      ...window.location,
      assign,
      pathname: "/",
      search: "",
    } as unknown as Location);

    render(
      <TerpProvider baseUrl="https://api.test">
        <LoginView ssoProviders={[{ name: "dex", label: "Dex" }]} />
      </TerpProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Continue with Dex" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://idp.test/authorize?x=1"));
  });

  it("completes the callback landing into a signed-in session and cleans the URL", async () => {
    window.history.replaceState({}, "", "/auth/callback/dex?code=c1&state=s1");
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const request = input as Request;
      if (request.url.endsWith("/api/v1/oidc/dex/callback")) {
        expect(await request.clone().json()).toEqual({ code: "c1", state: "s1" });
        return json({ access_token: "sso-token", token_type: "bearer" });
      }
      if (request.url.endsWith("/api/v1/me/")) {
        expect(request.headers.get("authorization")).toContain("sso-token");
        return json({ id: "1", email: "sso@acme.test", role_rank: 10, role_name: "viewer" });
      }
      return json({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <TerpProvider baseUrl="https://api.test">
        <CurrentEmail />
      </TerpProvider>,
    );

    await waitFor(() => expect(screen.getByText("sso@acme.test")).toBeInTheDocument());
    expect(window.location.pathname).toBe("/");
    // The single-use code/state must not be replayed by a second boot pass.
    const callbackCalls = fetchMock.mock.calls.filter((call) =>
      (call[0] as Request).url.endsWith("/api/v1/oidc/dex/callback"),
    );
    expect(callbackCalls).toHaveLength(1);
  });

  it("surfaces a failed callback on the login screen instead of signing in", async () => {
    window.history.replaceState({}, "", "/auth/callback/dex?code=bad&state=bad");
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const request = input as Request;
        if (request.url.endsWith("/api/v1/oidc/dex/callback")) {
          return json({ detail: "Authentication failed", code: "authentication_failed" }, 401);
        }
        return json({}, 404);
      }),
    );

    render(
      <TerpProvider baseUrl="https://api.test">
        <LoginView ssoProviders={[{ name: "dex" }]} />
      </TerpProvider>,
    );

    await waitFor(() =>
      expect(screen.getByText("Single sign-on failed. Try again.")).toBeInTheDocument(),
    );
    expect(window.location.pathname).toBe("/");
  });
});
