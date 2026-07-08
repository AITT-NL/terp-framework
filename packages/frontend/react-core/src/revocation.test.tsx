// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RequireAuth } from "./RequireAuth";
import { TerpProvider, useAuth, useTerpClient } from "./TerpProvider";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** Login + the first `/me` succeed; every later authenticated request 401s (a server-revoked session). */
function revokingFetch() {
  let meCalls = 0;
  return vi.fn<typeof fetch>(async (input) => {
    const url = (input as Request).url;
    if (url.endsWith("/api/v1/auth/login")) {
      return json({ access_token: "t", token_type: "bearer" });
    }
    if (url.endsWith("/api/v1/me/")) {
      meCalls += 1;
      if (meCalls === 1) {
        return json({ id: "1", email: "e@acme.test", role_rank: 20, role_name: "editor" });
      }
    }
    return json({ code: "authentication_required", detail: "token revoked" }, 401);
  });
}

function LogInOnMount() {
  const auth = useAuth();
  useEffect(() => {
    void auth.login({ email: "e@acme.test", password: "pw" });
  }, []);
  return null;
}

function DoWork() {
  const client = useTerpClient();
  return (
    <button type="button" onClick={() => void client.GET("/api/v1/me/", {})}>
      Do work
    </button>
  );
}

describe("session revocation (ADR 0031)", () => {
  it("clears the session and falls back to login when an authenticated request 401s", async () => {
    vi.stubGlobal("fetch", revokingFetch());

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RequireAuth fallback={<p>Please sign in</p>}>
          <DoWork />
        </RequireAuth>
      </TerpProvider>,
    );

    // After login the authenticated app (its "Do work" action) is shown.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Do work" })).toBeInTheDocument(),
    );

    // The token is revoked server-side: the next authenticated request 401s, which clears the
    // session so the app falls back to the login screen — not a signed-in shell over empty data.
    fireEvent.click(screen.getByRole("button", { name: "Do work" }));

    await waitFor(() => expect(screen.getByText("Please sign in")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Do work" })).not.toBeInTheDocument();
  });
});
