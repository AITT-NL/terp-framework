// @vitest-environment jsdom
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ModuleManifest } from "@terp/contract";
import type { ComponentType } from "react";

import { withAdminArea } from "../bootstrap";
import { buildAppRouter } from "../router";
import { Page } from "../Page";
import { TerpProvider, useAuth } from "../TerpProvider";
import { ToastProvider } from "../toast";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

// --- withAdminArea: the injection rules ------------------------------------- //

describe("withAdminArea", () => {
  const appManifests = (): ModuleManifest[] => [
    { name: "notes", routes: [{ path: "/", view: "NotesList" }], nav: [] },
  ];
  const appViews = (): Record<string, ComponentType> => ({ NotesList: () => null });

  it("appends the packaged admin module by default", () => {
    const { manifests, views } = withAdminArea(appManifests(), appViews(), true);
    const admin = manifests.find((manifest) => manifest.name === "terp-admin");
    expect(admin).toBeDefined();
    expect(admin?.routes.map((route) => route.path)).toContain("/admin");
    expect(admin?.nav?.[0]?.label).toBe("Admin");
    expect(views.TerpAdminHub).toBeDefined();
  });

  it("returns the inputs untouched when disabled", () => {
    const manifests = appManifests();
    const views = appViews();
    const result = withAdminArea(manifests, views, false);
    expect(result.manifests).toBe(manifests);
    expect(result.views).toBe(views);
  });

  it("lets an app route claim a packaged path (that screen is dropped, the rest stay)", () => {
    const manifests = [
      ...appManifests(),
      {
        name: "custom",
        routes: [{ path: "/admin/users", view: "MyUsers" }],
        nav: [],
      },
    ];
    const views = { ...appViews(), MyUsers: (() => null) as ComponentType };
    const merged = withAdminArea(manifests, views, true);
    const admin = merged.manifests.find((manifest) => manifest.name === "terp-admin");
    expect(admin?.routes.map((route) => route.path)).not.toContain("/admin/users");
    expect(admin?.routes.map((route) => route.path)).toContain("/admin/groups");
    expect(merged.views.TerpAdminUsers).toBeUndefined();
    expect(merged.views.MyUsers).toBeDefined();
  });

  it("drops the Admin nav entry when the app claims the hub itself", () => {
    const manifests = [
      ...appManifests(),
      { name: "custom", routes: [{ path: "/admin", view: "MyHub" }], nav: [] },
    ];
    const views = { ...appViews(), MyHub: (() => null) as ComponentType };
    const merged = withAdminArea(manifests, views, true);
    const admin = merged.manifests.find((manifest) => manifest.name === "terp-admin");
    expect(admin?.nav).toEqual([]);
    expect(admin?.routes.map((route) => route.path)).toContain("/admin/users");
  });

  it("refuses a view-id collision that claims no path (a silent drop would dead-link the hub)", () => {
    const manifests = [
      ...appManifests(),
      { name: "custom", routes: [{ path: "/other", view: "TerpAdminUsers" }], nav: [] },
    ];
    const views = { ...appViews(), TerpAdminUsers: (() => null) as ComponentType };
    expect(() => withAdminArea(manifests, views, true)).toThrow(/TerpAdminUsers/);
  });
});

// --- the packaged screens, end to end through the router --------------------- //

function LogInOnMount() {
  const auth = useAuth();
  useEffect(() => {
    void auth.login({ email: "admin@example.com", password: "pw" });
  }, []);
  return null;
}

const emptyPage = { items: [], total: 0, skip: 0, limit: 1 };

function stubAdminFetch() {
  const fetchMock = vi.fn<typeof fetch>(async (input) => {
    const request = input as Request;
    const url = new URL(request.url);
    const path = url.pathname;
    if (path.endsWith("/api/v1/auth/login")) {
      return jsonResponse({ access_token: "t", token_type: "bearer" });
    }
    if (path.endsWith("/api/v1/me/")) {
      return jsonResponse({
        id: "a1",
        email: "admin@example.com",
        role_rank: 30,
        role_name: "admin",
      });
    }
    if (path.endsWith("/api/v1/users/")) {
      // The directory search behind the member picker filters by email substring.
      if (url.searchParams.get("email") === "new.user") {
        return jsonResponse({
          items: [
            {
              id: "u9",
              email: "new.user@example.com",
              role: 10,
              is_active: true,
              created_at: "2026-07-01T10:00:00Z",
              updated_at: "2026-07-01T10:00:00Z",
              version: 1,
            },
          ],
          total: 1,
          skip: 0,
          limit: 20,
        });
      }
      return jsonResponse({
        items: [
          {
            id: "u1",
            email: "jane.doe@example.com",
            role: 20,
            is_active: true,
            created_at: "2026-07-01T10:00:00Z",
            updated_at: "2026-07-01T10:00:00Z",
            version: 1,
          },
        ],
        total: 7,
        skip: 0,
        limit: 10,
      });
    }
    if (path.endsWith("/members") && request.method === "POST") {
      return jsonResponse({
        id: "m2",
        group_id: "g1",
        user_id: "u9",
        email: "new.user@example.com",
        created_at: "2026-07-02T10:00:00Z",
      });
    }
    if (path.endsWith("/members")) {
      return jsonResponse({
        items: [
          {
            id: "m1",
            group_id: "g1",
            user_id: "u1",
            email: "jane.doe@example.com",
            created_at: "2026-07-01T10:00:00Z",
          },
        ],
        total: 1,
        skip: 0,
        limit: 200,
      });
    }
    if (path.endsWith("/api/v1/groups/g1")) {
      return jsonResponse({
        id: "g1",
        name: "Finance",
        description: "money",
        member_count: 1,
        version: 1,
        created_at: "2026-07-01T10:00:00Z",
        updated_at: "2026-07-01T10:00:00Z",
      });
    }
    if (path.endsWith("/api/v1/groups/")) {
      return jsonResponse({ ...emptyPage, total: 3 });
    }
    if (path.endsWith("/api/v1/audit/")) {
      return jsonResponse(emptyPage);
    }
    return jsonResponse(emptyPage);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderAdminApp(initialPath: string, roleRank = 30) {
  const manifests: ModuleManifest[] = [
    { name: "notes", routes: [{ path: "/", view: "NotesList" }], nav: [] },
  ];
  const views: Record<string, ComponentType> = {
    NotesList: () => <Page title="Notes">notes</Page>,
  };
  const merged = withAdminArea(manifests, views, true);
  const router = buildAppRouter(merged.manifests, {
    views: merged.views,
    title: "Terp",
    history: createMemoryHistory({ initialEntries: [initialPath] }),
  });
  const fetchMock = stubAdminFetch();
  if (roleRank !== 30) {
    fetchMock.mockImplementation(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "t", token_type: "bearer" });
      }
      return jsonResponse({
        id: "v1",
        email: "viewer@example.com",
        role_rank: roleRank,
        role_name: "viewer",
      });
    });
  }
  render(
    <TerpProvider baseUrl="https://api.test">
      <ToastProvider>
        <LogInOnMount />
        <RouterProvider router={router} />
      </ToastProvider>
    </TerpProvider>,
  );
  return fetchMock;
}

describe("the packaged admin area", () => {
  it("serves the hub at /admin with cards into users, groups and audit", async () => {
    renderAdminApp("/admin");
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "Admin" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: /Users/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Groups/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Audit log/ })).toBeInTheDocument();
    // Live totals from the limit=1 probes reach the cards.
    await waitFor(() => expect(screen.getByText("7")).toBeInTheDocument());
    expect(screen.getByText("3")).toBeInTheDocument();
    // The sidebar carries the single admin-gated entry.
    expect(screen.getByRole("link", { name: "Admin" })).toBeInTheDocument();
  });

  it("serves the users screen with the provision form and the listed accounts", async () => {
    renderAdminApp("/admin/users");
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "Users" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Provision user" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("jane.doe@example.com")).toBeInTheDocument());
    // The overview breadcrumbs back to the hub.
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent("Admin");
  });

  it("serves the group detail: API-resolved member emails and a searched member picker", async () => {
    const fetchMock = renderAdminApp("/admin/groups/g1");
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "Finance" })).toBeInTheDocument(),
    );
    // The member row shows the email the backend resolved (no client-side directory).
    await waitFor(() => expect(screen.getByText("jane.doe@example.com")).toBeInTheDocument());

    // Typing searches the directory server-side (debounced) and suggests matches…
    fireEvent.change(screen.getByPlaceholderText("Email"), {
      target: { value: "new.user" },
    });
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          (input as Request).url.includes("email=new.user"),
        ),
      ).toBe(true),
    );

    // …and submitting the full address resolves it to the account id for the POST.
    fireEvent.change(screen.getByPlaceholderText("Email"), {
      target: { value: "new.user@example.com" },
    });
    fireEvent.submit(screen.getByRole("button", { name: "Add member" }).closest("form")!);
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) => {
          const request = input as Request;
          return request.method === "POST" && request.url.endsWith("/groups/g1/members");
        }),
      ).toBe(true),
    );
  });

  it("denies the area to a non-admin (nav hidden, route refused)", async () => {
    renderAdminApp("/admin", 10);
    await waitFor(() =>
      expect(screen.getByText("You do not have access to this page.")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
  });
});
