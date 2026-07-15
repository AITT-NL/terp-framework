#!/usr/bin/env node
/**
 * The escape-hatch budget ratchet — the frontend analog of the backend's governed
 * `# arch-allow-*` budget (design §8): `terp-allow-*` marker counts in the app-authored
 * surface (`src/modules/**`) must match the checked-in `escape-hatch-budget.json` **exactly**.
 * A marker that rose needs a justified budget bump in the same change; one that dropped must
 * be lowered to lock in the win; an unbudgeted marker must be added with a justified count.
 * This keeps every boundary opt-out visible, greppable, and governed.
 *
 * Run it standalone or in CI (`terp-boundaries-budget [budget-path]`); the app lint
 * command (`terp-boundaries-lint`) runs the same {@link checkBudget} in-process, so the
 * ratchet can never be skipped by a failing lint. It exits non-zero on any drift.
 * `--format json` additionally publishes the drift as a findings envelope on stdout,
 * attributed to `frontend/escape-hatch` (see ./findings.js).
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

import { BOUNDARY_SPEC } from "./spec.js";
import { knownMarkerNames, parseAllowMarkers } from "./index.js";

const MODULE_FILE_RE = /\.(?:ts|tsx)$/;

/** The `review-by:<YYYY-MM-DD>` metadata token in a marker's reason (the Terp
 * Standard's escape-hatch contract): when the exception must be re-justified.
 * The tokens are a convention, not a gate — a reason without one is never
 * rejected — but the spec says a toolchain SHOULD surface *expired* dates. */
const REVIEW_BY_RE = /review-by:\s*(\d{4}-\d{2}-\d{2})/g;

/** A strictly valid calendar date from a `YYYY-MM-DD` token, else null — a
 * malformed date (2026-13-45) is not a well-formed token and never fires. */
function parsedReviewDate(value) {
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  const roundTrips =
    date.getUTCFullYear() === year &&
    date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day;
  return roundTrips ? date : null;
}

/** Every `src/modules/**` TypeScript file under *root*, recursively. */
function moduleFiles(root) {
  const modulesRoot = path.join(root, "src", "modules");
  if (!fs.existsSync(modulesRoot)) {
    return [];
  }
  const files = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (MODULE_FILE_RE.test(entry.name)) {
        files.push(full);
      }
    }
  };
  walk(modulesRoot);
  return files;
}

/** Actual `terp-allow-<rule>` marker counts across the app-authored surface. */
export function countMarkers(root) {
  const counts = {};
  for (const file of moduleFiles(root)) {
    for (const marker of parseAllowMarkers(fs.readFileSync(file, "utf-8"))) {
      const name = `${BOUNDARY_SPEC.allowMarkerPrefix}${marker.rule}`;
      counts[name] = (counts[name] ?? 0) + 1;
    }
  }
  return counts;
}

/** Compare actual marker counts to the budget; return human-readable problems (empty = clean).
 *
 * A marker (or budget key) that names no rule with a governed opt-out — a typo, a
 * stale name, or the governance rule's own name — is refused outright: an unknown
 * marker can never be budgeted into legitimacy. A marker reason MAY carry the spec's
 * `review-by:<YYYY-MM-DD>` metadata token; one whose date has passed is surfaced as a
 * problem naming the marker's own file:line (re-justify the exception or remove it —
 * a long-lived opt-out is never silently eternal). Reasons without the token are never
 * rejected. *today* is injectable for tests; the default is the real current date.
 */
export function checkBudget(root, budgetPath, today = new Date()) {
  let raw;
  try {
    raw = fs.readFileSync(budgetPath, "utf-8");
  } catch {
    return [`budget file not found: ${budgetPath}; create it (e.g. '{}') to govern opt-outs`];
  }
  let budget;
  try {
    budget = JSON.parse(raw);
  } catch (error) {
    return [`budget is not valid JSON: ${error.message}`];
  }
  if (
    budget === null ||
    typeof budget !== "object" ||
    Array.isArray(budget) ||
    !Object.values(budget).every((count) => Number.isInteger(count))
  ) {
    return ["budget must be a JSON object mapping each 'terp-allow-*' marker to an integer count"];
  }
  const actual = countMarkers(root);
  const known = knownMarkerNames();
  const problems = [];
  const isGoverned = (name) =>
    name.startsWith(BOUNDARY_SPEC.allowMarkerPrefix) &&
    known.has(name.slice(BOUNDARY_SPEC.allowMarkerPrefix.length));
  for (const name of [...new Set([...Object.keys(budget), ...Object.keys(actual)])].sort()) {
    if (!isGoverned(name)) {
      problems.push(
        `'${name}' names no rule with a governed opt-out; remove the marker/budget entry ` +
          "(opt-out markers name the Terp Standard catalog rule)",
      );
    }
  }
  for (const [name, count] of Object.entries(budget)) {
    if (!isGoverned(name)) {
      continue;
    }
    const used = actual[name] ?? 0;
    if (used < count) {
      problems.push(
        `marker '${name}' dropped to ${used} (budget ${count}); lower the budget to lock in the win`,
      );
    } else if (used > count) {
      problems.push(
        `marker '${name}' rose to ${used} (budget ${count}); justify the bump in the same change`,
      );
    }
  }
  for (const [name, used] of Object.entries(actual)) {
    if (isGoverned(name) && !(name in budget)) {
      problems.push(`unbudgeted marker '${name}' used ${used} time(s); add it with a justified count`);
    }
  }
  // Date-only comparison (like the backend checker): a review-by dated today
  // is due, not yet passed.
  const deadline = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  for (const file of moduleFiles(root)) {
    const relative = path.relative(root, file).split(path.sep).join("/");
    for (const marker of parseAllowMarkers(fs.readFileSync(file, "utf-8"))) {
      if (marker.reason === null) {
        continue;
      }
      for (const match of marker.reason.matchAll(REVIEW_BY_RE)) {
        const reviewBy = parsedReviewDate(match[1]);
        if (reviewBy !== null && reviewBy.getTime() < deadline) {
          problems.push(
            `marker '${BOUNDARY_SPEC.allowMarkerPrefix}${marker.rule}' at ${relative}:${marker.line} ` +
              `has a passed review date (review-by:${match[1]}); re-justify the exception ` +
              "with a new review-by date or remove the marker",
          );
        }
      }
    }
  }
  return problems;
}

function main() {
  const args = process.argv.slice(2);
  // `--format json` additionally publishes the drift as a findings envelope on stdout
  // (attributed to `frontend/escape-hatch`), so a driving tool joins the budget verdict
  // to the Terp Standard catalog without parsing prose. Humans keep reading stderr.
  let format = "text";
  const formatIndex = args.indexOf("--format");
  if (formatIndex !== -1) {
    const value = args[formatIndex + 1];
    if (value !== "json") {
      console.error(`escape-hatch-budget: unsupported --format ${value ?? "(missing)"}; expected json`);
      process.exit(2);
    }
    format = "json";
    args.splice(formatIndex, 2);
  }
  const root = process.cwd();
  const budgetPath = args[0] ?? path.join(root, "escape-hatch-budget.json");
  const problems = checkBudget(root, budgetPath);
  if (format === "json") {
    const relative = path.relative(root, budgetPath).split(path.sep).join("/");
    const budgetFile = relative === "" ? budgetPath.split(path.sep).join("/") : relative;
    console.log(
      JSON.stringify({
        terp_findings: 1,
        tool: "terp-boundaries-budget",
        rules: ["frontend/escape-hatch"],
        findings: problems.map((problem) => ({
          rule: "frontend/escape-hatch",
          path: budgetFile,
          message: problem,
        })),
        unattributed: [],
      }),
    );
  }
  if (problems.length > 0) {
    for (const problem of problems) {
      console.error(`escape-hatch-budget: ${problem}`);
    }
    process.exit(1);
  }
}

// Run main() only when invoked as a CLI (directly or via the npm bin symlink), not on import.
const entry = process.argv[1] ? pathToFileURL(fs.realpathSync(process.argv[1])).href : "";
if (entry === import.meta.url) {
  main();
}
