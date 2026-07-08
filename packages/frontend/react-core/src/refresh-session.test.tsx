// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RequireAuth } from "./RequireAuth";
import { TerpProvider, useAuth, useTerpClient } from "./TerpProvider";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function me(token: string) {
  return json({ id: "1", email: `${token}@acme.test`, role_rank: 20, role_name: "editor" });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function CurrentEmail() {
  const auth = useAuth();
  return <p>{auth.currentUser()?.email ?? "signed out"}</p>;
}

function DoWork() {
  const client = useTerpClient();
  return (
    <button type="button" onClick={() => void client.GET("/api/v1/me/", {})}>
      Do work
    </button>
  );
}

describe("refresh-token sessions (ADR 0054)", () => {
  it("silently restores the session on boot from the httpOnly refresh cookie", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const request = input as Request;
        if (request.url.endsWith("/api/v1/auth/refresh")) {
          return json({ access_token: "restored", token_type: "bearer" });
        }
        if (request.url.endsWith("/api/v1/me/")) {
          return me("restored");
        }
        return json({}, 404);
      }),
    );

    render(
      <TerpProvider baseUrl="https://api.test">
        <RequireAuth fallback={<p>Please sign in</p>}>
          <CurrentEmail />
        </RequireAuth>
      </TerpProvider>,
    );

    await waitFor(() => expect(screen.getByText("restored@acme.test")).toBeInTheDocument());
    expect(screen.queryByText("Please sign in")).not.toBeInTheDocument();
  });

  it("refreshes and retries an expired access token without logging out", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const request = input as Request;
      if (request.url.endsWith("/api/v1/auth/refresh")) {
        return json({ access_token: "fresh", token_type: "bearer" });
      }
      if (request.url.endsWith("/api/v1/auth/login")) {
        return json({ access_token: "expired", token_type: "bearer" });
      }
      if (request.url.endsWith("/api/v1/me/")) {
        const auth = request.headers.get("Authorization");
        if (auth === "Bearer expired") return json({ detail: "expired" }, 401);
        return me("fresh");
      }
      return json({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    function LogIn() {
      const auth = useAuth();
      return (
        <button
          type="button"
          onClick={() => void auth.login({ email: "e@acme.test", password: "pw" })}
        >
          Sign in
        </button>
      );
    }

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogIn />
        <RequireAuth fallback={<p>Please sign in</p>}>
          <DoWork />
        </RequireAuth>
      </TerpProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Do work" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Do work" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Do work" })).toBeInTheDocument());
    expect(screen.queryByText("Please sign in")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => (input as Request).headers.get("Authorization") === "Bearer fresh")).toBe(true);
  });
});
