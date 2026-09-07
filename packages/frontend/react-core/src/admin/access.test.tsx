// @vitest-environment jsdom
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ModuleManifest } from "@terpjs/contract";
import type { ComponentType } from "react";

import { withAdminArea } from "../bootstrap";
import { buildAppRouter } from "../router";
import { Page } from "../Page";
import { TerpProvider, useAuth } from "../TerpProvider";
import { ToastProvider } from "../toast";

/**
 * The permission surface end to end: the screen that *explains* the declared model
 * (`/admin/access`) and the panel that *assigns* from it (on a subject's detail screen).
 *
 * Its own harness rather than `admin.test.tsx`'s, for one reason: that fixture answers
 * `/access/model` with no modules at all, which is what every other admin screen needs from it
 * (a role ladder and nothing else). Both surfaces here are entirely about the modules, so they
 * need a model with real ones — and putting that in the shared fixture would make every
 * unrelated admin screen render module strips it has no business rendering.
 */

const SUBJECT = "11111111-1111-4111-8111-111111111111";
const GROUP = "22222222-2222-4222-8222-222222222222";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** One endpoint of a module, with the outcome the *server* reported for each rung. */
function endpoint(
  methods: string[],
  label: string | null,
  allowed: Record<string, boolean>,
) {
  return {
    path: "/api/v1/notes/",
    methods,
    requirement: "role:viewer",
    extra_permissions: [],
    name: "handler",
    operation: label === null ? null : { id: `notes.${label}`, label },
    by_role: Object.entries(allowed).map(([role, ok]) => ({
      role,
      allowed: ok,
      reason: ok ? "allowed" : "rank",
    })),
  };
}

function accessModel() {
  return {
    // Deliberately out of rank order: the endpoint sorts and the hook sorts again, so a
    // pre-sorted fixture would observe neither, and a ladder rendered out of order destroys the
    // whole legibility of a strip — its point is authority reading left to right.
    roles: [
      { name: "admin", rank: 30 },
      { name: "viewer", rank: 10 },
      { name: "editor", rank: 20 },
    ],
    permissions: [],
    modules: [
      {
        name: "notes",
        prefix: "/api/v1/notes",
        policy: { read: "viewer", write: "editor" },
        permissions: ["notes.delete"],
        access: { assignable: true, label: "Notes", platform_reason: null },
        endpoints: [
          endpoint(["GET"], "View a note", { viewer: true, editor: true, admin: true }),
          endpoint(["POST"], "Write a note", { viewer: false, editor: true, admin: true }),
          endpoint(["DELETE"], "Delete a note", { viewer: false, editor: false, admin: true }),
        ],
      },
      {
        name: "reports",
        prefix: "/api/v1/reports",
        policy: { read: "viewer", write: "editor" },
        permissions: [],
        access: { assignable: true, label: "Reports", platform_reason: null },
        // One route with no declared operation, so the pane has to say the module is not fully
        // explained rather than presenting a partial list as complete.
        endpoints: [endpoint(["GET"], null, { viewer: true, editor: true, admin: true })],
      },
      {
        name: "access",
        prefix: "/api/v1/access",
        policy: { read: "admin", write: "admin" },
        permissions: [],
        access: {
          assignable: false,
          label: null,
          platform_reason: "administering grants hands out every other authority",
        },
        endpoints: [],
      },
    ],
  };
}

/** What the subject holds: `editor` in notes directly, `admin` in reports through a group. */
function subjectAccess(subjectId: string) {
  return {
    subject_id: subjectId,
    via: [{ id: subjectId, kind: "self", name: null }],
    permissions: [],
    module_roles: [
      {
        module: "notes",
        role_rank: 20,
        role: "editor",
        effective: true,
        stale: [],
        via: { id: subjectId, kind: "self", name: null },
      },
      {
        module: "reports",
        role_rank: 30,
        role: "admin",
        effective: true,
        stale: [],
        via: { id: GROUP, kind: "group", name: "Finance" },
      },
    ],
  };
}

interface Written {
  method: string;
  path: string;
  body: unknown;
}

function stubAccessFetch(written: Written[]) {
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
      return jsonResponse(accessModel());
    }
    if (path.includes("/module-roles/")) {
      written.push({
        method: request.method,
        path,
        body: request.method === "PUT" ? await request.clone().json() : null,
      });
      return request.method === "DELETE"
        ? new Response(null, { status: 204 })
        : jsonResponse({
            id: "mr1",
            subject_id: SUBJECT,
            module: "notes",
            role_rank: 20,
            version: 1,
            created_at: "2026-07-01T10:00:00Z",
            updated_at: "2026-07-01T10:00:00Z",
          });
    }
    if (path.includes("/api/v1/access/subjects/")) {
      return jsonResponse(subjectAccess(path.split("/").pop() ?? SUBJECT));
    }
    if (path.endsWith(`/api/v1/users/${SUBJECT}`)) {
      return jsonResponse({
        id: SUBJECT,
        email: "jane.doe@example.com",
        // Globally an editor, which is the floor every strip on this page sits on.
        role: 20,
        is_active: true,
        created_at: "2026-07-01T10:00:00Z",
        updated_at: "2026-07-01T10:00:00Z",
        version: 1,
      });
    }
    if (path.endsWith(`/api/v1/groups/${GROUP}`)) {
      return jsonResponse({
        id: GROUP,
        name: "Finance",
        description: "money",
        member_count: 1,
        version: 1,
        created_at: "2026-07-01T10:00:00Z",
        updated_at: "2026-07-01T10:00:00Z",
      });
    }
    return jsonResponse({ items: [], total: 0, skip: 0, limit: 20 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function LogInOnMount() {
  const auth = useAuth();
  useEffect(() => {
    void auth.login({ email: "admin@example.com", password: "pw" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}

function renderAt(initialPath: string) {
  const written: Written[] = [];
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
  stubAccessFetch(written);
  render(
    <TerpProvider baseUrl="https://api.test">
      <ToastProvider>
        <LogInOnMount />
        <RouterProvider router={router} />
      </ToastProvider>
    </TerpProvider>,
  );
  return { written };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

// --- /admin/access: the screen that explains the model ---------------------- //

describe("the access screen", () => {
  it("describes each module's ladder without offering a choice", async () => {
    renderAt("/admin/access");
    // A description, not a disabled control: there is nothing on this screen to choose, and a
    // disabled radiogroup would announce three unchecked radio buttons per module.
    await waitFor(() =>
      expect(screen.getByRole("group", { name: "Notes" })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("radio")).toEqual([]);

    // Each rung says what it ADDS over the one below — the only framing in which two rungs can
    // be compared at a glance — split by kind so the destructive half is not buried.
    expect(screen.getByText("View a note")).toBeInTheDocument();
    expect(screen.getByText("Write a note")).toBeInTheDocument();
    expect(screen.getByText("Delete a note")).toBeInTheDocument();
  });

  it("keeps a module that refuses assignment, and renders the reason as text", async () => {
    renderAt("/admin/access");
    // Filtering it out leaves a question an administrator cannot stop asking. Rendered rather
    // than hovered, for the same reason the delta is on the tile: an explanation you have to
    // discover is not one.
    await waitFor(() =>
      expect(
        screen.getByText("administering grants hands out every other authority"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Never assignable per module")).toBeInTheDocument();
  });

  it("counts the routes that explained nothing instead of implying the list is complete", async () => {
    renderAt("/admin/access");
    await waitFor(() =>
      expect(
        screen.getByText("1 action(s) in this module have no description yet"),
      ).toBeInTheDocument(),
    );
  });
});

// --- the assignment panel: where the choice has a subject ------------------- //

async function openUserPanel() {
  const harness = renderAt(`/admin/users/${SUBJECT}`);
  await waitFor(() =>
    expect(screen.getByRole("radiogroup", { name: "Notes" })).toBeInTheDocument(),
  );
  return harness;
}

function tile(group: string, name: string): HTMLElement {
  const strip = screen.getByRole("radiogroup", { name: group });
  const found = [...strip.querySelectorAll('[role="radio"]')].find(
    (node) => node.textContent?.startsWith(name) === true,
  );
  if (found === undefined) throw new Error(`no ${name} tile in ${group}`);
  return found as HTMLElement;
}

describe("the assignment panel", () => {
  it("offers only the modules that opted in", async () => {
    await openUserPanel();
    // `access` declares that it is never per-module assignable, and offering a control the
    // server would refuse is worse than not offering one. The access screen is where its
    // refusal is explained; this panel simply has no strip for it.
    expect(screen.getByRole("radiogroup", { name: "Notes" })).toBeInTheDocument();
    expect(screen.getByRole("radiogroup", { name: "Reports" })).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "access" })).not.toBeInTheDocument();
  });

  it("preselects the rung held directly and credits an inherited one to its group", async () => {
    await openUserPanel();
    // Two different facts. The strip can only change what this subject holds *directly*; a rung
    // arriving through a group is a fact about the group, and "why can this person do that?" is
    // answered wrongly by a strip that shows only the direct row.
    expect(tile("Notes", "editor")).toHaveAttribute("aria-checked", "true");
    expect(tile("Notes", "admin")).toHaveAttribute("aria-checked", "false");

    expect(tile("Reports", "No access")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("Also admin here, through Finance")).toBeInTheDocument();
  });

  it("says why a rung at or below the global role would change nothing", async () => {
    await openUserPanel();
    // The guard resolves a module rank as the *higher* of the global rank and the module rung,
    // so assigning `viewer` to an editor stores a row that can never fire. The floor marker is
    // what stops someone doing it and wondering why nothing happened.
    expect(tile("Notes", "editor")).toHaveAttribute("data-floor", "true");
    expect(tile("Notes", "admin")).not.toHaveAttribute("data-floor");
    expect(
      screen.getAllByText("editor everywhere already, so anything up to here changes nothing"),
    ).toHaveLength(2);
  });

  it("writes a middle rung straight away, addressed by subject and module", async () => {
    const { written } = await openUserPanel();
    fireEvent.click(tile("Reports", "viewer"));
    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0].method).toBe("PUT");
    expect(written[0].path).toBe(
      `/api/v1/access/subjects/${SUBJECT}/module-roles/reports`,
    );
    // The rank, not the name: the row stores a rank so the ladder stays the app's own
    // (ADR 0022), and the name is what the reader sees.
    expect(written[0].body).toEqual({ role_rank: 10 });
  });

  it("puts the most privileged rung behind a confirmation", async () => {
    const { written } = await openUserPanel();
    fireEvent.click(tile("Notes", "admin"));
    // Nothing written yet — this is the claim that makes the strip's manual activation
    // load-bearing, since arrowing across the tiles must not fire this either.
    expect(written).toHaveLength(0);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Give admin in Notes?");

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0].body).toEqual({ role_rank: 30 });
  });

  it("takes a rung away through the same strip, behind its own confirmation", async () => {
    const { written } = await openUserPanel();
    // Revoking has to be exactly as reachable as granting, which an option buried in a menu
    // never is — and it is a real tile, so the strip biases downward rather than upward.
    fireEvent.click(tile("Notes", "No access"));
    expect(await screen.findByRole("dialog")).toHaveTextContent(
      "Take away the role in Notes?",
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0].method).toBe("DELETE");
    expect(written[0].path).toBe(`/api/v1/access/subjects/${SUBJECT}/module-roles/notes`);
  });

  it("writes nothing when the tile already selected is committed again", async () => {
    const { written } = await openUserPanel();
    // A request that stores what is already stored still writes an audit row saying somebody
    // changed something, which is a lie the audit log cannot be allowed to tell.
    fireEvent.click(tile("Notes", "editor"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(written).toEqual([]);
  });

  it("marks no floor on a group, because a group has no role of its own", async () => {
    renderAt(`/admin/groups/${GROUP}`);
    await waitFor(() =>
      expect(screen.getByRole("radiogroup", { name: "Notes" })).toBeInTheDocument(),
    );
    // ADR 0074 gives groups permissions rather than roles, so there is no rank under the strip
    // to mark — and a floor drawn from nothing would tell the reader a rung is redundant when
    // it is the only thing granting access at all.
    expect(tile("Notes", "editor")).not.toHaveAttribute("data-floor");
    expect(
      screen.queryByText(/everywhere already, so anything up to here changes nothing/),
    ).not.toBeInTheDocument();
  });
});
