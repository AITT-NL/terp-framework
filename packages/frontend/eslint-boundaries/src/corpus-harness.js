/**
 * The frontend corpus harness: lint a Terp Standard corpus case into spec-shaped
 * findings, exactly as an app's own boundary lint would see it.
 *
 * Shared by the certification test (corpus.test.js) and the scorecard emitter
 * (scorecard.js), so the two can never apply different corpus semantics. The spec
 * is resolved as a declared dependency (@terp/spec, ADR 0082) by the CALLER —
 * this module takes paths, never resolves the spec itself.
 */

import fs from "node:fs";
import path from "node:path";

import { ESLint } from "eslint";

import terpBoundaries, { LAYOUT_CONTRACT_FILE, catalogRuleId } from "./index.js";

/** Every file below *caseDir*, recursively. */
export function caseFiles(caseDir) {
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
export function caseLayoutContract(caseDir) {
  const file = path.join(caseDir, LAYOUT_CONTRACT_FILE);
  if (!fs.existsSync(file)) return null;
  const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
  return typeof parsed.contract === "string" ? parsed.contract : null;
}

/** Lint a corpus case into spec-shaped findings (`findings.schema.json`): rule/path/line/message. */
export async function lintCaseFindings(caseDir) {
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
