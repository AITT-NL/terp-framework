import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { DEFAULT_STRINGS } from "./uiText";

// react-core's theme list against the contract's published one.
//
// `Theme` in `theme.tsx` is a hand-written union of the stylesheet's theme names, and
// `THEME_ICONS` and the label map are records over it. That is a restatement of a published
// contract, so it can drift from it — and both directions fail quietly:
//
//   * A theme the sheet ships that this union omits is a palette no app can ever select. It
//     is compiled, gated for contrast and completeness, published in the manifest, and
//     unreachable.
//   * A theme this union offers that the sheet has no block for is a menu entry that sets
//     `data-theme` to a value nothing matches, so the app silently renders the base theme
//     while the control reports the choice took.
//
// The union is not derived from the manifest at runtime on purpose: react-core publishes
// unbuilt TypeScript and imports nothing but React, so resolving a sibling package's JSON
// module would add a bundler and tsconfig requirement to every consumer. A test reading the
// file from disk is the same discipline the other mirrored tables in this repo use — the copy
// stays a copy, and the copy is checked.

const manifest: {
  base: string;
  systemDark: string;
  themes: { name: string; label: string; appearance: "light" | "dark" }[];
} = JSON.parse(
  readFileSync(new URL("../../contract/src/tokens.manifest.json", import.meta.url), "utf-8"),
);

// Read as source rather than imported, because the union is a type: it does not survive to
// runtime, and `THEMES` alone would not prove the type and the array agree.
const themeSource = readFileSync(new URL("./theme.tsx", import.meta.url), "utf-8");

/** The names in `export type Theme = "a" | "b" | …`. */
function unionMembers(): string[] {
  const match = /export type Theme =([^;]+);/.exec(themeSource);
  if (!match) throw new Error("theme.tsx: could not find `export type Theme`");
  return [...match[1]!.matchAll(/"([a-z-]+)"/g)].map((entry) => entry[1]!);
}

/** The names in the `THEMES` array literal. */
function themesArray(): string[] {
  const match = /const THEMES: readonly Theme\[\] = \[([^\]]+)\]/.exec(themeSource);
  if (!match) throw new Error("theme.tsx: could not find the `THEMES` array");
  return [...match[1]!.matchAll(/"([a-z-]+)"/g)].map((entry) => entry[1]!);
}

/** The keys of a `Record<Theme, …>` literal assigned to `name`. */
function recordKeys(name: string): string[] {
  const match = new RegExp(`const ${name}: Record<Theme, [^>]+> = \\{([^}]+)\\}`).exec(
    themeSource,
  );
  if (!match) throw new Error(`theme.tsx: could not find \`${name}\``);
  return [...match[1]!.matchAll(/^\s*([a-z-]+):/gm)].map((entry) => entry[1]!);
}

/** Every theme the stylesheet ships, in registry order. */
const shipped = manifest.themes.map((theme) => theme.name);

/** What the control offers: every shipped theme, plus the OS-preference entry. */
const OS_PREFERENCE = "system";
const expected = [...shipped, OS_PREFERENCE];

describe("react-core's theme list", () => {
  it("reads the sources it is asserting about", () => {
    // Every assertion below is a comparison against a regex match. A regex that stopped
    // matching — a reformatted union, a renamed constant — would compare two empty lists and
    // report green, which is the one failure mode a parity test cannot afford.
    expect(shipped.length).toBeGreaterThanOrEqual(3);
    expect(unionMembers().length).toBe(expected.length);
    expect(themesArray().length).toBe(expected.length);
  });

  it("offers exactly the themes the contract ships, plus system", () => {
    // The union is the app-facing type: a theme missing here cannot be passed to
    // `ThemeProvider` at all, however completely the stylesheet defines it.
    expect(unionMembers()).toEqual(expected);
  });

  it("lists them in the same order in the THEMES array", () => {
    // `THEMES` is what `ThemeToggle` maps over and what `readStoredTheme` validates against,
    // so a name in the type but not the array is selectable in code and absent from the menu.
    expect(themesArray()).toEqual(expected);
  });

  it("gives every theme an icon, and no two the same", () => {
    // A picker whose entries share a glyph is a picker whose icons carry no information, and
    // the trigger renders the active theme's icon — so a duplicate makes two states identical.
    expect(recordKeys("THEME_ICONS")).toEqual(expected);
    const glyphs = [...themeSource.matchAll(/^\s{2}([a-z-]+): "([a-z-]+)",$/gm)]
      .filter((entry) => expected.includes(entry[1]!))
      .map((entry) => entry[2]!);
    expect(glyphs).toHaveLength(expected.length);
    expect(new Set(glyphs).size).toBe(glyphs.length);
  });

  it("has a translated label for every theme", () => {
    // The label map is `Record<Theme, string>` so the compiler catches a missing entry, but
    // not one pointing at a string key that does not exist in the catalog.
    for (const name of expected) {
      const key = `theme${name[0]!.toUpperCase()}${name.slice(1)}`;
      expect(
        Object.hasOwn(DEFAULT_STRINGS, key),
        `${name} needs a ${key} string (LOCALE_NL's completeness gate then forces the Dutch one)`,
      ).toBe(true);
    }
  });

  it("keeps the OS-preference entry from colliding with a theme name", () => {
    // "system" is a sentinel, not a theme: it means *remove* `data-theme` and let the sheet's
    // `prefers-color-scheme` block decide. A shipped theme actually named `system` would make
    // the sentinel ambiguous — selecting it would clear the attribute rather than pin the
    // theme, and the two would be indistinguishable in storage.
    expect(shipped).not.toContain(OS_PREFERENCE);
    // Both ends of what the sentinel resolves to have to be themes the control also offers,
    // or "System" would render a palette the user cannot pick deliberately.
    expect(shipped).toContain(manifest.systemDark);
    expect(shipped).toContain(manifest.base);
  });
});
