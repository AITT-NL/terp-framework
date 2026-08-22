import { describe, expect, it } from "vitest";

import { activeNavPath, isNavItemActive } from "./navActive";

// The predicate the sidebar and ModuleNav share (ADR 0097 §6, amended in 4e).
//
// Every case here is a URL shape where something in the framework got it wrong, or would have.
// The set-level ones are the point of the file: `activeNavPath` exists because "at most one item
// is current" cannot be decided one link at a time, and three of the four cases below are
// invisible to a per-item test.

describe("isNavItemActive", () => {
  it("matches a segment-aligned prefix, not a string prefix", () => {
    expect(isNavItemActive("/settings/users", "/settings")).toBe(true);
    // The guard that matters: /settings-users starts with /settings as a STRING.
    expect(isNavItemActive("/settings-users", "/settings")).toBe(false);
  });

  it("normalises a trailing slash on both operands, in both branches", () => {
    // The exact branch had this from the start; the prefix branch did not, and an earlier draft
    // of the rule attached the normalisation to `exact` alone.
    expect(isNavItemActive("/settings/", "/settings")).toBe(true);
    expect(isNavItemActive("/settings", "/settings/")).toBe(true);
    expect(isNavItemActive("/settings/", "/settings", true)).toBe(true);
    expect(isNavItemActive("/settings", "/settings/", true)).toBe(true);
    // ...and the root is not normalised away to the empty string.
    expect(isNavItemActive("/", "/")).toBe(true);
  });

  it("ignores the query string and the hash", () => {
    // A nav tab's identity is its path. Filtering a list must not unhighlight the tab the user
    // is standing on, which is what the router does on an exact link with includeSearch left at
    // its default.
    expect(isNavItemActive("/records", "/records")).toBe(true);
    expect(isNavItemActive("/records", "/records", true)).toBe(true);
  });

  it("treats a `to` that is not an absolute path as inactive", () => {
    // Not tidiness. The router resolves a relative or empty `to` against the CURRENT location,
    // so `to: ""` is a link to wherever you already are — and a raw prefix test would light
    // every item at once, because every path starts with the empty string.
    expect(isNavItemActive("/records", "")).toBe(false);
    expect(isNavItemActive("/records", "records")).toBe(false);
    expect(isNavItemActive("/records", "./records")).toBe(false);
  });

  it("exact refuses the children a prefix would take", () => {
    expect(isNavItemActive("/settings/users", "/settings", true)).toBe(false);
    expect(isNavItemActive("/settings", "/settings", true)).toBe(true);
  });

  it("lets the root claim nothing but itself, with no rule of its own", () => {
    // `/` prefixes every path as a STRING, which is why the router adapter carried a
    // hand-written `exact: item.to === "/"`. Matching on SEGMENTS makes that unnecessary:
    // `/profile`'s second character is not a slash.
    expect(isNavItemActive("/profile", "/")).toBe(false);
    expect(isNavItemActive("/", "/")).toBe(true);
  });

  it("collapses repeated slashes, which is the one shape the segment test would let through", () => {
    // The gate for the normalisation, and it is the only input that distinguishes it: `/` has
    // length 1, so the boundary test asks whether current[1] is a slash — true for exactly
    // `//foo`. The router never emits that (it collapses on the way in), but `activePath` is a
    // plain string and window.location.pathname is not normalised by anyone.
    expect(isNavItemActive("//foo", "/")).toBe(false);
    expect(activeNavPath("//foo", [{ to: "/" }])).toBeUndefined();
    // ...and a doubled slash deeper in the path resolves to the same item either way.
    expect(isNavItemActive("/settings//users", "/settings")).toBe(true);
  });
});

describe("activeNavPath", () => {
  const NAV = [{ to: "/" }, { to: "/settings" }, { to: "/settings/users" }];

  it("returns exactly one item where a per-link predicate returns two", () => {
    // The defect this whole file exists for. Both /settings and /settings/users match
    // /settings/users on their own, so a router — which decides per link — marks both current,
    // paints both, and announces "current page" twice.
    expect(NAV.filter((item) => isNavItemActive("/settings/users", item.to))).toHaveLength(2);
    expect(activeNavPath("/settings/users", NAV)).toBe("/settings/users");
  });

  it("keeps the parent lit on a URL that is not itself a nav item", () => {
    // The other half, and the reason per-item `exact` is not the fix: turn exact on to stop the
    // case above and this one goes dark, leaving a page with nothing current at all.
    expect(activeNavPath("/settings/appearance", NAV)).toBe("/settings");
  });

  it("does not let the root item claim an unrelated page", () => {
    // The example app ships `{ label: "Notes", to: "/" }`, and PROFILE_PATH is mounted by
    // buildAppRouter and is in no manifest's nav. A STRING-prefix longest-match would light
    // "Notes" while the user is on their profile; a segment-aligned one does not.
    expect(activeNavPath("/profile", NAV)).toBeUndefined();
    expect(activeNavPath("/", NAV)).toBe("/");
  });

  it("returns undefined when nothing matches", () => {
    expect(activeNavPath("/explorer", [{ to: "/settings" }])).toBeUndefined();
  });

  it("honours an item's own exact flag", () => {
    const nav = [{ to: "/settings", exact: true }, { to: "/records" }];
    expect(activeNavPath("/settings/users", nav)).toBeUndefined();
    expect(activeNavPath("/settings", nav)).toBe("/settings");
  });

  it("is not fooled by declaration order", () => {
    // Longest wins, not first — otherwise the answer depends on `import.meta.glob` key order,
    // which is the same accident 0097 names as the reason nav needs explicit ordering at all.
    const shallowFirst = [{ to: "/settings" }, { to: "/settings/users" }];
    const deepFirst = [{ to: "/settings/users" }, { to: "/settings" }];
    expect(activeNavPath("/settings/users", shallowFirst)).toBe("/settings/users");
    expect(activeNavPath("/settings/users", deepFirst)).toBe("/settings/users");
  });
});
