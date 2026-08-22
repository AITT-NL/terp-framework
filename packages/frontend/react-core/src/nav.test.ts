import { describe, expect, it } from "vitest";
import type { ModuleManifest } from "@terpjs/contract";

import { isDeclarationVisible, visibleNav } from "./nav";
import type { NavVisibilityContext } from "./nav";

const manifests: ModuleManifest[] = [
  { name: "notes", routes: [], nav: [{ label: "Notes", to: "/notes" }] },
  { name: "admin", routes: [], nav: [{ label: "Users", to: "/users", role: "admin" }] },
  {
    name: "billing",
    routes: [],
    nav: [{ label: "Export", to: "/export", permission: "billing.export" }],
  },
  {
    name: "audit",
    // Both gates on one item, which is the case the AND exists for.
    routes: [],
    nav: [{ label: "Audit", to: "/audit", role: "admin", permission: "audit.read" }],
  },
  { name: "noNav", routes: [] },
];

/** A context that says yes to everything, so each test can deny exactly one thing. */
function allowAll(overrides: Partial<NavVisibilityContext> = {}): NavVisibilityContext {
  return {
    canSeeRole: () => true,
    permissions: ["billing.export", "audit.read"],
    ...overrides,
  };
}

describe("visibleNav", () => {
  it("flattens nav across manifests when everything is visible", () => {
    expect(visibleNav(manifests, allowAll()).map((i) => i.to)).toEqual([
      "/notes",
      "/users",
      "/export",
      "/audit",
    ]);
  });

  it("filters items by their required role", () => {
    const onlyPublic = visibleNav(manifests, allowAll({ canSeeRole: (role) => role === undefined }));
    // /export declares no role, so the role gate lets it through; /audit declares both.
    expect(onlyPublic.map((i) => i.to)).toEqual(["/notes", "/export"]);
  });

  it("filters items by their required permission", () => {
    const noGrants = visibleNav(manifests, allowAll({ permissions: [] }));
    expect(noGrants.map((i) => i.to)).toEqual(["/notes", "/users"]);
  });
});

describe("isDeclarationVisible", () => {
  it("requires BOTH gates when an item declares both", () => {
    // The composition, stated as a truth table. Either alone is not enough, which is what the
    // server does: a Policy carrying a Permission enforces the permission's role floor AND the
    // grant. A client checking one would disagree with the endpoint in one direction or another.
    const both = { role: "admin", permission: "audit.read" };
    expect(isDeclarationVisible(both, allowAll())).toBe(true);
    expect(isDeclarationVisible(both, allowAll({ canSeeRole: () => false }))).toBe(false);
    expect(isDeclarationVisible(both, allowAll({ permissions: [] }))).toBe(false);
    expect(
      isDeclarationVisible(both, { canSeeRole: () => false, permissions: [] }),
    ).toBe(false);
  });

  it("is unchanged for a declaration that names neither gate", () => {
    // The additivity claim. Nothing an existing manifest declares moves, because a missing
    // permission short-circuits to true and `role` keeps its exact meaning.
    expect(isDeclarationVisible({}, allowAll({ permissions: [] }))).toBe(true);
    expect(isDeclarationVisible({}, allowAll({ canSeeRole: () => false }))).toBe(false);
  });

  it("fails closed on a permission nobody granted", () => {
    // Three ways in, one outcome. A misspelled name is indistinguishable from an ungranted one,
    // and that is correct: both mean "the server would refuse this".
    expect(isDeclarationVisible({ permission: "billing.exprot" }, allowAll())).toBe(false);
    // An app that mounts no grant capability has an empty list — which must hide the item, not
    // wave it through. This is the branch a "treat empty as unrestricted" shortcut would break.
    expect(isDeclarationVisible({ permission: "billing.export" }, allowAll({ permissions: [] }))).toBe(
      false,
    );
    // Signed out: `canSeeRole` already answers false for a null rank, before permissions matter.
    expect(
      isDeclarationVisible({ permission: "billing.export" }, {
        canSeeRole: () => false,
        permissions: ["billing.export"],
      }),
    ).toBe(false);
  });
});
