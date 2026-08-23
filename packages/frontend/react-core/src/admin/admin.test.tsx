// @vitest-environment jsdom
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ModuleManifest } from "@terpjs/contract";
import type { ComponentType } from "react";

import { withAdminArea } from "../bootstrap";
import type { AdminAreaSections } from "../bootstrap";
import { formatDateTime } from "../format";
import { buildAppRouter } from "../router";
import { Page } from "../Page";
import { TerpProvider, useAuth } from "../TerpProvider";
import { ToastProvider } from "../toast";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
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
    expect(admin?.routes.map((route) => route.path)).toEqual(expect.arrayContaining([
      "/admin/users/new",
      "/admin/users/$userId",
      "/admin/groups/new",
      "/admin/groups/$groupId",
    ]));
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

  it("ships a capability-selective area from a sections object", () => {
    const { manifests, views } = withAdminArea(appManifests(), appViews(), {
      groups: false,
    });
    const admin = manifests.find((manifest) => manifest.name === "terp-admin");
    const paths = admin?.routes.map((route) => route.path) ?? [];
    expect(paths).toContain("/admin");
    expect(paths).toContain("/admin/users");
    expect(paths).toContain("/admin/audit");
    expect(paths.some((path) => path.startsWith("/admin/groups"))).toBe(false);
    expect(views.TerpAdminGroups).toBeUndefined();
    expect(views.TerpAdminGroupCreate).toBeUndefined();
    expect(views.TerpAdminHub).toBeDefined();
    // Omitted flags default to true: an empty object is the full area.
    const full = withAdminArea(appManifests(), appViews(), {});
    const fullAdmin = full.manifests.find((manifest) => manifest.name === "terp-admin");
    expect(fullAdmin?.routes).toHaveLength(8);
    expect(full.views.TerpAdminHub).toBe(withAdminArea(appManifests(), appViews(), true).views.TerpAdminHub);
  });

  it("keeps the Admin nav and hub when only some sections are dropped", () => {
    const { manifests } = withAdminArea(appManifests(), appViews(), {
      users: false,
      groups: false,
    });
    const admin = manifests.find((manifest) => manifest.name === "terp-admin");
    expect(admin?.nav?.[0]?.label).toBe("Admin");
    expect(admin?.routes.map((route) => route.path)).toEqual(["/admin", "/admin/audit"]);
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
    if (path.endsWith("/api/v1/users/u1")) {
      if (request.method === "PATCH") {
        return jsonResponse({
          id: "u1",
          email: "jane.doe@example.com",
          role: 10,
          is_active: true,
          created_at: "2026-07-01T10:00:00Z",
          updated_at: "2026-07-02T10:00:00Z",
          version: 2,
        });
      }
      return jsonResponse({
        id: "u1",
        email: "jane.doe@example.com",
        role: 20,
        is_active: true,
        created_at: "2026-07-01T10:00:00Z",
        updated_at: "2026-07-01T10:00:00Z",
        version: 1,
      });
    }
    if (path.endsWith("/api/v1/users/u2")) {
      return jsonResponse({
        id: "u2",
        email: "new.account@example.com",
        role: 10,
        is_active: true,
        created_at: "2026-07-02T10:00:00Z",
        updated_at: "2026-07-02T10:00:00Z",
        version: 1,
      });
    }
    if (path.endsWith("/api/v1/users/")) {
      if (request.method === "POST") {
        return jsonResponse({
          id: "u2",
          email: "new.account@example.com",
          role: 10,
          is_active: true,
          created_at: "2026-07-02T10:00:00Z",
          updated_at: "2026-07-02T10:00:00Z",
          version: 1,
        });
      }
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
    if (path.endsWith("/api/v1/groups/g2")) {
      return jsonResponse({
        id: "g2",
        name: "Operations",
        description: "Daily operations",
        member_count: 0,
        version: 1,
        created_at: "2026-07-02T10:00:00Z",
        updated_at: "2026-07-02T10:00:00Z",
      });
    }
    if (path.endsWith("/api/v1/groups/")) {
      if (request.method === "POST") {
        return jsonResponse({
          id: "g2",
          name: "Operations",
          description: "Daily operations",
          member_count: 0,
          version: 1,
          created_at: "2026-07-02T10:00:00Z",
          updated_at: "2026-07-02T10:00:00Z",
        });
      }
      return jsonResponse({
        items: [
          {
            id: "g1",
            name: "Finance",
            description: "money",
            member_count: 1,
            version: 1,
            created_at: "2026-07-01T10:00:00Z",
            updated_at: "2026-07-01T10:00:00Z",
          },
        ],
        total: 3,
        skip: 0,
        limit: 10,
      });
    }
    if (path.endsWith("/api/v1/audit/")) {
      // One row, and it earns its place rather than padding the fixture: the audit screen's
      // expanded panel is the only place `admin-payload` renders, so with an empty page that
      // <pre> — and the `tabIndex` that keeps its scroll container reachable — could not be
      // asserted anywhere. The comment below this fixture used to say exactly that.
      return jsonResponse({
        items: [
          {
            id: "e1",
            created_at: "2026-08-21T09:30:00Z",
            action: "update",
            target_type: "sync_definition",
            target_id: "4d2c1b7e-0000-4000-8000-000000000001",
            actor_id: "9f2c1b7e-0000-4000-8000-000000000002",
            request_id: "req_01HQ8ZK4",
            payload: { window: "02:00-04:00 UTC", retention_days: 90 },
          },
        ],
        total: 1,
        skip: 0,
        limit: 25,
      });
    }
    return jsonResponse(emptyPage);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderAdminApp(
  initialPath: string,
  roleRank = 30,
  adminArea: boolean | AdminAreaSections = true,
) {
  const manifests: ModuleManifest[] = [
    { name: "notes", routes: [{ path: "/", view: "NotesList" }], nav: [] },
  ];
  const views: Record<string, ComponentType> = {
    NotesList: () => <Page title="Notes">notes</Page>,
  };
  const merged = withAdminArea(manifests, views, adminArea);
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
  return { fetchMock, router };
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

  it("serves a capability-selective hub: dropped sections lose card, route and stat call", async () => {
    const { fetchMock } = renderAdminApp("/admin", 30, { groups: false });
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "Admin" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: /Users/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Audit log/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Groups/ })).not.toBeInTheDocument();
    // The users stat still arrives; the groups endpoint is never probed (its
    // capability may not be mounted at all).
    await waitFor(() => expect(screen.getByText("7")).toBeInTheDocument());
    const probed = fetchMock.mock.calls.map((call) => (call[0] as Request).url);
    expect(probed.some((url) => url.includes("/api/v1/groups/"))).toBe(false);
  });

  it("uses the users overview action and clickable rows for dedicated pages", async () => {
    renderAdminApp("/admin/users");
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "Users" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Provision user" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("jane.doe@example.com")).toBeInTheDocument());
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent("Admin");

    fireEvent.click(screen.getByText("jane.doe@example.com"));
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "jane.doe@example.com" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Reset password" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent("Users");
  });

  it("provisions a user on a dedicated create page and redirects to its detail", async () => {
    const { fetchMock } = renderAdminApp("/admin/users");
    await screen.findByRole("heading", { level: 1, name: "Users" });
    fireEvent.click(screen.getByRole("button", { name: "Provision user" }));
    await screen.findByRole("heading", { level: 1, name: "Provision user" });

    // The form's measure is a sheet rule now (ADR 0094), and this is the only gate on it:
    // no admin screen has a specimen, so nothing pictures these three surfaces. What a test
    // can hold is that the marked element is there and styles nothing itself; that the rule
    // exists is held by styles.test.ts, and its values are a verbatim copy of the object
    // this replaced.
    const form = document.querySelector('[data-terp="admin-form"]');
    expect(form).not.toBeNull();
    expect(form?.getAttribute("style")).toBeNull();

    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "new.account@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "strong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Provision user" }));

    await screen.findByRole("heading", { level: 1, name: "new.account@example.com" });
    expect(fetchMock.mock.calls.some(([input]) => {
      const request = input as Request;
      return request.method === "POST" && request.url.endsWith("/api/v1/users/");
    })).toBe(true);
  });

  it("puts a 422's reason under the field it names instead of floating it in a toast", async () => {
    // The failure path had no test at all, which is how the framework shipped `Field.error` with
    // no production consumer for two releases: the rendering half was gated, the producing half
    // did not exist, and nothing exercised the seam between them.
    //
    // The two assertions are deliberately different strings. `Field` shows the server's bare
    // `msg`; the toast shows the joined `path: msg` sentence that `unwrap` has always produced.
    // Asserting only the first would stay green if BOTH appeared, which is the failure mode worth
    // guarding — three channels for one problem is what this commit set out to stop.
    const { fetchMock } = renderAdminApp("/admin/users/new");
    await screen.findByRole("heading", { level: 1, name: "Provision user" });
    // A uniqueness violation, not a malformed address, and the choice is not incidental: the
    // browser rejects a malformed one before any request leaves, so `type="email"` would have
    // caught it and the POST would never happen (jsdom enforces that too, which is how the first
    // draft of this test failed). What is left over after the four HTML constraint attributes
    // have done their work is exactly what the server alone knows, and that is the class of
    // reason this whole channel exists to carry.
    const passthrough = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input as Request;
      if (request.method === "POST" && request.url.endsWith("/api/v1/users/")) {
        return jsonResponse(
          { detail: [{ loc: ["body", "email"], msg: "Email address is already registered" }] },
          422,
        );
      }
      return passthrough(input, init);
    });

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "taken@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "strong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Provision user" }));

    const shown = await screen.findByText("Email address is already registered");
    expect(shown.getAttribute("data-terp")).toBe("field-error");
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText("email: Email address is already registered")).toBeNull();
    // Still on the create page: a rejected submit must not navigate away from the input it is
    // asking the user to fix.
    expect(screen.getByRole("heading", { level: 1, name: "Provision user" })).toBeInTheDocument();
  });

  it("confirms lifecycle mutations from the user detail action slot", async () => {
    const { fetchMock } = renderAdminApp("/admin/users/u1");
    await screen.findByRole("heading", { level: 1, name: "jane.doe@example.com" });
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Make viewer" }));
    expect(screen.getByRole("dialog", { name: "Make viewer" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => (input as Request).method === "PATCH")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([input]) => (input as Request).method === "PATCH")).toBe(true),
    );
  });

  it("clears user mutation state when navigating between detail records in place", async () => {
    const { router } = renderAdminApp("/admin/users/u1");
    await screen.findByRole("heading", { level: 1, name: "jane.doe@example.com" });
    fireEvent.click(screen.getByRole("button", { name: "Reset password" }));
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "must-not-cross-records" },
    });
    expect(screen.getByRole("dialog", { name: /Reset password/ })).toBeInTheDocument();

    await act(async () => {
      await router.navigate({
        to: "/admin/users/$userId",
        params: { userId: "u2" },
      });
    });
    await screen.findByRole("heading", { level: 1, name: "new.account@example.com" });
    expect(screen.queryByRole("dialog", { name: /Reset password/ })).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("must-not-cross-records")).not.toBeInTheDocument();
  });

  it("uses the groups overview action and rows for create/detail navigation", async () => {
    renderAdminApp("/admin/groups");
    await screen.findByRole("heading", { level: 1, name: "Groups" });
    await screen.findByText("Finance");

    fireEvent.click(screen.getByRole("button", { name: "Create group" }));
    await screen.findByRole("heading", { level: 1, name: "Create group" });
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent("Groups");
  });

  it("serves the group detail: API-resolved member emails and a searched member picker", async () => {
    const { fetchMock } = renderAdminApp("/admin/groups/g1");
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

  it("renders its dates in the framework's shape rather than the browser's default", async () => {
    // No admin screen has a specimen, so nothing pictures these cells and nothing asserted their
    // text either — which is how seven of them sat on `toLocaleDateString()` / `toLocaleString()`
    // with no locale argument through two releases.
    //
    // The negative half is the half with teeth: both spellings render the same instant, so an
    // assertion on the new one alone would stay green if the cell had never been converted and
    // the runner's default happened to agree. They differ in shape, not in value.
    const when = "2026-08-21T09:30:00Z";
    renderAdminApp("/admin/audit");
    expect(await screen.findByText(formatDateTime(when, undefined))).toBeInTheDocument();
    expect(screen.queryByText(new Date(when).toLocaleString())).toBeNull();
  });

  it("puts an unresolvable email under the member input rather than in a toast", async () => {
    // Not a 422 — the directory simply has no match — but it is a statement about the email the
    // user just typed, on a form whose only input is that email. Answering the server's reasons
    // on the field and this one above it would be a distinction the user cannot perceive, so the
    // routing follows what the message is about rather than where it came from.
    renderAdminApp("/admin/groups/g1");
    await screen.findByRole("heading", { level: 1, name: "Finance" });
    fireEvent.change(screen.getByPlaceholderText("Email"), {
      target: { value: "nobody@example.com" },
    });
    fireEvent.submit(screen.getByRole("button", { name: "Add member" }).closest("form")!);
    const shown = await screen.findByText("No account matches that email.");
    expect(shown.getAttribute("data-terp")).toBe("field-error");
  });

  it("marks the detail sections it no longer styles inline", async () => {
    // The second of the three surfaces the admin views used to style at the call site. Same
    // reasoning as the create form above: markers plus the absence of a style attribute,
    // because no admin screen has a specimen.
    //
    // The third, the audit payload, has its own test below now. It had none for a while, and
    // the reason was recorded here rather than left implicit: the audit fixture served an empty
    // page, so no row existed to expand and the <pre> never rendered in any test. That stayed
    // true until the payload gained a `tabIndex` — a claim about the real component that no
    // workbench specimen can make, because the specimen writes its own markup.
    renderAdminApp("/admin/groups/g1");
    const headings = await waitFor(() => {
      const found = document.querySelectorAll('[data-terp="admin-section-title"]');
      expect(found.length).toBe(2);
      return found;
    });
    for (const heading of headings) {
      expect(heading.tagName).toBe("H2");
      expect(heading.getAttribute("style")).toBeNull();
    }
  });

  it("keeps the audit payload's scroll container reachable by keyboard", async () => {
    // The gate for the SC 2.1.1 fix, and it has to be here rather than in the workbench.
    // `admin-payload` declares `overflow-x: auto`, so a wide payload is a scroll container, and
    // a scroll container no keyboard can reach is what axe reports as
    // `scrollable-region-focusable`. The workbench specimen renders its own `<pre>` with its own
    // literal `tabIndex`, so every lane there would stay green with the attribute deleted from
    // this component — the specimen would be asserting its own markup back to itself. This
    // reads the packaged screen.
    renderAdminApp("/admin/audit");
    // Expanding the row is what renders the panel; the trigger is the row's own expand control.
    const expand = await waitFor(() => {
      const found = document.querySelector('[data-terp="dataview-expand-cell"] button');
      expect(found).not.toBeNull();
      return found as HTMLButtonElement;
    });
    fireEvent.click(expand);
    const payload = await waitFor(() => {
      const found = document.querySelector('[data-terp="admin-payload"]');
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(payload.tagName).toBe("PRE");
    expect(payload.tabIndex).toBe(0);
    // And still no inline style — the third of the three surfaces the admin views used to
    // style at the call site, which is what the note above refers to.
    expect(payload.getAttribute("style")).toBeNull();
  });

  it("clears group destructive state when navigating between detail records in place", async () => {
    const { router } = renderAdminApp("/admin/groups/g1");
    await screen.findByRole("heading", { level: 1, name: "Finance" });
    fireEvent.click(screen.getAllByRole("button", { name: "More actions" })[0]!);
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete group" }));
    expect(screen.getByRole("dialog", { name: /Delete group/ })).toBeInTheDocument();

    await act(async () => {
      await router.navigate({
        to: "/admin/groups/$groupId",
        params: { groupId: "g2" },
      });
    });
    await screen.findByRole("heading", { level: 1, name: "Operations" });
    expect(screen.queryByRole("dialog", { name: /Delete group/ })).not.toBeInTheDocument();
  });

  it("denies the area to a non-admin (nav hidden, route refused)", async () => {
    renderAdminApp("/admin", 10);
    await waitFor(() =>
      expect(screen.getByText("You do not have access to this page.")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
  });
});
