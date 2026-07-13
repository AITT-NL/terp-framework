#!/usr/bin/env node
/**
 * The machine-readable boundary lint — the frontend analog of `terp check --format json`.
 *
 * `terp-boundaries-lint` runs the app's own ESLint config (the flat config in the cwd,
 * exactly what `eslint .` would load) **and** the escape-hatch budget ratchet (the same
 * check `terp-boundaries-budget` runs) in one command, and publishes one **findings
 * envelope** on stdout:
 *
 *   { "terp_findings": 1, "tool": "@terp/eslint-boundaries",
 *     "rules": ["frontend/<rule>", …],          // every catalog rule this run evaluated
 *     "not_applicable": ["frontend/<rule>", …], // opt-in rules this app has not enabled
 *     "findings": [{ rule, path, line, message }, …],   // spec findings.schema.json shape
 *     "unattributed": [{ path, line, message, reported_as }, …] }
 *
 * `rules` is the evaluated-rule inventory ({@link catalogRuleIds}, minus the opt-in
 * rules listed under `not_applicable` — today `frontend/layout-contract` when the app
 * has no checked-in layout-contract.json, so a consumer never renders an unenforced
 * rule as passing). `findings` are the reported messages attributed to their
 * stack-neutral catalog ids through the adapter's published {@link catalogRuleId}
 * mapping, plus any budget drift attributed to `frontend/escape-hatch`. A message
 * outside the boundary (another configured rule, a parse error) lands in
 * `unattributed` — surfaced, never dropped. The human-readable report goes to stderr,
 * so `npm run lint` failures stay legible while a driving tool (the Studio's gate, a
 * CI annotator) parses stdout.
 *
 * Both halves ALWAYS run — a boundary violation cannot skip the budget ratchet the way
 * an `eslint . && terp-boundaries-budget` chain could — and the exit code is the
 * combined verdict (non-zero when either half failed). An optional positional argument
 * names the budget file (default `escape-hatch-budget.json`, as the budget bin).
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

import { ESLint } from "eslint";

import { checkBudget } from "./budget.js";
import { activeLayoutContract, catalogRuleId, catalogRuleIds } from "./index.js";

/**
 * Render lint *results* (ESLint result objects) as the findings envelope plus the
 * human report lines. Paths are cwd-relative with `/` separators on every OS — the
 * envelope is a machine contract, not display text.
 *
 * Options mirror what the bin derives from the app checkout: `layoutContract`
 * (is the opt-in slot-typed contract active? default: the same upward
 * `layout-contract.json` search the ESLint rule performs from *cwd*),
 * `budgetProblems` (escape-hatch budget drift, appended as
 * `frontend/escape-hatch` findings) and `budgetFile` (the path those findings cite).
 */
export function renderEnvelope(results, cwd = process.cwd(), options = {}) {
  const {
    layoutContract = activeLayoutContract(cwd) !== null,
    budgetProblems = [],
    budgetFile = "escape-hatch-budget.json",
  } = options;
  const findings = [];
  const unattributed = [];
  const human = [];
  for (const result of results) {
    const relative = path.relative(cwd, result.filePath).split(path.sep).join("/");
    const file = relative === "" ? result.filePath.split(path.sep).join("/") : relative;
    for (const message of result.messages) {
      const rule = catalogRuleId(message);
      const line = Number.isInteger(message.line) && message.line > 0 ? message.line : 1;
      if (rule === null) {
        unattributed.push({
          path: file,
          line,
          message: message.message,
          reported_as: message.ruleId ?? null,
        });
      } else {
        findings.push({ rule, path: file, line, message: message.message });
      }
      human.push(
        `${file}:${line}:${message.column ?? 1}  ${message.message}  [${rule ?? message.ruleId ?? "parse"}]`,
      );
    }
  }
  for (const problem of budgetProblems) {
    findings.push({ rule: "frontend/escape-hatch", path: budgetFile, message: problem });
    human.push(`${budgetFile}  ${problem}  [frontend/escape-hatch]`);
  }
  // An opt-in rule the app has not enabled is published as not-applicable — never
  // silently kept in `rules`, where "evaluated, zero findings" would read as passing.
  const notApplicable = layoutContract ? [] : ["frontend/layout-contract"];
  return {
    envelope: {
      terp_findings: 1,
      tool: "@terp/eslint-boundaries",
      rules: catalogRuleIds().filter((id) => !notApplicable.includes(id)),
      not_applicable: notApplicable,
      findings,
      unattributed,
    },
    human,
  };
}

async function main() {
  const cwd = process.cwd();
  const budgetPath = process.argv[2] ?? path.join(cwd, "escape-hatch-budget.json");
  // The app's own config and ignore set, with the same cache the plain CLI used
  // (`--cache --cache-location node_modules/.cache/eslint/`).
  const eslint = new ESLint({ cache: true, cacheLocation: "node_modules/.cache/eslint/" });
  const results = await eslint.lintFiles(["."]);
  // The ratchet runs regardless of the lint verdict — both halves always report.
  const budgetProblems = checkBudget(cwd, budgetPath);
  const relativeBudget = path.relative(cwd, budgetPath).split(path.sep).join("/");
  const { envelope, human } = renderEnvelope(results, cwd, {
    budgetProblems,
    budgetFile: relativeBudget === "" ? budgetPath.split(path.sep).join("/") : relativeBudget,
  });
  if (human.length > 0) {
    process.stderr.write(
      `${human.join("\n")}\n${human.length} problem(s); the findings envelope is on stdout.\n`,
    );
  }
  process.stdout.write(`${JSON.stringify(envelope)}\n`);
  const errors =
    results.reduce((sum, result) => sum + result.errorCount, 0) + budgetProblems.length;
  process.exitCode = errors > 0 ? 1 : 0;
}

// Run main() only when invoked as a CLI (directly or via the npm bin symlink), not on import.
const entry = process.argv[1] ? pathToFileURL(fs.realpathSync(process.argv[1])).href : "";
if (entry === import.meta.url) {
  main().catch((error) => {
    // The lint could not run at all (no config, ESLint crash) — distinct from "ran and failed".
    console.error(String(error));
    process.exitCode = 2;
  });
}
