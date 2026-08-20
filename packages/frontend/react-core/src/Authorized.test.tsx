// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Authorized, useHasPermission, usePermissions } from "./Authorized";
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

  it("gates on a named grant, not only rank (ADR 0096)", async () => {
    // The hole this closes: rank was all the wire carried, so a screen whose write needs
    // `definitions.publish` hid by rank as a proxy and handled the 403 anyway.
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const url = (input as Request).url;
        if (url.endsWith("/api/v1/auth/login")) {
          return jsonResponse({ access_token: "token", token_type: "bearer" });
        }
        return jsonResponse({
          id: "u1",
          email: "editor@example.com",
          role_rank: 20,
          role_name: "editor",
          permissions: ["definitions.manage"],
        });
      }),
    );

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <Authorized action="write" permission="definitions.manage">
          <span>held</span>
        </Authorized>
        <Authorized action="write" permission="definitions.publish">
          <span>not held</span>
        </Authorized>
        {/* Rank alone still fails closed even when the grant is held. */}
        <Authorized action="admin" permission="definitions.manage">
          <span>rank too low</span>
        </Authorized>
      </TerpProvider>,
    );

    await waitFor(() => expect(screen.getByText("held")).toBeInTheDocument());
    expect(screen.queryByText("not held")).toBeNull();
    expect(screen.queryByText("rank too low")).toBeNull();
  });

  it("reports no permissions when signed out, and none for an app that grants none", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => new Response("", { status: 401 })),
    );

    function Probe() {
      return (
        <span>{`n=${usePermissions().length} has=${String(useHasPermission("anything"))}`}</span>
      );
    }
    render(
      <TerpProvider baseUrl="https://api.test">
        <Probe />
      </TerpProvider>,
    );

    // Empty rather than undefined, so a screen can read it without guarding first.
    await waitFor(() => expect(screen.getByText("n=0 has=false")).toBeInTheDocument());
  });
});
