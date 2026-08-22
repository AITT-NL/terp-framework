import { describe, expect, it } from "vitest";
import type { ModuleManifest } from "@terpjs/contract";

import { groupNav, isDeclarationVisible, visibleNav } from "./nav";
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

// `groupNav` — the app's declared groups meeting the modules' declared items.
//
// Every row below names the mutation that turns it red, because two of this phase's earlier
// gates could not fail and were only found by trying. Two are worth reading before adding a row
// here. "Sorts stably" cannot be falsified by DELETING the sort: `Array.prototype.sort` is stable
// by specification, so a tied array comes out in declaration order whether or not it was sorted,
// and the assertion passes over the mutant. The comparator that does reorder ties is
// `(a, b) => ((a.order ?? 0) - (b.order ?? 0)) || -1`, which was measured in this repo's node to
// fully reverse a tied array at every length from 2 upward. And "sorts" is only falsifiable
// against `?? Infinity` if the fixture carries a POSITIVE order beside an absent one — with only
// negatives and absents the two rules agree.
describe("groupNav", () => {
  const items = (...tos: string[]) => tos.map((to) => ({ label: to, to }));
  const tos = (sections: ReturnType<typeof groupNav>) =>
    sections.map((section) => section.items.map((item) => item.to));
  /** Section identity and heading, without the items — asserted separately via `tos`. */
  const shape = (sections: ReturnType<typeof groupNav>) =>
    sections.map((section) => ({ id: section.id, label: section.label }));

  it("renders one unlabelled section when the app declares no groups", () => {
    // The additivity claim, as a test rather than an argument: same items, same order, one
    // section that renders no heading. Mutation: `return [{ id: "default", label: "", items }]`,
    // which falsifies the null id and the null label together.
    expect(groupNav(items("/a", "/b", "/c"))).toEqual([
      { id: null, label: null, items: items("/a", "/b", "/c") },
    ]);
  });

  it("emits the ungrouped bucket last, after every declared group", () => {
    // The rule that changed under review. The packaged admin entry carries no `group` and no app
    // can give it one, so a first-emitted default bucket would hoist it to the top of the sidebar
    // the moment an app declared its first group. Mutation: emit the ungrouped section first.
    const sections = groupNav(
      [
        { label: "Loose", to: "/loose" },
        { label: "Sales", to: "/sales", group: "work" },
      ],
      [{ id: "work", label: "Werkruimte" }],
    );
    expect(sections.map((section) => section.id)).toEqual(["work", null]);
    expect(tos(sections)).toEqual([["/sales"], ["/loose"]]);
  });

  it("drops a group left empty rather than rendering a label over nothing", () => {
    // Reachable on a first render: a group holding only the role-gated `/admin` entry is empty
    // for everyone who is not an admin, because `visibleNav` has already removed it.
    // Mutation: push the section regardless of `bucket.length`.
    const sections = groupNav(items("/a"), [
      { id: "empty", label: "Beheer" },
      { id: "used", label: "Werk" },
    ]);
    expect(sections.map((section) => section.id)).toEqual([null]);
    expect(sections.some((section) => section.label === "Beheer")).toBe(false);
  });

  it("falls an item naming an undeclared group open into the ungrouped bucket", () => {
    // A module ships before the app declares its group; the link must still be reachable.
    // Mutation: drop the `declared.has(item.group)` half of the key expression, and the item
    // lands in a bucket nothing reads — it vanishes from the sidebar with nothing reporting it.
    const sections = groupNav(
      [{ label: "Orphan", to: "/orphan", group: "not-declared" }],
      [{ id: "work", label: "Werkruimte" }],
    );
    expect(tos(sections)).toEqual([["/orphan"]]);
    expect(sections[0]!.id).toBeNull();
  });

  it("sorts items on order, treating absent as 0", () => {
    // Mutation: `order ?? Infinity`, which sends both unordered items to the end and yields
    // /up, /down, /a, /b. The POSITIVE order is what makes the two rules disagree.
    const sections = groupNav([
      { label: "down", to: "/down", order: 1 },
      { label: "a", to: "/a" },
      { label: "up", to: "/up", order: -1 },
      { label: "b", to: "/b" },
    ]);
    expect(tos(sections)).toEqual([["/up", "/a", "/b", "/down"]]);
  });

  it("keeps tied items in declaration order", () => {
    // Mutation: `((a.order ?? 0) - (b.order ?? 0)) || -1` — measured to reverse a tied array at
    // every length from 2 up. Deleting the sort does NOT falsify this, which is the point.
    expect(tos(groupNav(items("/first", "/second", "/third")))).toEqual([
      ["/first", "/second", "/third"],
    ]);
  });

  it("sorts groups on order, treating absent as 0", () => {
    // Same shape one level up, and the same `?? Infinity` mutation.
    const sections = groupNav(
      [
        { label: "d", to: "/d", group: "down" },
        { label: "p", to: "/p", group: "plain" },
        { label: "u", to: "/u", group: "up" },
      ],
      [
        { id: "down", label: "Down", order: 1 },
        { id: "plain", label: "Plain" },
        { id: "up", label: "Up", order: -1 },
      ],
    );
    expect(sections.map((section) => section.id)).toEqual(["up", "plain", "down"]);
  });

  it("keeps tied groups in declaration order", () => {
    const sections = groupNav(
      [
        { label: "a", to: "/a", group: "one" },
        { label: "b", to: "/b", group: "two" },
        { label: "c", to: "/c", group: "three" },
      ],
      [
        { id: "one", label: "One" },
        { id: "two", label: "Two" },
        { id: "three", label: "Three" },
      ],
    );
    expect(sections.map((section) => section.id)).toEqual(["one", "two", "three"]);
  });

  it("lets the first declaration of a duplicated id win, without duplicating its items", () => {
    // `groupNav` stays total so a render can never throw; `buildAppRouter` refuses the duplicate
    // at composition time instead. Mutation: drop the `declared.has` guard on insertion, and the
    // second declaration overwrites the first, so the label becomes "Second".
    const sections = groupNav([{ label: "a", to: "/a", group: "dup" }], [
      { id: "dup", label: "First" },
      { id: "dup", label: "Second" },
    ]);
    expect(shape(sections)).toEqual([{ id: "dup", label: "First" }]);
    expect(tos(sections)).toEqual([["/a"]]);
  });

  it("treats the empty string as a real group id, not as the ungrouped bucket", () => {
    // The default bucket is keyed on `null` rather than on a falsy sentinel precisely so that
    // `id: ""` — a legal string — stays a group of its own. Mutation: key the bucket on `""`,
    // and this item's group merges into the ungrouped section and loses its label.
    const sections = groupNav([{ label: "a", to: "/a", group: "" }], [{ id: "", label: "Blank" }]);
    expect(shape(sections)).toEqual([{ id: "", label: "Blank" }]);
    expect(tos(sections)).toEqual([["/a"]]);
  });

  it("renders a null-labelled group as pure positioning", () => {
    // The escape an app uses to place its otherwise-ungrouped items somewhere other than last.
    const sections = groupNav(
      [
        { label: "main", to: "/main", group: "main" },
        { label: "loose", to: "/loose" },
      ],
      [{ id: "main", label: null }],
    );
    expect(shape(sections)).toEqual([
      { id: "main", label: null },
      { id: null, label: null },
    ]);
    expect(tos(sections)).toEqual([["/main"], ["/loose"]]);
  });
});
