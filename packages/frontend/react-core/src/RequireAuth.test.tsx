// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RequireAuth } from "./RequireAuth";
import { TerpProvider, useAuth } from "./TerpProvider";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function LogInOnMount() {
  const auth = useAuth();
  useEffect(() => {
    void auth.login({ email: "user@example.com", password: "pw" });
  }, []);
  return null;
}

describe("RequireAuth", () => {
  it("shows the fallback while signed out", async () => {
    render(
      <TerpProvider baseUrl="https://api.test">
        <RequireAuth fallback={<span>please-sign-in</span>}>
          <span>app</span>
        </RequireAuth>
      </TerpProvider>,
    );
    await waitFor(() => expect(screen.getByText("please-sign-in")).toBeInTheDocument());
    expect(screen.queryByText("app")).not.toBeInTheDocument();
  });

  it("shows the pending view while boot refresh is in flight", async () => {
    let finishRefresh!: () => void;
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(
        async () => new Promise<Response>((resolve) => {
          finishRefresh = () => resolve(new Response("{}", { status: 401 }));
        }),
      ),
    );

    render(
      <TerpProvider baseUrl="https://api.test">
        <RequireAuth fallback={<span>please-sign-in</span>} pending={<span>checking</span>}>
          <span>app</span>
        </RequireAuth>
      </TerpProvider>,
    );
    expect(screen.getByText("checking")).toBeInTheDocument();
    expect(screen.queryByText("please-sign-in")).not.toBeInTheDocument();

    finishRefresh();
    await waitFor(() => expect(screen.getByText("please-sign-in")).toBeInTheDocument());
  });

  it("shows children once a user signs in", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "t", token_type: "bearer" });
      }
      return jsonResponse({ id: "1", email: "user@example.com", role_rank: 10, role_name: "viewer" });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RequireAuth fallback={<span>please-sign-in</span>}>
          <span>app</span>
        </RequireAuth>
      </TerpProvider>,
    );

    await waitFor(() => expect(screen.getByText("app")).toBeInTheDocument());
    expect(screen.queryByText("please-sign-in")).not.toBeInTheDocument();
  });
});
