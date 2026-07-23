import { describe, expect, it } from "vitest";
import type { ModuleManifest } from "@terpjs/contract";

import { visibleNav } from "./nav";

const manifests: ModuleManifest[] = [
  { name: "notes", routes: [], nav: [{ label: "Notes", to: "/notes" }] },
  { name: "admin", routes: [], nav: [{ label: "Users", to: "/users", role: "admin" }] },
  { name: "noNav", routes: [] },
];

describe("visibleNav", () => {
  it("flattens nav across manifests when everything is visible", () => {
    expect(visibleNav(manifests, () => true).map((i) => i.to)).toEqual(["/notes", "/users"]);
  });

  it("filters items by their required role", () => {
    const onlyPublic = visibleNav(manifests, (role) => role === undefined);
    expect(onlyPublic.map((i) => i.to)).toEqual(["/notes"]);
  });
});
