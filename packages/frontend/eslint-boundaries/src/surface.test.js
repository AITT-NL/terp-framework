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

// ---------------------------------------------------------------------------
// opt-out parity: the catalog's declared marker spelling is the one that works.
// A violating line per rule; the spec's own `opt_out` (a justified marker naming
// the CATALOG rule) must suppress exactly that rule — and the escape-hatch
// governance rule declares no opt_out at all (waiving governance is refused).
// Spec >= 0.6.0 states this contract; the block self-activates when the
// @terp/spec pin moves past the pre-0.6.0 core-id spellings.
// ---------------------------------------------------------------------------
const SPEC_VERSION = fs.readFileSync(path.join(SPEC_ROOT, "VERSION"), "utf8").trim();
const SPEC_STATES_CATALOG_MARKERS = !/^0\.[0-5]\./.test(SPEC_VERSION);
const CATALOG_DIR = path.join(SPEC_ROOT, "catalog", "frontend");
const CATALOG_ENTRIES = fs
  .readdirSync(CATALOG_DIR)
  .filter((name) => name.endsWith(".json"))
  .map((name) => JSON.parse(fs.readFileSync(path.join(CATALOG_DIR, name), "utf8")));

/** A minimal violating line per frontend catalog rule (the marker goes on the line above). */
const VIOLATION_SNIPPETS = {
  "frontend/token-styled-elements": "export const W = () => <button>x</button>;",
  "frontend/no-inline-styling": 'export const W = () => <div className="x" />;',
  "frontend/router-links": 'export const W = () => <a href="/notes">go</a>;',
  "frontend/generated-client-only": 'export const ping = () => fetch("/healthz");',
  "frontend/no-deep-imports": 'import { x } from "@terp/react-core/src/internal";',
  "frontend/no-style-imports": 'import "./widget.css";',
  "frontend/no-cross-module-imports": 'import { x } from "../other/thing";',
  "frontend/no-dom-html-injection": "export const W = (el, html) => { el.innerHTML = html; };",
  "frontend/no-eval": "export const run = (code) => eval(code);",
  "frontend/no-unsafe-href": 'export const W = () => <a href="javascript:alert(1)">x</a>;',
  "frontend/no-unsafe-target-blank":
    'export const W = () => <a href="https://example.com" target="_blank">x</a>;',
};

describe.skipIf(!SPEC_STATES_CATALOG_MARKERS)(
  "opt-out parity: every catalog opt_out spelling suppresses its own rule",
  () => {
    for (const entry of CATALOG_ENTRIES) {
      const optOut = entry.opt_out;
      if (entry.id === "frontend/escape-hatch") {
        it("frontend/escape-hatch declares no opt_out (governance is unwaivable)", () => {
          expect(optOut).toBeUndefined();
        });
        continue;
      }
      it(`${entry.id} declares its catalog-derived marker`, () => {
        const name = entry.id.slice("frontend/".length);
        expect(optOut).toBe(`// terp-allow-${name}: <reason>`);
      });
      const snippet = VIOLATION_SNIPPETS[entry.id];
      if (snippet === undefined) {
        // frontend/layout-contract needs the opt-in contract config; its marker
        // behaviour is covered by layouts.test.js with the same spelling.
        continue;
      }
      it(`${entry.id}'s declared marker suppresses its violation`, async () => {
        const marker = optOut.replace("<reason>", "recorded parity exception");
        // These snippets violate exactly one rule, so the suppressed result is
        // COMPLETELY clean — the marker waived its rule and nothing else remains.
        expect(await lintModuleSource(`${marker}\n${snippet}\n`)).toEqual([]);
        // ...and the same line without the marker does violate (the fixture is live).
        expect(await lintModuleSource(`${snippet}\n`)).toContain(entry.id);
      });
    }
  },
);
