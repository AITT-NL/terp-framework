// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Authorized } from "./Authorized";
import { TerpProvider, useAuth } from "./TerpProvider";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

function LogInOnMount() {
  const auth = useAuth();
  useEffect(() => {
    void auth.login({ email: "editor@example.com", password: "pw" });
  }, []);
  return null;
}

describe("Authorized", () => {
  it("reveals content per the logged-in user's role (editor can write, not admin)", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "token", token_type: "bearer" });
      }
      return jsonResponse({
        id: "u1",
        email: "editor@example.com",
        role_rank: 20,
        role_name: "editor",
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <Authorized action="write">
          <span>can-write</span>
        </Authorized>
        <Authorized action="admin" fallback={<span>no-admin</span>}>
          <span>admin-only</span>
        </Authorized>
      </TerpProvider>,
    );

    await waitFor(() => expect(screen.getByText("can-write")).toBeInTheDocument());
    expect(screen.getByText("no-admin")).toBeInTheDocument();
    expect(screen.queryByText("admin-only")).not.toBeInTheDocument();
  });
});
