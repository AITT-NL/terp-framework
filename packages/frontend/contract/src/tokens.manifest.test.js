import fs from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { parseRules } from "./css-rules.js";

// The published token manifest: the same tokens as machine-readable data.
//
// It exists because three consumers could not get the list any other way. A theme editor had
// to hard-code its own copy — `tokens.json` is Style-Dictionary-shaped and was never exported
// from the package, only the compiled CSS was. An agent editing a theme had to infer names
// from whatever it found in `node_modules`, with no way to tell which tokens are safe to theme
// or which must stay legible against which. A human had no list at all.
//
// A manifest that disagrees with the stylesheet beside it is worse than none, because it is
// the copy a tool trusts. So it is generated in the same run from the same sources, and these
// tests hold the two together.

const here = (name) => fileURLToPath(new URL(name, import.meta.url));

const manifest = JSON.parse(fs.readFileSync(here("./tokens.manifest.json"), "utf8"));
const tokensCss = fs.readFileSync(here("./tokens.css"), "utf8");
const pairsSource = JSON.parse(fs.readFileSync(here("../token-pairs.json"), "utf8"));

const rules = parseRules(tokensCss);
const declarationsFor = (selector) =>
  rules.find((rule) => rule.selector === selector).declarations;
const light = declarationsFor(":root");
const dark = declarationsFor("[data-theme='dark']");

describe("token manifest", () => {
  it("names exactly the tokens the light root declares", () => {
    // Either direction is a real failure: a token missing from the manifest is invisible to
    // every tool that reads it, and a token in the manifest that the sheet does not declare
    // is a control that would silently do nothing.
    const manifestNames = manifest.tokens.map((token) => token.name).sort();
    expect(manifestNames).toEqual([...light.keys()].sort());
  });

  it("records the light value each token actually resolves to", () => {
    for (const token of manifest.tokens) {
      expect(token.light, token.name).toBe(light.get(token.name));
    }
  });

  it("marks a token themeable exactly when the dark block overrides it", () => {
    // This is the flag an editor uses to decide whether to offer a per-theme control, so
    // getting it wrong means either a missing control or one that has no effect.
    for (const token of manifest.tokens) {
      expect(token.themeable, `${token.name} themeable`).toBe(dark.has(token.name));
      expect(token.dark, `${token.name} dark value`).toBe(dark.get(token.name) ?? null);
    }
  });

  it("gives every token a category from its source family", () => {
    // `zIndex.base` flattens to `--z-index-base`; splitting the CSS name would call its
    // family `z`, which is why the category comes from the source tree instead.
    const categories = new Set(manifest.tokens.map((token) => token.category));
    expect(categories.has("z")).toBe(false);
    expect(categories.has("zIndex")).toBe(true);
    for (const token of manifest.tokens) {
      expect(token.category, token.name).toBeTruthy();
    }
  });

  it("publishes the pairings the contrast gate enforces, unchanged", () => {
    // The manifest is a claim about what is guaranteed; the gate is what guarantees it. If
    // the two lists could differ, the published claim would be unverified.
    expect(manifest.textPairs).toEqual(pairsSource.textPairs);
  });

  it("references only tokens that exist, in both directions of every pairing", () => {
    for (const pair of manifest.textPairs) {
      expect(light.has(pair.fg), `${pair.id} fg ${pair.fg}`).toBe(true);
      expect(light.has(pair.bg), `${pair.id} bg ${pair.bg}`).toBe(true);
    }
  });

  it("says it is generated", () => {
    // The file is committed, so the next person to open it needs to know editing it is futile.
    expect(manifest.$comment).toContain("Generated");
    expect(manifest.$comment).toContain("build-tokens.mjs");
  });
});
