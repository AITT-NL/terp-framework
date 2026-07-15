/**
 * The scorecard emitter is held to the published certification contract
 * (spec/scorecard.schema.json): the adapter's scorecard validates, claims the
 * whole corpus-covered frontend catalog, passes it, and only relies on the
 * residuals the spec records. The emitter reuses the corpus test's own harness
 * (./corpus-harness.js), so a scorecard can never disagree with the suite.
 */

import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { buildScorecard, validateScorecard } from "./scorecard.js";

const SPEC_ROOT = path.dirname(
  createRequire(import.meta.url).resolve("@terp/spec/package.json"),
);

describe("the @terp/eslint-boundaries scorecard", () => {
  it("claims the whole corpus-covered catalog, green, schema-shaped", async () => {
    const scorecard = await buildScorecard();
    expect(validateScorecard(scorecard)).toEqual([]);

    // Schema shape, field by field (the spec suite's minimal-validator discipline).
    const schema = JSON.parse(
      fs.readFileSync(path.join(SPEC_ROOT, "scorecard.schema.json"), "utf8"),
    );
    for (const field of schema.required) expect(scorecard).toHaveProperty(field);
    for (const field of Object.keys(scorecard)) {
      expect(Object.keys(schema.properties)).toContain(field);
    }
    expect(scorecard.spec_version).toBe(
      fs.readFileSync(path.join(SPEC_ROOT, "VERSION"), "utf8").trim(),
    );
    expect(scorecard.checker.tool).toBe("@terp/eslint-boundaries");
    const itemProperties = Object.keys(schema.properties.rules.items.properties);
    for (const claim of scorecard.rules) {
      expect(claim.pass).toBe(true);
      for (const field of Object.keys(claim)) expect(itemProperties).toContain(field);
    }
  }, 120_000);

  it("rejects a scorecard claiming an unrecorded residual or a failing rule", async () => {
    const scorecard = await buildScorecard();
    const failing = {
      ...scorecard,
      rules: [{ ...scorecard.rules[0], pass: false }, ...scorecard.rules.slice(1)],
    };
    expect(validateScorecard(failing).join("\n")).toMatch(/must pass its own corpus/);
    const overclaiming = {
      ...scorecard,
      rules: [
        { ...scorecard.rules[0], residuals_claimed: ["a residual the spec never recorded"] },
        ...scorecard.rules.slice(1),
      ],
    };
    expect(validateScorecard(overclaiming).join("\n")).toMatch(/unrecorded residual/);
  }, 120_000);
});
