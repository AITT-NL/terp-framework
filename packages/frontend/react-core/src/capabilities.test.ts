import { describe, expect, it } from "vitest";

import { canPerform, DEFAULT_RANK_THRESHOLDS, type RankThresholds } from "./capabilities";

describe("canPerform", () => {
  it("gates by the default viewer/editor/admin ladder", () => {
    expect(canPerform(10, "read")).toBe(true);
    expect(canPerform(10, "write")).toBe(false);
    expect(canPerform(20, "write")).toBe(true);
    expect(canPerform(20, "admin")).toBe(false);
    expect(canPerform(30, "admin")).toBe(true);
  });

  it("honours custom thresholds for a different role model", () => {
    const flat: RankThresholds = { read: 0, write: 0, admin: 100 };
    expect(canPerform(0, "write", flat)).toBe(true);
    expect(canPerform(0, "admin", flat)).toBe(false);
    expect(canPerform(100, "admin", flat)).toBe(true);
  });

  it("exposes the bundled ladder as the default", () => {
    expect(DEFAULT_RANK_THRESHOLDS).toEqual({ read: 10, write: 20, admin: 30 });
  });
});

describe("canPerform with a per-module rung", () => {
  it("takes the higher of the global rank and the module rung", () => {
    // What the server's guard computes (ADR 0121). Without the rung the UI refused what the
    // guard would have allowed, so a caller who could reach a module *only* through a rung had
    // every control there hidden — a control living on one side of the wire.
    expect(canPerform(10, "write")).toBe(false);
    expect(canPerform(10, "write", DEFAULT_RANK_THRESHOLDS, 20)).toBe(true);
  });

  it("never lowers a global rank", () => {
    // The rung is additive at the guard, so a lower one cannot demote anyone here either. This
    // is the case an implementation that *replaced* the rank would break.
    expect(canPerform(30, "write", DEFAULT_RANK_THRESHOLDS, 10)).toBe(true);
  });

  it("ignores a rung for a threshold it still does not reach", () => {
    expect(canPerform(10, "admin", DEFAULT_RANK_THRESHOLDS, 20)).toBe(false);
  });
});
