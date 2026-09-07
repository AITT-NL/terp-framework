import { describe, expect, it } from "vitest";

import { buildModuleRows, tileValues, NO_ACCESS } from "./accessModel";
import type { AccessModel } from "./accessModel";

/** A model shaped like the server's, with the rungs deliberately out of rank order. */
function model(overrides: Partial<AccessModel> = {}): AccessModel {
  return {
    roles: [
      { name: "admin", rank: 30 },
      { name: "viewer", rank: 10 },
      { name: "editor", rank: 20 },
    ],
    permissions: [{ name: "notes.delete", min_role: "editor", label: "Delete a note" }],
    modules: [],
    ...overrides,
  } as AccessModel;
}

function endpoint(
  methods: string[],
  label: string | null,
  allowed: Record<string, boolean>,
  extra: string[] = [],
) {
  return {
    path: `/api/v1/notes/${label ?? "x"}`,
    methods,
    requirement: "role:viewer",
    extra_permissions: extra,
    name: "handler",
    operation: label === null ? null : { id: "notes.op", label },
    by_role: Object.entries(allowed).map(([role, ok]) => ({
      role,
      allowed: ok,
      reason: ok ? "allowed" : "rank",
    })),
  };
}

describe("buildModuleRows", () => {
  it("orders the rungs by rank even when the payload does not", () => {
    // Both the endpoint and the hook sort, so a pre-sorted fixture observes neither. The
    // fixture above is scrambled on purpose — a ladder rendered out of order destroys the whole
    // legibility of a strip, whose point is authority reading left to right.
    const [row] = buildModuleRows(
      model({
        modules: [
          {
            name: "notes",
            prefix: "/api/v1/notes",
            policy: null,
            permissions: [],
            access: { assignable: true, label: "Notes", platform_reason: null },
            endpoints: [],
          },
        ],
      } as Partial<AccessModel>),
    );
    expect(row.rungs.map((rung) => rung.role)).toEqual(["viewer", "editor", "admin"]);
  });

  it("reports what each rung ADDS, split by kind", () => {
    // "Everything below, plus…" is the only framing in which two rungs can be compared at a
    // glance, and the split matters because "may delete three things" is a different decision
    // from "may read thirty" — a mixed list buries the destructive half in the harmless one.
    const [row] = buildModuleRows(
      model({
        modules: [
          {
            name: "notes",
            prefix: "/api/v1/notes",
            policy: null,
            permissions: ["notes.delete"],
            access: { assignable: true, label: "Notes", platform_reason: null },
            endpoints: [
              endpoint(["GET"], "View a note", { viewer: true, editor: true, admin: true }),
              endpoint(["POST"], "Write a note", { viewer: false, editor: true, admin: true }),
              endpoint(["DELETE"], "Delete a note", { viewer: false, editor: false, admin: true }),
            ],
          },
        ],
      } as Partial<AccessModel>),
    );
    const [viewer, editor, admin] = row.rungs;

    expect(viewer.added.read.map((o) => o.label)).toEqual(["View a note"]);
    expect(viewer.added.write).toEqual([]);

    // The editor rung adds only the write — the read it inherits is not repeated.
    expect(editor.added.write.map((o) => o.label)).toEqual(["Write a note"]);
    expect(editor.added.read).toEqual([]);

    expect(admin.added.delete.map((o) => o.label)).toEqual(["Delete a note"]);
    expect(admin.added.write).toEqual([]);
    // And the cumulative set is still available, because the ladder is inclusive.
    expect(admin.reachable).toHaveLength(3);
  });

  it("says plainly when a rung adds nothing", () => {
    // A module whose policy only separates read from write has an `admin` rung that buys
    // nothing, and an administrator assigning it expecting more has made a mistake the pane
    // could have prevented. ADR 0121's second open question, answered by telling the truth
    // rather than hiding the rung.
    const [row] = buildModuleRows(
      model({
        modules: [
          {
            name: "notes",
            prefix: "/api/v1/notes",
            policy: null,
            permissions: [],
            access: { assignable: true, label: "Notes", platform_reason: null },
            endpoints: [
              endpoint(["GET"], "View a note", { viewer: true, editor: true, admin: true }),
              endpoint(["POST"], "Write a note", { viewer: false, editor: true, admin: true }),
            ],
          },
        ],
      } as Partial<AccessModel>),
    );
    expect(row.rungs.map((rung) => rung.addsNothing)).toEqual([false, false, true]);
  });

  it("keeps a module that refuses assignment, with its reason", () => {
    // Filtering it out leaves a question an administrator cannot stop asking. Present, with
    // "administering grants hands out every other authority", answers it — which is why the
    // declaration requires a reason at all.
    const rows = buildModuleRows(
      model({
        modules: [
          {
            name: "access",
            prefix: "/api/v1/access",
            policy: null,
            permissions: [],
            access: {
              assignable: false,
              label: null,
              platform_reason: "administering grants hands out every other authority",
            },
            endpoints: [],
          },
          { name: "silent", prefix: null, policy: null, permissions: [], access: null, endpoints: [] },
        ],
      } as Partial<AccessModel>),
    );
    expect(rows.map((r) => [r.name, r.assignable, r.platformReason !== null])).toEqual([
      ["access", false, true],
      ["silent", false, false],
    ]);
    // A module with no declaration falls back to its own identifier rather than rendering blank.
    expect(rows[1].label).toBe("silent");
  });

  it("counts routes that declared no operation instead of guessing a label", () => {
    // The pane has to be able to say the module is not fully explained. Presenting a partial
    // list as complete is the failure `OperationCoverage.STRICT` exists to end.
    const [row] = buildModuleRows(
      model({
        modules: [
          {
            name: "notes",
            prefix: "/api/v1/notes",
            policy: null,
            permissions: [],
            access: { assignable: true, label: "Notes", platform_reason: null },
            endpoints: [
              endpoint(["GET"], null, { viewer: true, editor: true, admin: true }),
              endpoint(["POST"], "Write a note", { viewer: false, editor: true, admin: true }),
            ],
          },
        ],
      } as Partial<AccessModel>),
    );
    expect(row.unexplainedRoutes).toBe(1);
    expect(row.rungs[0].added.read[0]).toMatchObject({ label: "handler", unexplained: true });
  });

  it("never re-derives an allowance from rank", () => {
    // The load-bearing property of this file. `by_role` is the kernel guard's own answer, so a
    // rung the server says is refused stays refused here even when its rank would suggest
    // otherwise — a client that compared ranks would be a second implementation of the
    // decision, and the copy that drifts is the one an administrator is shown.
    const [row] = buildModuleRows(
      model({
        modules: [
          {
            name: "notes",
            prefix: "/api/v1/notes",
            policy: null,
            permissions: ["notes.delete"],
            access: { assignable: true, label: "Notes", platform_reason: null },
            endpoints: [
              // An admin is refused (the route needs a grant the server cannot assume), while a
              // viewer is allowed. Nonsense by rank, and exactly what the server reports for a
              // route-level `require_permission`.
              endpoint(["DELETE"], "Delete a note", {
                viewer: true,
                editor: false,
                admin: false,
              }),
            ],
          },
        ],
      } as Partial<AccessModel>),
    );
    expect(row.rungs.map((rung) => rung.reachable.length)).toEqual([1, 0, 0]);
  });
});

describe("tileValues", () => {
  it("puts a real no-access tile first, in ladder order", () => {
    // Revoking has to be exactly as reachable as granting, which an option buried in a menu
    // never is. It is also what makes the strip bias downward rather than upward.
    expect(tileValues(model())).toEqual([NO_ACCESS, "viewer", "editor", "admin"]);
  });
});
