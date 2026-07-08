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
