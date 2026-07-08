/**
 * The reference adapter is held to the spec's declared refused surface (`spec/restricted-surface.json`).
 *
 * The refused raw frontend surface is spec **data**, not adapter code: the stack-neutral,
 * normative part of the portable prohibition rules is the list of raw primitives an app module
 * must not author; which sanctioned component answers each primitive is per-stack configuration
 * (the catalog entries' non-normative `reference` field). This test locks the two together:
 *
 * - structurally: `BOUNDARY_SPEC` realises exactly the declared surface (no drift in either
 *   direction — an element/attribute/global added to one side must be added to the other);
 * - behaviourally: authoring each declared primitive in an app module produces a finding
 *   attributed to the expected catalog id (through the published {@link catalogRuleId} mapping,
 *   exactly as the corpus contract states).
 */

import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

import terpBoundaries, { BOUNDARY_SPEC, catalogRuleId } from "./index.js";

// The spec is a declared dependency (@terp/spec, ADR 0082), never a repo-relative path.
const SPEC_ROOT = path.dirname(
  createRequire(import.meta.url).resolve("@terp/spec/package.json"),
);
const SURFACE = JSON.parse(
  fs.readFileSync(path.join(SPEC_ROOT, "restricted-surface.json"), "utf8"),
);

async function lintModuleSource(source) {
  const eslint = new ESLint({ overrideConfigFile: true, overrideConfig: terpBoundaries });
  const filePath = path.resolve("src/modules/widgets/Widget.tsx");
  const [result] = await eslint.lintText(source, { filePath });
  return result.messages.map((message) => catalogRuleId(message));
}

describe("structural parity: BOUNDARY_SPEC realises exactly the declared surface", () => {
  it("restricted elements match", () => {
    expect(Object.keys(BOUNDARY_SPEC.restrictedElements).sort()).toEqual(
      [...SURFACE.restrictedElements].sort(),
    );
  });

  it("restricted attributes match", () => {
    expect([...BOUNDARY_SPEC.restrictedAttributes].sort()).toEqual(
      [...SURFACE.restrictedAttributes].sort(),
    );
  });

  it("restricted globals match", () => {
    expect([...BOUNDARY_SPEC.restrictedGlobals].sort()).toEqual(
      [...SURFACE.restrictedGlobals].sort(),
    );
  });

  it("every declared stylesheet extension is refused by the import patterns", () => {
    for (const extension of SURFACE.styleImportExtensions) {
      expect(BOUNDARY_SPEC.styleImportPatterns).toContain(`**/*${extension}`);
    }
    // ...and no pattern refuses an undeclared extension.
    const declared = new Set(SURFACE.styleImportExtensions);
    for (const pattern of BOUNDARY_SPEC.styleImportPatterns) {
      const extension = pattern.replace(/\?\*$/, "").match(/\.[a-z]+$/)?.[0];
      expect(declared.has(extension), `undeclared extension in pattern ${pattern}`).toBe(true);
    }
  });

  it("every declared deep-import segment is refused by the import patterns", () => {
    for (const segment of SURFACE.deepImportPathSegments) {
      expect(BOUNDARY_SPEC.internalImportPatterns).toContain(`@terp/*/${segment}/*`);
    }
    expect(BOUNDARY_SPEC.internalImportPatterns).toHaveLength(
      SURFACE.deepImportPathSegments.length,
    );
  });
});

describe("behavioural parity: each declared primitive is refused with the right catalog id", () => {
  for (const element of SURFACE.restrictedElements) {
    it(`raw <${element}> -> frontend/token-styled-elements`, async () => {
      expect(await lintModuleSource(`export const W = () => <${element} />;\n`)).toContain(
        "frontend/token-styled-elements",
      );
    });
  }

  for (const attribute of SURFACE.restrictedAttributes) {
    it(`${attribute} attribute -> frontend/no-inline-styling`, async () => {
      const value = attribute === "style" ? "{{}}" : '"x"';
      expect(await lintModuleSource(`export const W = () => <div ${attribute}=${value} />;\n`)).toContain(
        "frontend/no-inline-styling",
      );
    });
  }

  for (const globalName of SURFACE.restrictedGlobals) {
    it(`${globalName} -> frontend/generated-client-only`, async () => {
      expect(await lintModuleSource(`export const value = ${globalName};\n`)).toContain(
        "frontend/generated-client-only",
      );
    });
  }

  for (const memberCall of SURFACE.restrictedMemberCalls) {
    it(`${memberCall}() -> frontend/generated-client-only`, async () => {
      expect(await lintModuleSource(`export const send = () => ${memberCall}("/x", "");\n`)).toContain(
        "frontend/generated-client-only",
      );
    });
  }

  for (const extension of SURFACE.styleImportExtensions) {
    it(`import of *${extension} -> frontend/no-style-imports`, async () => {
      expect(await lintModuleSource(`import "./widget${extension}";\n`)).toContain(
        "frontend/no-style-imports",
      );
    });
  }

  for (const segment of SURFACE.deepImportPathSegments) {
    it(`deep import via /${segment}/ -> frontend/no-deep-imports`, async () => {
      expect(
        await lintModuleSource(`import { x } from "@terp/react-core/${segment}/internal";\n`),
      ).toContain("frontend/no-deep-imports");
    });
  }
});
