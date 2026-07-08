#!/usr/bin/env node
/**
 * The escape-hatch budget ratchet — the frontend analog of the backend's governed
 * `# arch-allow-*` budget (design §8): `terp-allow-*` marker counts in the app-authored
 * surface (`src/modules/**`) must match the checked-in `escape-hatch-budget.json` **exactly**.
 * A marker that rose needs a justified budget bump in the same change; one that dropped must
 * be lowered to lock in the win; an unbudgeted marker must be added with a justified count.
 * This keeps every boundary opt-out visible, greppable, and governed.
 *
 * Run it after the lint (`eslint . && terp-boundaries-budget`); it exits non-zero on any drift.
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

import { BOUNDARY_SPEC } from "./spec.js";
import { parseAllowMarkers } from "./index.js";

const MODULE_FILE_RE = /\.(?:ts|tsx)$/;

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

/** Compare actual marker counts to the budget; return human-readable problems (empty = clean). */
export function checkBudget(root, budgetPath) {
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
  const problems = [];
  for (const [name, count] of Object.entries(budget)) {
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
    if (!(name in budget)) {
      problems.push(`unbudgeted marker '${name}' used ${used} time(s); add it with a justified count`);
    }
  }
  return problems;
}

function main() {
  const root = process.cwd();
  const budgetPath = process.argv[2] ?? path.join(root, "escape-hatch-budget.json");
  const problems = checkBudget(root, budgetPath);
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
