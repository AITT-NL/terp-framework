// @vitest-environment jsdom
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ModuleManifest } from "@terpjs/contract";
import type { ComponentType } from "react";

import { withAdminArea } from "../bootstrap";
import type { AdminAreaSections } from "../bootstrap";
import { formatDateTime } from "../format";
import { LOCALE_EN, LOCALE_NL, LocaleProvider } from "../locale";
import type { LocaleProviderProps } from "../locale";
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
  heldAccessModel = null;
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
    expect(admin?.nav?.[0]?.label).toEqual({ framework: "admin" });
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
    expect(fullAdmin?.routes).toHaveLength(9);
    expect(full.views.TerpAdminHub).toBe(withAdminArea(appManifests(), appViews(), true).views.TerpAdminHub);
  });

  it("keeps the Admin nav and hub when only some sections are dropped", () => {
    const { manifests } = withAdminArea(appManifests(), appViews(), {
      users: false,
      groups: false,
    });
    const admin = manifests.find((manifest) => manifest.name === "terp-admin");
    expect(admin?.nav?.[0]?.label).toEqual({ framework: "admin" });
    expect(admin?.routes.map((route) => route.path)).toEqual([
      "/admin",
      "/admin/audit",
      "/admin/access",
    ]);

    // The access screen is section-gated too, and for a reason rather than for symmetry: it
    // reads `GET /api/v1/access/model`, which exists only where the access capability is
    // mounted, so an app without it would otherwise ship a nav entry leading to a 404.
    const withoutAccess = withAdminArea(appManifests(), appViews(), { access: false });
    const trimmed = withoutAccess.manifests.find((m) => m.name === "terp-admin");
    expect(trimmed?.routes.map((route) => route.path)).not.toContain("/admin/access");
    expect(withoutAccess.views.TerpAdminAccess).toBeUndefined();
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

/** A day of the hub's activity fixture: `offset` days after 5 September 2026. */
function activityDay(offset: number, count: number) {
  return { date: new Date(Date.UTC(2026, 8, 5 + offset)).toISOString().slice(0, 10), count };
}

/**
 * The trail's activity as the hub reads it: thirty days ending 4 October. The last week sums to
 * 21 and the week before to 16, so the figure reads 21, 5 up. The days before the last week
 * count 1, 2, 3, 4 in turn: with one change on each, any seven of them summed to 7, and a
 * comparison read a day off still printed the right delta.
 */
const LAST_WEEK = [5, 4, 6, 3, 2, 0, 1];
const ACTIVITY = {
  time_zone: "Europe/Amsterdam",
  days: Array.from({ length: 30 }, (_, index) =>
    activityDay(index, index >= 23 ? LAST_WEEK[index - 23]! : (index % 4) + 1),
  ),
  previous_days: Array.from({ length: 30 }, (_, index) => activityDay(index - 30, 2)),
  by_action: [
    { action: "updated", count: 30 },
    { action: "created", count: 12 },
    { action: "deleted", count: 2 },
  ],
  by_target_type: [{ target_type: "User", count: 44 }],
  total: 44,
};

/**
 * Held open, the access-model response does not land. Set by the one test that needs the
 * role ladder to still be in flight while it looks at the form, so the window in which the
 * submit control is disabled is a fact rather than a timing accident. Cleared in `afterEach`.
 */
let heldAccessModel: Promise<void> | null = null;

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
    if (path.endsWith("/api/v1/access/model")) {
      if (heldAccessModel) await heldAccessModel;
      // The admin screens read the role ladder from the access model rather than from three
      // literals in `roles.ts`, so the mock has to answer it. Declaring a fourth rung here is
      // deliberate: it is what proves the screens render the ladder the *app* declares, which
      // a viewer/editor/admin fixture could never observe.
      return jsonResponse({
        // Deliberately NOT in rank order. The endpoint sorts, and the hook sorts again — so a
        // pre-sorted fixture cannot observe either, and removing the hook's sort broke no test
        // at all until this fixture was scrambled. A ladder rendered out of order is a real
        // defect: the strip's whole legibility comes from authority reading left to right.
        roles: [
          { name: "admin", rank: 30 },
          { name: "viewer", rank: 10 },
          { name: "approver", rank: 25 },
          { name: "editor", rank: 20 },
        ],
        permissions: [],
        modules: [],
      });
    }
    if (path.includes("/api/v1/access/subjects/")) {
      // The assignment panel on every detail screen reads this. Answered with a real, empty
      // payload rather than left to the page fallback: the panel treats a failed read as
      // "the rungs are unknown" and refuses to render its strips, which is correct behaviour
      // and would otherwise turn every detail-screen test into a test of that error path.
      return jsonResponse({
        subject_id: path.split("/").pop(),
        via: [],
        permissions: [],
        module_roles: [],
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
      // The hub counts its active accounts as a total under the status filter.
      if (url.searchParams.get("is_active") === "true") {
        return jsonResponse({ items: [], total: 5, skip: 0, limit: 1 });
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
    if (path.endsWith("/api/v1/audit/activity")) {
      return jsonResponse(ACTIVITY);
    }
    if (path.endsWith("/api/v1/audit/")) {
      // One row, and it earns its place rather than padding the fixture: the audit screen's
      // expanded panel is the only place the payload renders, so with an empty page that
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

/** An English-source app opened in Dutch. */
const DUTCH = { locales: { en: LOCALE_EN, nl: LOCALE_NL }, defaultLocale: "nl" };

function renderAdminApp(
  initialPath: string,
  roleRank = 30,
  adminArea: boolean | AdminAreaSections = true,
  locale?: Pick<LocaleProviderProps, "locales" | "defaultLocale">,
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
  const app = (
    <TerpProvider baseUrl="https://api.test">
      <ToastProvider>
        <LogInOnMount />
        <RouterProvider router={router} />
      </ToastProvider>
    </TerpProvider>
  );
  render(
    locale === undefined ? (
      app
    ) : (
      <LocaleProvider locales={locale.locales} defaultLocale={locale.defaultLocale}>
        {app}
      </LocaleProvider>
    ),
  );
  return { fetchMock, router };
}

/**
 * The create form's submit control, waited on until it is actually clickable.
 *
 * `UserCreate` gates the only control that reaches the POST on
 * `creating || ladderLoading || role === ""`, and `role` is still `""` in the commit where
 * `ladderLoading` first clears — the effect that picks the ladder's lowest rung runs after
 * it. So the button is disabled for one commit longer than the access-model fetch takes,
 * while the page heading renders before either. Awaiting the heading and then clicking
 * submits nothing at all: jsdom raises no submit event for a click on a disabled control,
 * and the test then fails several lines later on whatever was waiting for the POST's
 * result, as "unable to find element" pointing at the wrong line.
 *
 * A control disabled on an ambient async load has to give a test something deterministic
 * to wait on. This is that thing, and it is the condition that actually gates the click
 * rather than a proxy for it.
 */
/** A figure on the page, read by its label: its value, caption, delta and whether it leads. */
function figure(label: string) {
  const stat = [...document.querySelectorAll('[data-terp="stat"]')].find(
    (node) => node.querySelector('[data-terp="stat-label"]')?.textContent === label,
  );
  if (stat === undefined) return undefined;
  return {
    value: stat.querySelector('[data-terp="stat-value"]')?.textContent,
    caption: stat.querySelector('[data-terp="stat-caption"]')?.textContent,
    delta: stat.querySelector('[data-terp="stat-change"]')?.textContent,
    headline: stat.hasAttribute("data-headline"),
  };
}

async function enabledSubmitControl(): Promise<HTMLElement> {
  const control = await screen.findByRole("button", { name: "Provision user" });
  await waitFor(() => expect(control).toBeEnabled());
  return control;
}

describe("the packaged admin area", () => {
  it("serves the hub at /admin as a dashboard: the figures, the areas, then the trail", async () => {
    const { fetchMock } = renderAdminApp("/admin");
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "Admin" })).toBeInTheDocument(),
    );
    for (const area of [/Users/, /Groups/, /Audit log/, /^Access/]) {
      expect(screen.getByRole("link", { name: area })).toBeInTheDocument();
    }
    // The summary band's figures, each read by its label: the active accounts as a total under
    // the status filter, with the rest deactivated; the groups; and the trail's last week
    // against the week before, from one activity read.
    await waitFor(() => expect(figure("Changes, last 7 days")?.value).toBe("21"));
    expect(figure("Active accounts")).toMatchObject({ value: "5", caption: "2 deactivated", headline: true });
    expect(figure("Groups")?.value).toBe("3");
    // 21 against the 16 of the seven days just before. Mutation: those seven read a day off.
    expect(figure("Changes, last 7 days")?.delta).toMatch(/(^|\D)5(\D|$)/);
    // Then the trail per day against the days before, and the kinds of change in the app's words.
    expect(screen.getByText("Changes per day")).toBeInTheDocument();
    expect(screen.getByText("Changes by kind, last 30 days")).toBeInTheDocument();
    expect(screen.getAllByText("Changed").length).toBeGreaterThan(0);
    const reads = fetchMock.mock.calls.map((call) => new URL((call[0] as Request).url));
    const activity = reads.find((url) => url.pathname.endsWith("/api/v1/audit/activity"))!;
    expect(activity.searchParams.get("days")).toBe("30");
    expect(activity.searchParams.get("time_zone")).toBe(
      Intl.DateTimeFormat().resolvedOptions().timeZone,
    );
    // The sidebar carries the single admin-gated entry.
    expect(screen.getByRole("link", { name: "Admin" })).toBeInTheDocument();
  });

  it("serves a capability-selective hub: dropped sections lose card, figure and read", async () => {
    const { fetchMock } = renderAdminApp("/admin", 30, { groups: false, audit: false });
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "Admin" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: /Users/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Groups/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Audit log/ })).not.toBeInTheDocument();
    // The users figure still arrives; the groups and the trail are never read (their
    // capabilities may not be mounted at all), and the audit section takes its charts along.
    await waitFor(() => expect(figure("Active accounts")?.value).toBe("5"));
    expect(figure("Groups")).toBeUndefined();
    expect(figure("Changes, last 7 days")).toBeUndefined();
    expect(screen.queryByText("Changes per day")).not.toBeInTheDocument();
    const probed = fetchMock.mock.calls.map((call) => (call[0] as Request).url);
    expect(probed.some((url) => url.includes("/api/v1/groups/"))).toBe(false);
    expect(probed.some((url) => url.includes("/api/v1/audit/"))).toBe(false);
  });

  it("keeps every other figure when one read fails (ADR 0171)", async () => {
    const { fetchMock } = renderAdminApp("/admin");
    const answer = fetchMock.getMockImplementation()!;
    // The failing read lands last, after the others have drawn their figures, so a failure
    // that took the page's other reads down with it shows here rather than being overwritten.
    let fail!: () => void;
    const failing = new Promise<void>((resolve) => (fail = resolve));
    fetchMock.mockImplementation(async (input, init) => {
      if (!new URL((input as Request).url).pathname.endsWith("/api/v1/groups/")) {
        return answer(input, init);
      }
      await failing;
      return jsonResponse({ detail: "unavailable" }, 503);
    });
    await waitFor(() => expect(figure("Changes, last 7 days")?.value).toBe("21"));
    await waitFor(() => expect(figure("Active accounts")?.value).toBe("5"));
    await act(async () => {
      fail();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    // Mutation: the reads awaited together behind one catch, so one failure dashed them all.
    expect(figure("Changes, last 7 days")?.value).toBe("21");
    expect(figure("Active accounts")?.value).toBe("5");
    expect(figure("Groups")?.value).toBe("—");
  });

  it("draws the days before as the comparison, not the last thirty again", async () => {
    renderAdminApp("/admin");
    const chart = await screen.findByRole("figure", { name: "Changes per day" });
    const comparison = within(chart)
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("cell").at(-1)!.textContent);
    // Every day before counts 2 in the fixture; the last thirty never do all at once.
    expect(comparison).toHaveLength(30);
    expect(new Set(comparison)).toEqual(new Set(["2"]));
  });

  it("counts the trail in the viewer's zone, whatever the host running the test is in", async () => {
    const real = Intl.DateTimeFormat.prototype.resolvedOptions;
    vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockImplementation(function (
      this: Intl.DateTimeFormat,
    ) {
      return { ...real.call(this), timeZone: "Pacific/Chatham" };
    });
    const { fetchMock } = renderAdminApp("/admin");
    await waitFor(() => expect(figure("Changes, last 7 days")?.value).toBe("21"));
    const activity = fetchMock.mock.calls
      .map((call) => new URL((call[0] as Request).url))
      .find((url) => url.pathname.endsWith("/api/v1/audit/activity"))!;
    expect(activity.searchParams.get("time_zone")).toBe("Pacific/Chatham");
  });

  it("counts in UTC rather than drawing nothing when the server refuses the viewer's zone", async () => {
    const real = Intl.DateTimeFormat.prototype.resolvedOptions;
    vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockImplementation(function (
      this: Intl.DateTimeFormat,
    ) {
      return { ...real.call(this), timeZone: "Etc/Unknown" };
    });
    const { fetchMock } = renderAdminApp("/admin");
    const answer = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => {
      const url = new URL((input as Request).url);
      return url.pathname.endsWith("/api/v1/audit/activity") &&
        url.searchParams.get("time_zone") === "Etc/Unknown"
        ? jsonResponse({ detail: "'Etc/Unknown' is not a time zone this server knows." }, 400)
        : answer(input, init);
    });
    // Mutation: no second read, and the figure keeps its dash with both charts gone.
    await waitFor(() => expect(figure("Changes, last 7 days")?.value).toBe("21"));
    expect(screen.getByRole("figure", { name: "Changes per day" })).toBeInTheDocument();
    const zones = fetchMock.mock.calls
      .map((call) => new URL((call[0] as Request).url))
      .filter((url) => url.pathname.endsWith("/api/v1/audit/activity"))
      .map((url) => url.searchParams.get("time_zone"));
    expect(zones).toEqual(["Etc/Unknown", "UTC"]);
  });

  it("lays the area cards out on as many tracks as there are cards", async () => {
    // Two cards on a fixed three left a blank third column; one card took a third of the row.
    renderAdminApp("/admin", 30, { groups: false, audit: false });
    const users = await screen.findByRole("link", { name: /Users/ });
    expect(users.closest('[data-terp="grid"]')).toHaveAttribute("data-template", "1:1");
  });

  it("never counts fewer than no deactivated accounts", async () => {
    // The total and the active count are two reads; an account made between them made -1.
    const { fetchMock } = renderAdminApp("/admin", 30, { groups: false, audit: false });
    const answer = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => {
      const url = new URL((input as Request).url);
      return url.pathname.endsWith("/api/v1/users/") && url.searchParams.get("is_active") === "true"
        ? jsonResponse({ items: [], total: 8, skip: 0, limit: 1 })
        : answer(input, init);
    });
    await waitFor(() => expect(figure("Active accounts")?.value).toBe("8"));
    expect(figure("Active accounts")?.caption).toBe("0 deactivated");
  });

  it("titles a user being read by nothing yet, then by the user, and by the user on a return (ADR 0173)", async () => {
    const { fetchMock, router } = renderAdminApp("/admin/users/u1");
    const answer = fetchMock.getMockImplementation()!;
    let release!: () => void;
    let held: Promise<void> = new Promise((resolve) => (release = resolve));
    fetchMock.mockImplementation(async (input, init) => {
      const request = input as Request;
      if (new URL(request.url).pathname.endsWith("/api/v1/users/u1") && request.method === "GET") {
        await held;
      }
      return answer(input, init);
    });
    // While the user is read: a placeholder, never the parent's name as a stand-in title.
    const loading = await screen.findByRole("heading", { level: 1 });
    expect(loading).toHaveTextContent("Loading...");
    expect(loading).not.toHaveTextContent("Users");
    await act(async () => release());
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("jane.doe@example.com"),
    );
    // Away and back, and this time the read never answers: the trail still knows the place.
    held = new Promise(() => {});
    await act(async () => {
      await router.navigate({ to: "/admin/users" });
    });
    await act(async () => {
      await router.navigate({ to: "/admin/users/u1" });
    });
    // The detail's own trail, where Users is an ancestor link again.
    const trail = await screen.findByRole("navigation", { name: "Breadcrumb" });
    await waitFor(() => expect(within(trail).getByRole("link", { name: "Users" })).toBeInTheDocument());
    // Mutation: no memory in the shell, which put the placeholder back on every visit.
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("jane.doe@example.com");
    expect(document.querySelector('[data-terp="breadcrumbs-pending"]')).toBeNull();
  });

  it("titles a group being read by nothing yet, never by its parent", async () => {
    const { fetchMock } = renderAdminApp("/admin/groups/g1");
    const answer = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => {
      const request = input as Request;
      if (new URL(request.url).pathname.endsWith("/api/v1/groups/g1") && request.method === "GET") {
        return new Promise<Response>(() => {});
      }
      return answer(input, init);
    });
    const heading = await screen.findByRole("heading", { level: 1 });
    // Mutation: `record?.name ?? strings.adminGroups`, the parent's name as a stand-in title.
    expect(heading).toHaveTextContent("Loading...");
    expect(heading).not.toHaveTextContent("Groups");
  });

  it("drops the access card with the access section, the one a full hub always drew", async () => {
    // The selective hub replaced the full one only when users, groups or audit was dropped, so
    // `{ access: false }` alone removed the route and kept the card that leads to it.
    renderAdminApp("/admin", 30, { access: false });
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "Admin" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: /Users/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Groups/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Audit log/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^Access/ })).not.toBeInTheDocument();
  });

  it("uses the users overview action and clickable rows for dedicated pages", async () => {
    renderAdminApp("/admin/users");
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "Users" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Provision user" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("jane.doe@example.com")).toBeInTheDocument());
    // The status column is the quiet form (ADR 0169 §5): a dot before its word, toned by the
    // account's state. Mutation: drop `status` from the column, and the dot is gone.
    const active = screen.getAllByText("Active")[0]!.closest('[data-terp="dataview-status"]')!;
    expect(active.querySelector('[data-terp="dataview-status-dot"]')).toHaveAttribute(
      "data-tone",
      "success",
    );
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent("Admin");

    fireEvent.click(screen.getByText("jane.doe@example.com"));
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "jane.doe@example.com" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Reset password" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent("Users");
  });

  it("keeps the create form's submit control disabled until the declared ladder arrives", async () => {
    // The pin under `enabledSubmitControl`, and the reason the four submitting tests below
    // cannot go back to awaiting the heading. With the ladder held in flight, the heading is
    // up and the only control that reaches the POST is disabled — so a click there raises no
    // submit event at all in jsdom, and the test would fail much later, on whatever was
    // waiting for the POST's result and with a message naming that instead. This holds the
    // window itself: disabled while the ladder is outstanding, enabled once it lands. It
    // does not hold which of the two gates (`ladderLoading`, `role === ""`) is doing it —
    // either one alone produces the window, and both have to go for the race to.
    let releaseLadder: () => void = () => {};
    heldAccessModel = new Promise<void>((resolve) => {
      releaseLadder = resolve;
    });
    renderAdminApp("/admin/users/new");

    await screen.findByRole("heading", { level: 1, name: "Provision user" });
    const submit = screen.getByRole("button", { name: "Provision user" });
    expect(submit).toBeDisabled();

    releaseLadder();
    await waitFor(() => expect(submit).toBeEnabled());
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
    fireEvent.click(await enabledSubmitControl());

    await screen.findByRole("heading", { level: 1, name: "new.account@example.com" });
    expect(fetchMock.mock.calls.some(([input]) => {
      const request = input as Request;
      return request.method === "POST" && request.url.endsWith("/api/v1/users/");
    })).toBe(true);
  });

  it("offers the ladder the app declares, not the three ranks the framework ships", async () => {
    // `roles.ts` used to return ranks 10/20/30 as literals, so an app that declared a fourth
    // rung got a three-rung admin UI while ADR 0022 promised the role model was the app's.
    // The ladder now comes from `GET /api/v1/access/model`, and the fixture declares
    // `approver` at 25 precisely so this can observe it: a viewer/editor/admin fixture would
    // pass against the old literals too.
    const { fetchMock } = renderAdminApp("/admin/users/new");
    await screen.findByRole("heading", { level: 1, name: "Provision user" });

    // Waited on the rung itself, not the heading: the heading resolves before the model
    // fetch settles, and asserting then would have been asserting on an empty ladder.
    await screen.findByRole("option", { name: "approver" });
    const select = screen.getByLabelText("Role") as HTMLSelectElement;
    const offered = [...select.options].map((option) => [option.value, option.textContent]);
    expect(offered).toEqual([
      ["10", "Viewer"],
      ["20", "Editor"],
      // No framework translation exists for a rung the app invented, so it renders under the
      // name its author gave it — which beats the `rank 25` the old rank-only fallback showed.
      ["25", "approver"],
      ["30", "Administrator"],
    ]);

    // And the form starts on the least privileged *declared* rung. Asserted through the
    // request body rather than `select.value`, which cannot observe it: with no option
    // matching the state, HTML's own selectedness algorithm shows the first one anyway, so a
    // value assertion passed even against a default of 99. The posted rank is the thing that
    // decides what the account actually gets.
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "new.account@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "strong-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Provision user" }));
    await screen.findByRole("heading", { level: 1, name: "new.account@example.com" });

    const posted = fetchMock.mock.calls.find(([input]) => {
      const request = input as Request;
      return request.method === "POST" && request.url.endsWith("/api/v1/users/");
    });
    const body = (await (posted![0] as Request).json()) as { role: number };
    expect(body.role).toBe(10);
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
    fireEvent.click(await enabledSubmitControl());

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
    // Waited on, not reached for: the rung this item offers comes from the access model, so
    // the menu opens empty of it until that fetch lands. Same race as `enabledSubmitControl`
    // guards, one screen over.
    fireEvent.click(await screen.findByRole("menuitem", { name: "Make viewer" }));
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
    // Group sizes as bars against the largest shown, each still printed (ADR 0169 §5).
    // Mutation: drop `bar` from the column, and no meter is named for it.
    expect(screen.getAllByRole("meter", { name: "Members" }).length).toBeGreaterThan(0);

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

  it("still says something when the 422 names a field the form does not render", async () => {
    // The hole in the obvious version of this pattern: a non-empty `fields` suppressed the toast
    // on the way out, and if no key matched an input, the state it set was read by nothing. The
    // user pressed Save and NOTHING happened — no field lit up, no message, no navigation. A
    // failed write that reports nothing is worse than the floating toast it replaced.
    //
    // This also proves the sibling test's `queryByText(...).toBeNull()` is not vacuous: the toast
    // really does render the joined `path: msg` sentence as findable text, so an assertion that
    // it is absent is an assertion about something that could otherwise have been there.
    const { fetchMock } = renderAdminApp("/admin/users/new");
    await screen.findByRole("heading", { level: 1, name: "Provision user" });
    const passthrough = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input as Request;
      if (request.method === "POST" && request.url.endsWith("/api/v1/users/")) {
        return jsonResponse(
          { detail: [{ loc: ["body", "organization_id"], msg: "Not allowed for this tenant" }] },
          422,
        );
      }
      return passthrough(input, init);
    });

    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "new.account@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "strong-password" } });
    fireEvent.click(await enabledSubmitControl());

    expect(
      await screen.findByText("organization_id: Not allowed for this tenant"),
    ).toBeInTheDocument();
    // And nothing was marked invalid, because none of these inputs is the one the server meant.
    expect(screen.getByLabelText("Email")).not.toHaveAttribute("aria-invalid");
    expect(screen.getByLabelText("Password")).not.toHaveAttribute("aria-invalid");
  });

  it("shows the field it can and still toasts the reason it cannot, when a 422 names both", async () => {
    // The mixed envelope is the case the `leftover` flag exists for, and the only one that
    // distinguishes it: with no renderable reason at all the toast fires anyway because `shown` is
    // empty, so a mutation neutering `leftover` stayed green until this test existed. Here `email`
    // finds its input and `organization_id` does not, and BOTH have to reach the user.
    const { fetchMock } = renderAdminApp("/admin/users/new");
    await screen.findByRole("heading", { level: 1, name: "Provision user" });
    const passthrough = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input as Request;
      if (request.method === "POST" && request.url.endsWith("/api/v1/users/")) {
        return jsonResponse(
          {
            detail: [
              { loc: ["body", "email"], msg: "Email address is already registered" },
              { loc: ["body", "organization_id"], msg: "Not allowed for this tenant" },
            ],
          },
          422,
        );
      }
      return passthrough(input, init);
    });

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "taken@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "strong-password" } });
    fireEvent.click(await enabledSubmitControl());

    const shown = await screen.findByText("Email address is already registered");
    expect(shown.getAttribute("data-terp")).toBe("field-error");
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
    // The reason with nowhere to go is still said out loud, in the joined sentence.
    expect(
      screen.getByText(
        "email: Email address is already registered; organization_id: Not allowed for this tenant",
      ),
    ).toBeInTheDocument();
  });

  it("words a refusal by its code in the app's language, not in the backend's English", async () => {
    // The admin screens toasted the backend's detail as written, so a rate-limited create said
    // "Too many requests; please retry later." on a Dutch screen. Mutation: toast error.message
    // again, and the English sentence is what appears.
    const { fetchMock } = renderAdminApp("/admin/groups/new", 30, true, DUTCH);
    await screen.findByRole("heading", { level: 1, name: "Groep aanmaken" });
    const passthrough = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input as Request;
      if (request.method === "POST" && request.url.endsWith("/api/v1/groups/")) {
        return jsonResponse(
          { code: "rate_limited", detail: "Too many requests; please retry later.", request_id: "-" },
          429,
        );
      }
      return passthrough(input, init);
    });

    fireEvent.change(screen.getByLabelText("Naam"), { target: { value: "Redactie" } });
    fireEvent.click(screen.getByRole("button", { name: "Groep aanmaken" }));

    expect(
      await screen.findByText("Te veel verzoeken tegelijk. Wacht even en probeer het opnieuw."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Too many requests; please retry later.")).toBeNull();
  });

  it("renders its dates through the framework helper, not the built-in", async () => {
    // What this gates is the CONVERSION, not the locale channel, and the distinction is worth
    // naming: `renderAdminApp` mounts no `LocaleProvider`, so `useFormatDateTime` resolves an
    // undefined locale and both sides of the assertion below say `undefined`. That the hook reads
    // a provider at all is gated in format.test.tsx, by rendering two locales against each other.
    //
    // Here the teeth are in the negative half. Both spellings render the same instant and differ
    // only in shape, so asserting the new one alone would stay green on a host whose default
    // happened to agree with it. Asserting the old one is absent cannot be satisfied that way.
    //
    // Only one admin screen has a specimen (`admin-user-create`) and it renders no date, so
    // nothing pictures these cells and nothing asserted their text before this — which is how
    // seven of them sat on a locale-less built-in through two releases.
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
      // Access per module. The count is here so the loop below cannot pass by finding
      // nothing; the members and the granted permissions were two more, and are collections
      // that name themselves now (below).
      expect(found.length).toBe(1);
      return found;
    });
    for (const heading of headings) {
      // An h3, the level of the group's two collections beside it and of every Card's title:
      // as an h2 it put the members and the permissions under "Access per module" in the
      // page's outline. Mutation: an h2 again, and this fails.
      expect(heading.tagName).toBe("H3");
      expect(heading.getAttribute("style")).toBeNull();
    }
  });

  it("shows an account's facts and a group's as ruled sheets", async () => {
    // The packaged detail screens are the ruled grid's consumers in the framework (ADR 0169
    // §5). Mutation: drop layout="grid" from either list, and its layout is "stacked".
    renderAdminApp("/admin/users/u1");
    await screen.findByRole("heading", { level: 1, name: "jane.doe@example.com" });
    await waitFor(() =>
      expect(document.querySelector('[data-terp="detail-list"]')).toHaveAttribute("data-layout", "grid"),
    );
    cleanup();
    renderAdminApp("/admin/groups/g1");
    await waitFor(() =>
      expect(document.querySelector('[data-terp="detail-list"]')).toHaveAttribute("data-layout", "grid"),
    );
  });

  it("shows an account's own history from the audit trail, in the app's words", async () => {
    // The trail narrowed to the record the screen is about (ADR 0169 §5): the request names
    // the record, and the events read as a timeline, newest first. Mutation: drop the target
    // from the query, and the request is the whole trail.
    const { fetchMock } = renderAdminApp("/admin/users/u1");
    const base = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input) => {
      const url = new URL((input as Request).url);
      if (url.pathname.endsWith("/api/v1/audit/") && url.searchParams.get("target_id") === "u1") {
        return jsonResponse({
          items: [
            {
              id: "e2",
              created_at: "2026-08-21T09:30:00Z",
              action: "updated",
              target_type: "User",
              target_id: "u1",
              actor_id: "9f2c1b7e-0000-4000-8000-000000000002",
              request_id: null,
              payload: null,
            },
            {
              id: "e1",
              created_at: "2026-08-20T08:00:00Z",
              action: "created",
              target_type: "User",
              target_id: "u1",
              actor_id: null,
              request_id: null,
              payload: null,
            },
          ],
          total: 2,
          skip: 0,
          limit: 10,
        });
      }
      return base(input);
    });
    const history = await screen.findByRole("list", { name: "History" });
    const items = within(history).getAllByRole("listitem");
    expect(items.map((item) => item.querySelector('[data-terp="timeline-label"]')!.textContent)).toEqual([
      "Changed",
      "Created",
    ]);
    expect(items[0]!.textContent).toContain("Actor: 9f2c1b7e");
    const asked = fetchMock.mock.calls
      .map((call) => new URL((call[0] as Request).url))
      .find((url) => url.pathname.endsWith("/api/v1/audit/"))!;
    expect(asked.searchParams.get("target_type")).toBe("User");
    expect(asked.searchParams.get("target_id")).toBe("u1");
  });

  it("shows a group's own history, asked for by the group", async () => {
    // Mutation: ask GroupDetail's history for the wrong record type, and this group's events are
    // never asked for.
    const { fetchMock } = renderAdminApp("/admin/groups/g1");
    const base = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input) => {
      const url = new URL((input as Request).url);
      if (
        url.pathname.endsWith("/api/v1/audit/") &&
        url.searchParams.get("target_type") === "Group" &&
        url.searchParams.get("target_id") === "g1"
      ) {
        return jsonResponse({
          items: [
            {
              id: "g-e1",
              created_at: "2026-08-20T08:00:00Z",
              action: "created",
              target_type: "Group",
              target_id: "g1",
              actor_id: null,
              request_id: null,
              payload: null,
            },
          ],
          total: 1,
          skip: 0,
          limit: 10,
        });
      }
      return base(input);
    });
    const history = await screen.findByRole("list", { name: "History" });
    expect(within(history).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      expect.stringContaining("Created"),
    ]);
  });

  it.each([
    ["a trail the caller may not read", () => jsonResponse({ code: "permission_denied", detail: "No.", request_id: "-" }, 403)],
    ["a trail with nothing about the record", () => jsonResponse({ items: [], total: 0, skip: 0, limit: 10 })],
  ])("renders no history section for %s, and nothing in its place", async (_case, answer) => {
    // The history is context: the screen is whole without it. Mutation: render an error state
    // when the trail cannot be read, or the card when it is empty, and a section appears here.
    const { fetchMock } = renderAdminApp("/admin/users/u1");
    const base = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input) => {
      const url = new URL((input as Request).url);
      return url.pathname.endsWith("/api/v1/audit/") ? answer() : base(input);
    });
    await screen.findByRole("heading", { level: 1 });
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some((call) => new URL((call[0] as Request).url).pathname.endsWith("/api/v1/audit/")),
      ).toBe(true),
    );
    // Let the answer land and the component settle before looking for what it must not draw.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(screen.queryByRole("heading", { name: "History" })).toBeNull();
    expect(screen.queryByRole("list", { name: "History" })).toBeNull();
    expect(document.querySelector('[data-terp="error-state"]')).toBeNull();
  });

  it("names each of a group's collections, and counts the one it has read", async () => {
    // The members and the grants were an h2 the screen placed over an embedded DataView, with
    // the count nowhere; the collection now carries its own name and count (ADR 0169 §5), and
    // the way to add to it sits in its toolbar, under the name. The fixture serves one member
    // and no grants request at all, so only the members heading may claim a number.
    // Mutation: drop the count from DataView's heading, and "Members 1" is never found.
    renderAdminApp("/admin/groups/g1");
    expect(await screen.findByRole("heading", { level: 3, name: "Members 1" })).toBeInTheDocument();
    const permissions = screen.getByRole("heading", { level: 3, name: /^Permissions/ });
    expect(permissions.closest('[data-terp="dataview"]')).not.toBeNull();
    // The add-member form is inside the members collection, after its heading.
    const members = screen.getByRole("heading", { level: 3, name: "Members 1" });
    const form = screen.getByRole("button", { name: "Add member" }).closest("form")!;
    expect(members.closest('[data-terp="dataview"]')!.contains(form)).toBe(true);
    expect(members.compareDocumentPosition(form) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("speaks the app's language on the audit screen, its table and expanded row included", async () => {
    // The framework's own screen, under the framework's own Dutch catalog. Its title was Dutch
    // and everything its DataView drew was not — the result count, the row controls — because
    // DataView's strings were a table the locale could not reach; and the expanded row carried
    // one label written straight into the screen. Asserted here rather than on a bare DataView
    // because this is where an app's user actually met the two languages side by side.
    renderAdminApp("/admin/audit", 30, true, DUTCH);
    await screen.findByRole("heading", { level: 1, name: "Auditlog" });
    expect(await screen.findByText("1–1 van 1 resultaat")).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: "Rij uitklappen" }));
    expect(await screen.findByText("Verzoek")).toBeInTheDocument();
    expect(screen.queryByText("Request")).toBeNull();
    expect(screen.queryByText(/results/)).toBeNull();
  });

  it.each([
    ["nl", "nl", "Hoofdnavigatie", "Beheer"],
    ["nl", "en", "Primary", "Admin"],
    ["en", "nl", "Hoofdnavigatie", "Beheer"],
  ])(
    "labels the sidebar entry in the active locale (source %s, opened in %s)",
    async (source, active, navigationName, label) => {
      // The first row is the case a `{ id, message }` descriptor could not serve. In an app whose
      // source locale is Dutch, a descriptor opened in Dutch renders its `message` without
      // consulting any catalog — and a framework-authored message is English. The entry names
      // the framework string instead, so it is the active table's word whichever locale is the
      // source: Dutch where the app opens in Dutch, English where it opens in English.
      const locales =
        source === "nl" ? { nl: LOCALE_NL, en: LOCALE_EN } : { en: LOCALE_EN, nl: LOCALE_NL };
      renderAdminApp("/admin", 30, true, { locales, defaultLocale: active });
      const sidebar = await screen.findByRole("navigation", { name: navigationName });
      expect(await within(sidebar).findByRole("link", { name: label })).toBeInTheDocument();
      expect(within(sidebar).getAllByRole("link")).toHaveLength(1);
    },
  );

  it("keeps the audit payload's scroll container reachable by keyboard", async () => {
    // The gate for the SC 2.1.1 fix, and it has to be here rather than in the workbench.
    // `code-block` declares `overflow-x: auto`, so a wide payload is a scroll container, and a
    // scroll container no keyboard can reach is what axe reports as
    // `scrollable-region-focusable`. The workbench specimen renders its own markup, so every lane
    // there would stay green with the attribute gone from what this screen renders — the specimen
    // would be asserting its own fixture back to itself. This reads the packaged screen.
    //
    // It also pins the substitution: the audit panel renders `Code block` now rather than a
    // hand-rolled <pre> under a marker of its own, and if that reverted this would find the wrong
    // marker rather than nothing at all.
    renderAdminApp("/admin/audit");
    // Expanding the row is what renders the panel; the trigger is the row's own expand control.
    const expand = await waitFor(() => {
      const found = document.querySelector('[data-terp="dataview-expand-cell"] button');
      expect(found).not.toBeNull();
      return found as HTMLButtonElement;
    });
    fireEvent.click(expand);
    const payload = await waitFor(() => {
      const found = document.querySelector('[data-terp="code-block"]');
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
