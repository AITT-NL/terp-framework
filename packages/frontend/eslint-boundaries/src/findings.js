#!/usr/bin/env node
/**
 * The machine-readable boundary lint — the frontend analog of `terp check --format json`.
 *
 * `terp-boundaries-lint` runs the shipped boundary config on app source, the app's own
 * ESLint config on its configured files, and the escape-hatch budget ratchet (the same
 * check `terp-boundaries-budget` runs) in one command, and publishes one **findings
 * envelope** on stdout:
 *
 *   { "terp_findings": 1, "tool": "@terpjs/eslint-boundaries",
 *     "ok": true,                                // did this run pass? (no findings)
 *     "rules": ["frontend/<rule>", …],          // every catalog rule this run evaluated
 *     "not_applicable": ["frontend/<rule>", …], // opt-in rules this app has not enabled
 *     "findings": [{ rule, path, line, message }, …],   // spec findings.schema.json shape
 *     "unattributed": [{ path, line, message, reported_as }, …] }
 *
 * `terp_findings: 1` is the envelope's **format version**, not a count — it is the
 * discriminator a consumer matches on (the same role `terp_check_report: 1` plays for
 * the check report) and it stays 1 whether the run found zero problems or twenty. The
 * count lives in `findings.length`, and the verdict in `ok`. Reading the marker as a
 * finding count is a real reported misread, which is why `ok` is there: a consumer that
 * wants "did this pass" should never have to interpret a version number.
 *
 * `rules` is the evaluated-rule inventory ({@link catalogRuleIds}, minus the opt-in
 * rules listed under `not_applicable` — today `frontend/layout-contract` when the app
 * has no checked-in layout-contract.json, so a consumer never renders an unenforced
 * rule as passing). `findings` are the reported messages attributed to their
 * catalog ids through the adapter's published {@link catalogRuleId}
 * mapping, plus any budget drift attributed to `frontend/escape-hatch`. A message
 * outside the boundary (another configured rule, a parse error) lands in
 * `unattributed` — surfaced, never dropped. The human-readable report goes to stderr,
 * so `npm run lint` failures stay legible while a driving tool (the Studio's gate, a
 * CI annotator) parses stdout.
 *
 * Both halves ALWAYS run — a boundary violation cannot skip the budget ratchet the way
 * an `eslint . && terp-boundaries-budget` chain could — and the exit code is the
 * combined verdict (non-zero when either half failed). An optional positional argument
 * names the budget file (default `escape-hatch-budget.json`, as the budget bin). *
 * `--format check-report` prints the Terp Standard **check report** instead
 * (`app-check-report.schema.json`: the same inventory and findings, self-described with
 * `spec_version`, the checker identity, and the run verdict) — still exactly one JSON
 * document on stdout. The default stays the legacy `terp_findings` envelope, a published
 * seam (ADR 0083) existing consumers parse strictly. */

import fs from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

import { ESLint } from "eslint";

import { checkBudget, sourceFiles } from "./budget.js";
import { activeLayoutContract, catalogRuleId, catalogRuleIds, terpBoundaries } from "./index.js";
import { SPEC_VERSION } from "./spec.js";

/** This package's own version — the `checker.version` a check report carries. */
const PACKAGE_VERSION = JSON.parse(
  fs.readFileSync(new URL("../package.json", import.meta.url), "utf8"),
).version;

/**
 * Render a findings envelope as the Terp Standard **check report**
 * (`app-check-report.schema.json`, printed by `--format check-report`): the same
 * inventory and findings, self-described with the release of the report format, the
 * checker identity (whose version names the catalog release the rule ids resolve
 * against: the catalog ships with this package, ADR 0203), and the run verdict — so a
 * consumer joins per-rule verdicts to the catalog without knowing this toolchain.
 * `unattributed.reported_as` is omitted (never null) per the schema; `ok` covers the
 * standard's own findings (the process exit code stays the combined verdict,
 * unattributed errors included).
 */
export function asCheckReport(envelope) {
  return {
    terp_check_report: 1,
    spec_version: SPEC_VERSION,
    checker: { tool: envelope.tool, version: PACKAGE_VERSION },
    ok: envelope.findings.length === 0,
    rules: envelope.rules,
    not_applicable: envelope.not_applicable,
    findings: envelope.findings,
    unattributed: envelope.unattributed.map(({ path: file, line, message, reported_as }) => ({
      path: file,
      ...(Number.isInteger(line) && line >= 1 ? { line } : {}),
      message,
      ...(typeof reported_as === "string" && reported_as !== "" ? { reported_as } : {}),
    })),
  };
}

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
  const seen = new Set();
  for (const result of results) {
    const relative = path.relative(cwd, result.filePath).split(path.sep).join("/");
    const file = relative === "" ? result.filePath.split(path.sep).join("/") : relative;
    for (const message of result.messages) {
      // The app config normally includes Terp. Publish a shared diagnostic once.
      const key = JSON.stringify([file, message.line, message.column, message.ruleId, message.message]);
      if (seen.has(key)) continue;
      seen.add(key);
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
      tool: "@terpjs/eslint-boundaries",
      // The verdict, stated: `terp_findings` is a format version and reads like a
      // count, so leaving "did it pass" implicit invites the wrong answer.
      ok: findings.length === 0,
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
  const args = process.argv.slice(2);
  // `--format check-report` prints the Terp Standard check report
  // (app-check-report.schema.json) instead of the legacy terp_findings envelope —
  // still exactly ONE JSON document on stdout, so strict consumers keep a single
  // parse. The default stays the legacy envelope (a published seam, ADR 0083).
  let format = "findings";
  const formatIndex = args.indexOf("--format");
  if (formatIndex !== -1) {
    const value = args[formatIndex + 1];
    if (value !== "findings" && value !== "check-report") {
      process.stderr.write(
        `terp-boundaries-lint: unsupported --format ${value ?? "(missing)"}; ` +
          "expected findings or check-report\n",
      );
      process.exit(2);
    }
    format = value;
    args.splice(formatIndex, 2);
  }
  const budgetPath = args[0] ?? path.join(cwd, "escape-hatch-budget.json");
  // Evaluate the published inventory with the package's config before loading app config.
  // The budget and the lint walk the same app-authored files, including files an app ignores.
  const sources = sourceFiles(cwd);
  const boundaries = new ESLint({
    overrideConfigFile: true,
    overrideConfig: terpBoundaries(),
    globInputPaths: false,
  });
  const mandatory = sources.length ? await boundaries.lintFiles(sources) : [];

  // The app's own config and ignore set. Two rules also read checked-in declarations
  // outside the linted source file, so include those bytes in the cache namespace.
  // Otherwise fixing i18n.json can replay a stale failure, and breaking it after a
  // cached pass can stay falsely green until a source file happens to change.
  const externalInputs = ["i18n.json", "layout-contract.json"].map((name) => {
    const file = path.join(cwd, name);
    return fs.existsSync(file) ? fs.readFileSync(file) : Buffer.from("<missing>");
  });
  const hash = createHash("sha256").update(externalInputs[0]).update("\0").update(externalInputs[1]);
  // CSS Modules are linted from the importing component. Editing or deleting just its
  // stylesheet must invalidate the same cached result as changing the JSX.
  // A repacked adapter can change the CSS policy without changing app sources.
  hash.update("\0").update(fs.readFileSync(new URL("./cssModules.js", import.meta.url)));
  hash.update("\0").update(fs.readFileSync(new URL("./bootstrapSheets.js", import.meta.url)));
  for (const file of fs.globSync("src/**/*.module.css", { cwd }).sort()) {
    hash.update("\0").update(file).update("\0").update(fs.readFileSync(path.join(cwd, file)));
  }
  // The bootstrap's two token sheets are read from src/main.tsx the same way (ADR 0225): a
  // change to one alone must not replay the bootstrap's cached verdict.
  for (const file of ["src/house-style.css", "src/theme.css"]) {
    const absolute = path.join(cwd, file);
    hash.update("\0").update(file).update("\0")
      .update(fs.existsSync(absolute) ? fs.readFileSync(absolute) : Buffer.from("<missing>"));
  }
  const declarationHash = hash.digest("hex").slice(0, 16);
  const eslint = new ESLint({
    cache: true,
    cacheLocation: path.join(
      "node_modules",
      ".cache",
      "eslint",
      `declarations-${declarationHash}`,
      ".eslintcache",
    ),
  });
  const results = [...mandatory, ...await eslint.lintFiles(["."])];
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
  const document = format === "check-report" ? asCheckReport(envelope) : envelope;
  process.stdout.write(`${JSON.stringify(document)}\n`);
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
