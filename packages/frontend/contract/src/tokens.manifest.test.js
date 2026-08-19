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
const registry = JSON.parse(fs.readFileSync(here("../themes.json"), "utf8"));

const rules = parseRules(tokensCss);
const declarationsFor = (selector) =>
  rules.find((rule) => rule.selector === selector).declarations;
const base = declarationsFor(":root");

/** Each theme's own block: the base on `:root`, every other on its attribute selector. */
const blocks = new Map(
  registry.themes.map((theme) => [
    theme.name,
    theme.name === registry.base ? base : declarationsFor(`[data-theme='${theme.name}']`),
  ]),
);

const tokenByName = new Map(manifest.tokens.map((token) => [token.name, token]));

describe("token manifest", () => {
  it("names exactly the tokens the base root declares", () => {
    // Either direction is a real failure: a token missing from the manifest is invisible to
    // every tool that reads it, and a token in the manifest that the sheet does not declare
    // is a control that would silently do nothing.
    const manifestNames = manifest.tokens.map((token) => token.name).sort();
    expect(manifestNames).toEqual([...base.keys()].sort());
  });

  it("publishes the theme list the sheet was generated from", () => {
    // This is the list a consumer builds a theme picker from, and the set of keys a `values`
    // map is allowed to use. A manifest naming a theme the sheet has no block for would hand
    // a tool a theme it cannot apply.
    expect(manifest.base).toBe(registry.base);
    expect(manifest.systemDark).toBe(registry.systemDark);
    expect(manifest.themes).toEqual(
      registry.themes.map(({ name, label, appearance, description }) => ({
        name,
        label,
        appearance,
        description,
      })),
    );
    for (const theme of manifest.themes) {
      expect(blocks.has(theme.name), `${theme.name} has no block in the sheet`).toBe(true);
    }
  });

  it("records the value each token resolves to, in every theme", () => {
    // `values` carries only the themes that declare the token; a theme absent from it inherits
    // the base value. That is the cascade stated as data, so both halves are checked: a
    // recorded value must match the theme's own block, and an omission must mean the block
    // really does not declare it.
    for (const token of manifest.tokens) {
      for (const [name, block] of blocks) {
        const recorded = token.values[name];
        if (recorded === undefined) {
          expect(
            block.has(token.name),
            `${token.name} is omitted for ${name} but ${name} declares it`,
          ).toBe(false);
        } else {
          expect(recorded, `${token.name} in ${name}`).toBe(block.get(token.name));
        }
      }
      // The base value is never omitted: it is what every other theme falls back to.
      expect(token.values[registry.base], `${token.name} base value`).toBe(
        base.get(token.name),
      );
      expect(Object.keys(token.values)[0], `${token.name} value order`).toBe(registry.base);
    }
  });

  it("names no theme in a values map that the theme list omits", () => {
    const known = new Set(manifest.themes.map((theme) => theme.name));
    for (const token of manifest.tokens) {
      expect(
        Object.keys(token.values).filter((name) => !known.has(name)),
        token.name,
      ).toEqual([]);
    }
  });

  it("marks a token themeable exactly when some non-base theme overrides it", () => {
    // This is the flag an editor uses to decide whether to offer a per-theme control, so
    // getting it wrong means either a missing control or one that has no effect.
    const overlays = registry.themes.filter((theme) => theme.name !== registry.base);
    for (const token of manifest.tokens) {
      const overridden = overlays.some((theme) => blocks.get(theme.name).has(token.name));
      expect(token.themeable, `${token.name} themeable`).toBe(overridden);
      // Geometry is declared once and inherited, so a non-themeable token carries exactly one
      // value. A themeable one carries every theme's, because each theme is a full colour set.
      expect(Object.keys(token.values), `${token.name} values`).toHaveLength(
        overridden ? registry.themes.length : 1,
      );
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
    expect(manifest.nonTextPairs).toEqual(pairsSource.nonTextPairs);
  });

  it("publishes both sections, so a missing one cannot read as no requirement", () => {
    // `nonTextPairs` reached the manifest by being added to the builder's literal, which is a
    // line that can be deleted without any other test noticing: a consumer would then see only
    // the text pairings and read the absence of a boundary pairing as "nothing is required
    // here" rather than "held in a section you were not given". Both sections are named
    // explicitly rather than derived, because deriving them from the source file is what the
    // assertion above already does — this one is about the shape the package publishes.
    expect(Array.isArray(manifest.textPairs)).toBe(true);
    expect(Array.isArray(manifest.nonTextPairs)).toBe(true);
    expect(manifest.nonTextPairs.length).toBeGreaterThan(0);
  });

  it("references only tokens that exist, in both directions of every pairing", () => {
    // Both sections. A typo in a token name is the failure this catches, and it is the only
    // check that catches it for a pairing naming a token the sheet declares nowhere — the
    // contrast gate would report it as an undefined declaration, which reads as a sheet
    // problem rather than as a pairing problem.
    for (const pair of [...manifest.textPairs, ...manifest.nonTextPairs]) {
      expect(tokenByName.has(pair.fg), `${pair.id} fg ${pair.fg}`).toBe(true);
      expect(tokenByName.has(pair.bg), `${pair.id} bg ${pair.bg}`).toBe(true);
    }
  });

  it("says it is generated", () => {
    // The file is committed, so the next person to open it needs to know editing it is futile.
    expect(manifest.$comment).toContain("Generated");
    expect(manifest.$comment).toContain("build-tokens.mjs");
  });
});
