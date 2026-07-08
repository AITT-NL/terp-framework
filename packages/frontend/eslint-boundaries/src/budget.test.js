import fs from "node:fs";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { checkBudget, countMarkers } from "./budget.js";

// The frontend analog of the backend budget-ratchet tests: actual `terp-allow-*` marker counts
// must match the checked-in escape-hatch-budget.json exactly — a rise, a drop, and an
// unbudgeted marker are each reported, and a missing/invalid budget fails closed.

const roots = [];
const scratchRoot = path.resolve("node_modules/.cache/terp-budget-tests");
let rootCounter = 0;

function appRoot(files, budget) {
  const root = path.join(scratchRoot, `case-${rootCounter++}`);
  fs.rmSync(root, { recursive: true, force: true });
  fs.mkdirSync(root, { recursive: true });
  roots.push(root);
  for (const [relative, text] of Object.entries(files)) {
    const full = path.join(root, "src", "modules", relative);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, text);
  }
  if (budget !== undefined) {
    fs.writeFileSync(path.join(root, "escape-hatch-budget.json"), budget);
  }
  return root;
}

function check(root) {
  return checkBudget(root, path.join(root, "escape-hatch-budget.json"));
}

const MARKED = "// terp-allow-no-restricted-syntax: measured host quirk\nexport const W = 1;\n";

afterEach(() => {
  for (const root of roots.splice(0)) {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

describe("countMarkers", () => {
  it("counts markers per rule across the module surface", () => {
    const root = appRoot({ "a/x.tsx": MARKED, "b/y.tsx": MARKED });
    expect(countMarkers(root)).toEqual({ "terp-allow-no-restricted-syntax": 2 });
  });

  it("counts custom terp rule markers for the same budget ratchet", () => {
    const marked = "// terp-allow-no-unsafe-target-blank: vendor opener handshake\nexport const W = 1;\n";
    const root = appRoot({ "a/x.tsx": marked });
    expect(countMarkers(root)).toEqual({ "terp-allow-no-unsafe-target-blank": 1 });
  });

  it("is empty for an app with no modules directory", () => {
    const root = path.join(scratchRoot, `case-${rootCounter++}`);
    fs.rmSync(root, { recursive: true, force: true });
    fs.mkdirSync(root, { recursive: true });
    roots.push(root);
    expect(countMarkers(root)).toEqual({});
  });
});

describe("checkBudget", () => {
  it("passes when usage matches the budget exactly", () => {
    const root = appRoot({ "a/x.tsx": MARKED }, '{ "terp-allow-no-restricted-syntax": 1 }');
    expect(check(root)).toEqual([]);
  });

  it("fails when a marker rose above its budget", () => {
    const root = appRoot(
      { "a/x.tsx": MARKED, "b/y.tsx": MARKED },
      '{ "terp-allow-no-restricted-syntax": 1 }',
    );
    expect(check(root).join("\n")).toMatch(/rose to 2/);
  });

  it("fails when a marker dropped below its budget (lock in the win)", () => {
    const root = appRoot({}, '{ "terp-allow-no-restricted-syntax": 1 }');
    expect(check(root).join("\n")).toMatch(/dropped to 0/);
  });

  it("fails on an unbudgeted marker", () => {
    const root = appRoot({ "a/x.tsx": MARKED }, "{}");
    expect(check(root).join("\n")).toMatch(/unbudgeted marker/);
  });

  it("fails closed on a missing budget file", () => {
    const root = appRoot({ "a/x.tsx": MARKED });
    expect(check(root).join("\n")).toMatch(/budget file not found/);
  });

  it("fails closed on invalid budget JSON", () => {
    const root = appRoot({}, "not json");
    expect(check(root).join("\n")).toMatch(/not valid JSON/);
  });

  it("fails closed on a non-object budget", () => {
    const root = appRoot({}, '["terp-allow-x"]');
    expect(check(root).join("\n")).toMatch(/must be a JSON object/);
  });
});
