import { spawnSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { ESLint } from "eslint";
import { afterEach, describe, expect, it } from "vitest";

import terpBoundaries, { catalogRuleIds } from "./index.js";
import { renderEnvelope } from "./findings.js";

// The machine-readable boundary lint (the frontend analog of `terp check --format json`):
// the findings envelope publishes the evaluated-rule inventory + findings attributed to
// stack-neutral catalog ids, humans keep stderr, and the exit code stays the verdict.

const SPEC_ROOT = path.dirname(
  createRequire(import.meta.url).resolve("@terp/spec/package.json"),
);
const FINDINGS_BIN = fileURLToPath(new URL("./findings.js", import.meta.url));

const roots = [];
const scratchRoot = path.resolve("node_modules/.cache/terp-findings-tests");
let rootCounter = 0;

function appRoot(files) {
  const root = path.join(scratchRoot, `case-${rootCounter++}`);
  fs.rmSync(root, { recursive: true, force: true });
  fs.mkdirSync(root, { recursive: true });
  roots.push(root);
  for (const [relative, text] of Object.entries(files)) {
    const full = path.join(root, relative);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, text);
  }
  return root;
}

afterEach(() => {
  for (const root of roots.splice(0)) {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

async function lintModule(text) {
  const eslint = new ESLint({ overrideConfigFile: true, overrideConfig: terpBoundaries });
  const filePath = path.resolve("src/modules/sample/View.tsx");
  return eslint.lintText(text, { filePath });
}

describe("catalogRuleIds (the evaluated-rule inventory)", () => {
  it("matches the Terp Standard frontend catalog exactly, both directions", () => {
    // The inventory can't lie: every catalog entry is evaluated, and no evaluated id
    // outlives its catalog entry (the same parity discipline as test_spec_catalog).
    const catalogued = fs
      .readdirSync(path.join(SPEC_ROOT, "catalog", "frontend"))
      .filter((name) => name.endsWith(".json"))
      .map((name) => `frontend/${name.replace(/\.json$/, "")}`)
      .sort();
    expect(catalogRuleIds()).toEqual(catalogued);
  });
});

describe("renderEnvelope", () => {
  it("attributes findings to catalog ids and publishes the inventory", async () => {
    const results = await lintModule(
      'export function View() {\n  return <button style={{ color: "#fff" }}>x</button>;\n}\n',
    );
    const { envelope, human } = renderEnvelope(results, path.resolve("."), {
      layoutContract: true,
    });
    expect(envelope.terp_findings).toBe(1);
    expect(envelope.tool).toBe("@terp/eslint-boundaries");
    expect(envelope.rules).toEqual(catalogRuleIds());
    expect(envelope.not_applicable).toEqual([]);
    const rules = envelope.findings.map((finding) => finding.rule);
    expect(rules).toContain("frontend/token-styled-elements");
    expect(rules).toContain("frontend/no-inline-styling");
    expect(envelope.unattributed).toEqual([]);
    expect(human.length).toBe(envelope.findings.length);
  });

  it("publishes an un-opted-in layout contract as not_applicable, never as passing", async () => {
    // The opt-in rule is inert without a checked-in layout-contract.json; keeping it
    // in `rules` would let a consumer render "evaluated, zero findings" = green for a
    // rule that never ran. It moves to `not_applicable` instead.
    const results = await lintModule("export const view = 1;\n");
    const { envelope } = renderEnvelope(results, path.resolve("."), { layoutContract: false });
    expect(envelope.not_applicable).toEqual(["frontend/layout-contract"]);
    expect(envelope.rules).toEqual(
      catalogRuleIds().filter((id) => id !== "frontend/layout-contract"),
    );
  });

  it("appends budget drift as frontend/escape-hatch findings", () => {
    const { envelope, human } = renderEnvelope([], path.resolve("."), {
      layoutContract: true,
      budgetProblems: ["unbudgeted marker 'terp-allow-no-eval' used 1 time(s)"],
      budgetFile: "escape-hatch-budget.json",
    });
    expect(envelope.findings).toEqual([
      {
        rule: "frontend/escape-hatch",
        path: "escape-hatch-budget.json",
        message: "unbudgeted marker 'terp-allow-no-eval' used 1 time(s)",
      },
    ]);
    expect(human).toHaveLength(1);
  });

  it("emits spec-shaped findings (findings.schema.json), separator-stable", async () => {
    const schema = JSON.parse(
      fs.readFileSync(path.join(SPEC_ROOT, "findings.schema.json"), "utf8"),
    );
    const item = schema.items;
    const results = await lintModule("export const x = fetch('/api');\n");
    const { envelope } = renderEnvelope(results, path.resolve("."));
    expect(envelope.findings.length).toBeGreaterThan(0);
    for (const finding of envelope.findings) {
      expect(Object.keys(finding).sort()).toEqual(["line", "message", "path", "rule"]);
      expect(finding.rule).toMatch(new RegExp(item.properties.rule.pattern));
      expect(finding.path).toBe("src/modules/sample/View.tsx");
      expect(finding.path).not.toContain("\\");
      expect(Number.isInteger(finding.line)).toBe(true);
      expect(finding.line).toBeGreaterThanOrEqual(1);
    }
  });

  it("surfaces a non-boundary message as unattributed, never dropped", async () => {
    // A parse error has no boundary attribution; it must stay visible in the envelope.
    const results = await lintModule("export const = broken(\n");
    const { envelope } = renderEnvelope(results, path.resolve("."));
    expect(envelope.findings).toEqual([]);
    expect(envelope.unattributed.length).toBeGreaterThan(0);
    for (const entry of envelope.unattributed) {
      expect(Object.keys(entry).sort()).toEqual(["line", "message", "path", "reported_as"]);
      expect(entry.line).toBeGreaterThanOrEqual(1);
    }
  });
});

describe("terp-boundaries-lint (the bin)", () => {
  const config =
    'import terpBoundaries from "@terp/eslint-boundaries";\n' +
    'export default [{ ignores: ["node_modules/**"] }, ...terpBoundaries];\n';

  function runBin(root) {
    return spawnSync(process.execPath, [FINDINGS_BIN], { cwd: root, encoding: "utf8" });
  }

  it("publishes the envelope on stdout, humans on stderr, verdict as exit code", () => {
    const root = appRoot({
      "package.json": '{ "type": "module" }',
      "eslint.config.js": config,
      "escape-hatch-budget.json": "{}",
      "src/modules/sample/View.tsx": "export function View() {\n  return <button>x</button>;\n}\n",
    });
    const run = runBin(root);
    expect(run.status).toBe(1);
    const envelope = JSON.parse(run.stdout);
    expect(envelope.terp_findings).toBe(1);
    expect(envelope.findings.map((finding) => finding.rule)).toContain(
      "frontend/token-styled-elements",
    );
    expect(envelope.findings[0].path).toBe("src/modules/sample/View.tsx");
    expect(run.stderr).toMatch(/problem/);
  });

  it("stays green (exit 0) with an empty findings list on a clean app", () => {
    const root = appRoot({
      "package.json": '{ "type": "module" }',
      "eslint.config.js": config,
      "escape-hatch-budget.json": "{}",
      "src/modules/sample/View.tsx": "export const view = 1;\n",
    });
    const run = runBin(root);
    expect(run.status).toBe(0);
    const envelope = JSON.parse(run.stdout);
    expect(envelope.findings).toEqual([]);
    expect(envelope.unattributed).toEqual([]);
    // No layout-contract.json: the opt-in rule is not applicable, never "passing".
    expect(envelope.not_applicable).toEqual(["frontend/layout-contract"]);
    expect(envelope.rules).toEqual(
      catalogRuleIds().filter((id) => id !== "frontend/layout-contract"),
    );
  });

  it("reports budget drift even when the boundary lint fails (both halves always run)", () => {
    // The regression the merged bin exists for: with `eslint . && terp-boundaries-budget`
    // a boundary violation short-circuited the ratchet, hiding budget drift from the run.
    const root = appRoot({
      "package.json": '{ "type": "module" }',
      "eslint.config.js": config,
      "escape-hatch-budget.json": "{}",
      "src/modules/sample/View.tsx":
        "// terp-allow-no-eval: measured host quirk\n" +
        "export function View() {\n  return <button>x</button>;\n}\n",
    });
    const run = runBin(root);
    expect(run.status).toBe(1);
    const rules = JSON.parse(run.stdout).findings.map((finding) => finding.rule);
    expect(rules).toContain("frontend/token-styled-elements"); // the lint half
    expect(rules).toContain("frontend/escape-hatch"); // the ratchet half, not skipped
  });

  it("fails closed on a missing budget file, attributed to frontend/escape-hatch", () => {
    const root = appRoot({
      "package.json": '{ "type": "module" }',
      "eslint.config.js": config,
      "src/modules/sample/View.tsx": "export const view = 1;\n",
    });
    const run = runBin(root);
    expect(run.status).toBe(1);
    const envelope = JSON.parse(run.stdout);
    expect(envelope.findings).toHaveLength(1);
    expect(envelope.findings[0].rule).toBe("frontend/escape-hatch");
    expect(envelope.findings[0].message).toMatch(/budget file not found/);
  });

  it("includes layout-contract in the inventory when the app has opted in", () => {
    const root = appRoot({
      "package.json": '{ "type": "module" }',
      "eslint.config.js": config,
      "escape-hatch-budget.json": "{}",
      "layout-contract.json": '{ "contract": "standard" }',
      "src/modules/sample/View.tsx": "export const view = 1;\n",
    });
    const run = runBin(root);
    expect(run.status).toBe(0);
    const envelope = JSON.parse(run.stdout);
    expect(envelope.rules).toEqual(catalogRuleIds());
    expect(envelope.not_applicable).toEqual([]);
  });
});
