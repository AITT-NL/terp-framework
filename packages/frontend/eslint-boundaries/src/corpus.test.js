/**
 * The ESLint adapter is held to its violation corpus (ADR 0080, ADR 0203).
 *
 * `corpus/frontend/<rule>/` (beside this package's sources) holds violating and compliant sample
 * module files: the executable meaning of each frontend catalog entry in `catalog/frontend/`. This
 * test lints every case with the real boundary config and applies the corpus contract in terms of
 * the **catalog id** (findings are attributed through the adapter's published {@link catalogRuleId}
 * mapping, never the raw ESLint rule id — several catalog rules share a core rule id):
 *
 * - every `violation-*` case produces at least one finding attributed to the entry's catalog id;
 * - every `compliant-*` case is completely clean (no messages at all).
 *
 * The rules, their entries and their cases live together (ADR 0203), so a rule, its entry and its
 * cases land in one change. The backend half lives in `tests/architecture/test_rule_corpus.py`.
 */

import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { lintCaseFindings } from "./corpus-harness.js";

const PACKAGE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const CATALOG = path.join(PACKAGE_ROOT, "catalog", "frontend");
const CORPUS = path.join(PACKAGE_ROOT, "corpus", "frontend");
// The finding format is a contract more than one program reads, so it stays in the shared
// contracts package (ADR 0203), resolved as a declared dependency, never a repo path.
const CONTRACTS_ROOT = path.dirname(
  createRequire(import.meta.url).resolve("@terpjs/spec/package.json"),
);

const catalogEntries = fs
  .readdirSync(CATALOG)
  .filter((name) => name.endsWith(".json"))
  .map((name) => JSON.parse(fs.readFileSync(path.join(CATALOG, name), "utf8")));
const entries = catalogEntries.filter((entry) => entry.corpus);

async function lintCase(caseDir) {
  return (await lintCaseFindings(caseDir)).map((finding) => finding.rule);
}

describe("frontend corpus (corpus/frontend)", () => {
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

describe("findings round-trip (findings.schema.json)", () => {
  // The adapter's output, rendered as findings, must validate against the finding format, the
  // contract every reader of a check report is held to.
  const schema = JSON.parse(
    fs.readFileSync(path.join(CONTRACTS_ROOT, "findings.schema.json"), "utf8"),
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
