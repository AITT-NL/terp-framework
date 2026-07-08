// @vitest-environment jsdom
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ModuleManifest } from "@terp/contract";

import { buildAppRouter } from "./router";
import { Page } from "./Page";
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
    void auth.login({ email: "editor@example.com", password: "pw" });
  }, []);
  return null;
}

const manifests: ModuleManifest[] = [
  {
    name: "notes",
    routes: [{ path: "/notes", view: "NotesList" }],
    nav: [{ label: "Notes", to: "/notes" }],
  },
  {
    name: "users",
    routes: [{ path: "/users", view: "UsersList", role: "admin" }],
    nav: [{ label: "Users", to: "/users", role: "admin" }],
  },
];

const views = {
  NotesList: () => <Page title="Notes view">notes body</Page>,
  UsersList: () => <Page title="Users view">users body</Page>,
};

describe("buildAppRouter", () => {
  it("renders the matched view in the shell with a role-filtered nav", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "t", token_type: "bearer" });
      }
      return jsonResponse({ id: "1", email: "editor@example.com", role_rank: 20, role_name: "editor" });
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = buildAppRouter(manifests, {
      views,
      title: "Terp",
      history: createMemoryHistory({ initialEntries: ["/notes"] }),
    });

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Notes view" })).toBeInTheDocument(),
    );
    // Editor (rank 20) sees the Notes nav but not the admin-only Users nav.
    expect(screen.getByRole("link", { name: "Notes" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
  });

  it("shows a sign-out control for the signed-in user and revokes the token on click", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "t", token_type: "bearer" });
      }
      if (url.endsWith("/api/v1/auth/logout")) {
        return new Response(null, { status: 204 });
      }
      return jsonResponse({ id: "1", email: "editor@example.com", role_rank: 20, role_name: "editor" });
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = buildAppRouter(manifests, {
      views,
      title: "Terp",
      history: createMemoryHistory({ initialEntries: ["/notes"] }),
    });

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );

    // The sidebar's user menu shows the signed-in user's email; sign-out lives inside it.
    await waitFor(() => expect(screen.getByText("editor@example.com")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Account menu" }));
    // Clicking sign-out revokes the token server-side (ADR 0031).
    fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          (input as Request).url.endsWith("/api/v1/auth/logout"),
        ),
      ).toBe(true),
    );
  });

  it("rejects a route whose view id was not collected", () => {
    expect(() =>
      buildAppRouter(
        [{ name: "missing", routes: [{ path: "/missing", view: "MissingView" }] }],
        {
          views: {},
          title: "Terp",
          history: createMemoryHistory({ initialEntries: ["/missing"] }),
        },
      ),
    ).toThrow(/missing view/);
  });

  it("refuses a routed view that skips the page archetypes (fail closed)", async () => {
    // The runtime half of the page-archetype control: a view rendering bare markup (no Page /
    // OverviewPage / DetailPage / HubPage in its tree) is refused after mount, not shown.
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "t", token_type: "bearer" });
      }
      return jsonResponse({ id: "1", email: "editor@example.com", role_rank: 20, role_name: "editor" });
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = buildAppRouter(
      [{ name: "bare", routes: [{ path: "/bare", view: "BareView" }], nav: [] }],
      {
        views: { BareView: () => <h1>Bare view</h1> },
        title: "Terp",
        history: createMemoryHistory({ initialEntries: ["/bare"] }),
      },
    );

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );

    // The bare view mounts, the post-mount check bites, and the screen is torn down.
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Bare view" })).not.toBeInTheDocument(),
    );
  });

  it("accepts a view whose page archetype lands on a follow-up commit", async () => {
    // A view may frame one commit late (e.g. a lazy inner component resolving); the grace
    // window tolerates it while a view that never frames is still refused.
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "t", token_type: "bearer" });
      }
      return jsonResponse({ id: "1", email: "editor@example.com", role_rank: 20, role_name: "editor" });
    });
    vi.stubGlobal("fetch", fetchMock);

    function LateFramedView() {
      const [ready, setReady] = useState(false);
      useEffect(() => setReady(true), []);
      return ready ? <Page title="Late view">late body</Page> : null;
    }

    const router = buildAppRouter(
      [{ name: "late", routes: [{ path: "/late", view: "LateView" }], nav: [] }],
      {
        views: { LateView: LateFramedView },
        title: "Terp",
        history: createMemoryHistory({ initialEntries: ["/late"] }),
      },
    );

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Late view" })).toBeInTheDocument(),
    );
  });

  it("mounts the built-in profile page; the user menu's Settings opens it", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "t", token_type: "bearer" });
      }
      return jsonResponse({ id: "1", email: "editor@example.com", role_rank: 20, role_name: "editor" });
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = buildAppRouter(manifests, {
      views,
      title: "Terp",
      history: createMemoryHistory({ initialEntries: ["/notes"] }),
    });

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );

    await waitFor(() => expect(screen.getByText("editor@example.com")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Account menu" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Settings" }));

    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "Profile" })).toBeInTheDocument(),
    );
    // The identity comes from the server-validated session (email + role), framed by a Page.
    expect(screen.getByText("editor (20)")).toBeInTheDocument();
  });

  it("lets an app manifest claim /profile over the built-in page", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "t", token_type: "bearer" });
      }
      return jsonResponse({ id: "1", email: "editor@example.com", role_rank: 20, role_name: "editor" });
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = buildAppRouter(
      [{ name: "custom", routes: [{ path: "/profile", view: "CustomProfile" }], nav: [] }],
      {
        views: { CustomProfile: () => <Page title="Custom profile">custom body</Page> },
        title: "Terp",
        history: createMemoryHistory({ initialEntries: ["/profile"] }),
      },
    );

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Custom profile" })).toBeInTheDocument(),
    );
  });
});
