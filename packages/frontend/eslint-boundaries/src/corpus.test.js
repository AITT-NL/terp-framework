/**
 * The ESLint adapter is held to the Terp Standard's violation corpus (ADR 0080).
 *
 * `spec/corpus/frontend/<rule>/` holds violating and compliant sample module files — the
 * executable meaning of each frontend catalog entry. This test lints every case with the real
 * boundary config and applies the corpus contract in terms of the **stack-neutral catalog id**
 * (findings are attributed through the adapter's published {@link catalogRuleId} mapping, never
 * the raw ESLint rule id — several catalog rules share a core rule id):
 *
 * - every `violation-*` case produces at least one finding attributed to the entry's catalog id;
 * - every `compliant-*` case is completely clean (no messages at all).
 *
 * The same corpus certifies any future stack's adapter (e.g. a Svelte realisation of
 * BOUNDARY_SPEC). The backend half lives in `tests/architecture/test_spec_corpus.py`.
 */

import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

import terpBoundaries, { catalogRuleId, LAYOUT_CONTRACT_FILE } from "./index.js";

// The spec is a declared dependency (@terp/spec, ADR 0082), never a repo-relative path —
// inside the monorepo it resolves to the workspace member; after a repo split, to the pin.
const SPEC_ROOT = path.dirname(
  createRequire(import.meta.url).resolve("@terp/spec/package.json"),
);
const CATALOG = path.join(SPEC_ROOT, "catalog", "frontend");
const CORPUS = path.join(SPEC_ROOT, "corpus", "frontend");

const entries = fs
  .readdirSync(CATALOG)
  .filter((name) => name.endsWith(".json"))
  .map((name) => JSON.parse(fs.readFileSync(path.join(CATALOG, name), "utf8")))
  .filter((entry) => entry.corpus);

function caseFiles(caseDir) {
  const files = [];
  const walk = (dir) => {
    for (const item of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, item.name);
      if (item.isDirectory()) walk(full);
      else files.push(full);
    }
  };
  walk(caseDir);
  return files;
}

/**
 * A case that ships a `layout-contract.json` at its root has opted into that layout
 * contract (exactly as a real app does, ADR 0079). The harness lints with virtual file
 * paths, so the rule's on-disk upward search cannot see the case's config; it is passed
 * through the rule's `contract` option instead — the same activation, spelled explicitly.
 */
function caseLayoutContract(caseDir) {
  const file = path.join(caseDir, LAYOUT_CONTRACT_FILE);
  if (!fs.existsSync(file)) return null;
  const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
  return typeof parsed.contract === "string" ? parsed.contract : null;
}

async function lintCase(caseDir) {
  return (await lintCaseFindings(caseDir)).map((finding) => finding.rule);
}

/** Lint a corpus case into spec-shaped findings (`findings.schema.json`): rule/path/line/message. */
async function lintCaseFindings(caseDir) {
  const contract = caseLayoutContract(caseDir);
  const overrideConfig =
    contract === null
      ? terpBoundaries
      : [
          ...terpBoundaries,
          {
            files: ["**/modules/**/*.{ts,tsx}"],
            rules: { "terp/layout-contract": ["error", { contract }] },
          },
        ];
  const eslint = new ESLint({ overrideConfigFile: true, overrideConfig });
  const findings = [];
  for (const file of caseFiles(caseDir)) {
    if (!/\.tsx?$/.test(file)) continue; // config carriers (layout-contract.json) are not linted
    // Resolve under the cwd so the config's `files` globs match the module path.
    const filePath = path.resolve(path.relative(caseDir, file));
    const [result] = await eslint.lintText(fs.readFileSync(file, "utf8"), { filePath });
    findings.push(
      ...result.messages.map((message) => ({
        rule: catalogRuleId(message),
        path: path.relative(caseDir, file).split(path.sep).join("/"),
        line: message.line,
        message: message.message,
      })),
    );
  }
  return findings;
}

describe("frontend corpus (spec/corpus/frontend)", () => {
  for (const entry of entries) {
    const rule = entry.id.split("/")[1];
    const ruleDir = path.join(CORPUS, rule);
    for (const caseName of fs.readdirSync(ruleDir).sort()) {
      if (caseName.startsWith("violation-")) {
        it(`${rule}/${caseName} is attributed to ${entry.id}`, async () => {
          expect(await lintCase(path.join(ruleDir, caseName))).toContain(entry.id);
        });
      } else {
        it(`${rule}/${caseName} is completely clean`, async () => {
          expect(await lintCase(path.join(ruleDir, caseName))).toEqual([]);
        });
      }
    }
  }
});

describe("findings round-trip (spec/findings.schema.json)", () => {
  // The reference adapter's output, rendered as spec findings, must validate against the
  // published finding format (ADR 0081) — the contract a Level 2 checker is certified on.
  const schema = JSON.parse(
    fs.readFileSync(path.join(SPEC_ROOT, "findings.schema.json"), "utf8"),
  );
  const item = schema.items;
  const rulePattern = new RegExp(item.properties.rule.pattern);

  it("every violation-case finding conforms to the published finding format", async () => {
    const findings = [];
    for (const entry of entries) {
      const ruleDir = path.join(CORPUS, entry.id.split("/")[1]);
      for (const caseName of fs.readdirSync(ruleDir).sort()) {
        if (!caseName.startsWith("violation-")) continue;
        findings.push(...(await lintCaseFindings(path.join(ruleDir, caseName))));
      }
    }
    expect(findings.length).toBeGreaterThan(0);
    for (const finding of findings) {
      for (const field of item.required) expect(finding).toHaveProperty(field);
      for (const field of Object.keys(finding)) {
        expect(Object.keys(item.properties)).toContain(field); // additionalProperties: false
      }
      expect(finding.rule).toMatch(rulePattern); // attributed to a catalog id, never a tool id
      expect(finding.path).not.toContain("\\"); // forward slashes, relative to the tree root
      expect(Number.isInteger(finding.line)).toBe(true);
      expect(finding.line).toBeGreaterThanOrEqual(item.properties.line.minimum);
      expect(finding.message.trim()).not.toBe("");
    }
  });
});
