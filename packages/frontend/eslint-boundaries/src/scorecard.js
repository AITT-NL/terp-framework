#!/usr/bin/env node
/**
 * Emit the Terp Standard conformance scorecard for `@terp/eslint-boundaries`
 * (the frontend checker).
 *
 * The scorecard (`scorecard.schema.json` in the spec) turns "certified against
 * spec X.Y.Z" into a verifiable artifact: one entry per frontend catalog rule
 * with its pass/fail verdict over the violation corpus, plus the detector
 * residuals the adapter relies on (held to a subset of the spec's recorded
 * `corpus/RESIDUALS.json`). A consumer re-runs the corpus and reproduces it.
 *
 * A certification-context tool, not an app tool: it needs `@terp/spec` (a dev
 * dependency of the platform repo) and runs the SAME harness the corpus test
 * uses (./corpus-harness.js), so the scorecard can never disagree with the
 * suite. Self-validates and refuses to write an invalid or failing scorecard
 * (exit 1).
 *
 *   node packages/frontend/eslint-boundaries/src/scorecard.js --out scorecard.json
 */

import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

import { lintCaseFindings } from "./corpus-harness.js";

const require = createRequire(import.meta.url);

const RULE_ID_RE = /^(backend\/[a-z0-9_]+|frontend\/[a-z0-9-]+)$/;
const SEMVER_RE = /^\d+\.\d+\.\d+$/;

/** The @terp/spec root — resolved lazily so importing this module never requires it. */
function specRoot() {
  return path.dirname(require.resolve("@terp/spec/package.json"));
}

/** Build the @terp/eslint-boundaries scorecard over the frontend corpus. */
export async function buildScorecard() {
  const root = specRoot();
  const catalogDir = path.join(root, "catalog", "frontend");
  const corpusDir = path.join(root, "corpus", "frontend");
  const residuals = JSON.parse(
    fs.readFileSync(path.join(root, "corpus", "RESIDUALS.json"), "utf8"),
  ).residuals;
  const packageVersion = JSON.parse(
    fs.readFileSync(new URL("../package.json", import.meta.url), "utf8"),
  ).version;

  const rules = [];
  const entries = fs
    .readdirSync(catalogDir)
    .filter((name) => name.endsWith(".json"))
    .map((name) => JSON.parse(fs.readFileSync(path.join(catalogDir, name), "utf8")))
    .filter((entry) => entry.corpus);
  for (const entry of entries) {
    const ruleDir = path.join(corpusDir, entry.id.split("/")[1]);
    let pass = true;
    for (const caseName of fs.readdirSync(ruleDir).sort()) {
      const caseDir = path.join(ruleDir, caseName);
      if (!fs.statSync(caseDir).isDirectory()) continue;
      const fired = (await lintCaseFindings(caseDir)).map((finding) => finding.rule);
      if (caseName.startsWith("violation-") && !fired.includes(entry.id)) pass = false;
      if (caseName.startsWith("compliant-") && fired.length > 0) pass = false;
    }
    const claim = { rule: entry.id, pass };
    if (residuals[entry.id]?.length) claim.residuals_claimed = [...residuals[entry.id]];
    rules.push(claim);
  }
  return {
    spec_version: fs.readFileSync(path.join(root, "VERSION"), "utf8").trim(),
    checker: { tool: "@terp/eslint-boundaries", version: packageVersion },
    rules,
  };
}

/** Hold the scorecard to its published contract; returns the problems. */
export function validateScorecard(scorecard) {
  const problems = [];
  if (!SEMVER_RE.test(String(scorecard.spec_version ?? ""))) {
    problems.push("spec_version is not a semver string");
  }
  if (!scorecard.checker?.tool || !scorecard.checker?.version) {
    problems.push("checker must carry tool and version");
  }
  const root = specRoot();
  const residuals = JSON.parse(
    fs.readFileSync(path.join(root, "corpus", "RESIDUALS.json"), "utf8"),
  ).residuals;
  const catalogued = fs
    .readdirSync(path.join(root, "catalog", "frontend"))
    .filter((name) => name.endsWith(".json"))
    .map((name) =>
      JSON.parse(fs.readFileSync(path.join(root, "catalog", "frontend", name), "utf8")),
    )
    .filter((entry) => entry.corpus)
    .map((entry) => entry.id);
  const rules = scorecard.rules ?? [];
  if (rules.length === 0) problems.push("a scorecard without rule claims certifies nothing");
  const claimed = new Set();
  for (const claim of rules) {
    claimed.add(claim.rule);
    if (!RULE_ID_RE.test(String(claim.rule ?? ""))) {
      problems.push(`bad rule id: ${claim.rule}`);
    }
    if (typeof claim.pass !== "boolean") {
      problems.push(`${claim.rule}: pass must be a boolean`);
    } else if (!claim.pass) {
      problems.push(`${claim.rule}: the reference adapter must pass its own corpus`);
    }
    for (const residual of claim.residuals_claimed ?? []) {
      if (!(residuals[claim.rule] ?? []).includes(residual)) {
        problems.push(`${claim.rule}: claims an unrecorded residual: ${residual}`);
      }
    }
  }
  const missing = catalogued.filter((id) => !claimed.has(id));
  if (missing.length > 0) {
    problems.push(`corpus-covered rules missing a claim: ${missing.join(", ")}`);
  }
  return problems;
}

async function main() {
  const args = process.argv.slice(2);
  const outIndex = args.indexOf("--out");
  const out = outIndex !== -1 ? args[outIndex + 1] : "";
  const scorecard = await buildScorecard();
  const problems = validateScorecard(scorecard);
  if (problems.length > 0) {
    for (const problem of problems) process.stderr.write(`scorecard: ${problem}\n`);
    process.exitCode = 1;
    return;
  }
  const rendered = `${JSON.stringify(scorecard, null, 2)}\n`;
  if (out) {
    fs.writeFileSync(out, rendered);
    process.stderr.write(
      `wrote ${out} (${scorecard.rules.length} rule claims, spec ${scorecard.spec_version})\n`,
    );
  } else {
    process.stdout.write(rendered);
  }
}

// Run main() only when invoked as a CLI, not on import (the findings.js pattern).
const entry = process.argv[1] ? pathToFileURL(fs.realpathSync(process.argv[1])).href : "";
if (entry === import.meta.url) {
  main().catch((error) => {
    console.error(String(error));
    process.exitCode = 2;
  });
}
