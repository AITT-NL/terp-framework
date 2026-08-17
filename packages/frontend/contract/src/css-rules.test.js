import { describe, expect, it } from "vitest";

import {
  parseDeclarations,
  parseProperties,
  parseRules,
  stripComments,
} from "./css-rules.js";

// The reader the two token gates are built on. Every case here is a shape that made an
// earlier, naive version of this code assert about a fragment of a rule while still
// reporting green — which is the only failure mode that matters for a gate.

describe("parseRules", () => {
  it("reads a flat rule's custom properties", () => {
    const rules = parseRules(":root { --a: 1; --b: 2; }");
    expect(rules).toHaveLength(1);
    expect(rules[0].selector).toBe(":root");
    expect([...rules[0].declarations]).toEqual([
      ["--a", "1"],
      ["--b", "2"],
    ]);
  });

  it("flattens a conditional group to its inner rules", () => {
    // The sheet's OS-preference dark theme is a `:root:not(…)` nested in `@media`. A reader
    // that returned the `@media` itself would find no declarations and the completeness
    // gate would pass by asserting about nothing.
    const rules = parseRules(
      "@media (prefers-color-scheme: dark) { :root:not([data-theme='light']) { --a: 9; } }",
    );
    expect(rules.map((rule) => rule.selector)).toEqual([":root:not([data-theme='light'])"]);
    expect(rules[0].declarations.get("--a")).toBe("9");
  });

  it("skips a statement at-rule instead of swallowing the next rule", () => {
    // `@layer tokens;` declares no block. Scanning to the next `{` would make the selector
    // `@layer tokens; :root`, which starts with `@`, so the reader would recurse into
    // `:root`'s body and drop the rule — `:root` then does not exist and every downstream
    // assertion is about a sheet with no light theme.
    const rules = parseRules("@layer tokens;\n:root { --a: 1; }");
    expect(rules.map((rule) => rule.selector)).toEqual([":root"]);
    expect(rules[0].declarations.get("--a")).toBe("1");
  });

  it("skips a charset or import line the same way", () => {
    const rules = parseRules('@charset "utf-8";\n@import "x.css";\n:root { --a: 1; }');
    expect(rules.map((rule) => rule.selector)).toEqual([":root"]);
  });

  it("does not end a block on a brace inside a value", () => {
    // Not hypothetical for a generated sheet: a font stack or a `url()` can carry one.
    const rules = parseRules(':root { --a: "}"; --b: 2; }');
    expect(rules).toHaveLength(1);
    expect(rules[0].declarations.get("--b")).toBe("2");
  });

  it("ignores commented-out declarations", () => {
    const rules = parseRules(":root { /* --a: 1; */ --b: 2; }");
    expect([...rules[0].declarations.keys()]).toEqual(["--b"]);
  });

  it("returns nothing for a sheet with no rules", () => {
    expect(parseRules("")).toEqual([]);
    expect(parseRules("/* just a comment */")).toEqual([]);
  });
});

describe("parseProperties", () => {
  it("reads standard properties alongside custom ones", () => {
    // `color-scheme` is the reason this exists: every theme block must declare it, and a
    // custom-property reader cannot see it, so the gate that checks it would pass vacuously.
    const properties = parseProperties("color-scheme: dark; --a: 1;");
    expect([...properties]).toEqual([
      ["color-scheme", "dark"],
      ["--a", "1"],
    ]);
  });

  it("does not read a property name out of a value", () => {
    // A value containing a colon — a `url(https://…)`, a media condition — would otherwise
    // register as a second property and the caller would be reading noise.
    expect([...parseProperties("background: url(https://x/y.png);").keys()]).toEqual([
      "background",
    ]);
  });

  it("is exposed on every rule the reader returns", () => {
    const [rule] = parseRules(":root { color-scheme: light; --a: 1; }");
    expect([...rule.declarations.keys()]).toEqual(["--a"]);
    expect(rule.properties.get("color-scheme")).toBe("light");
  });
});

describe("parseDeclarations", () => {
  it("keeps the last value when a property repeats", () => {
    // The cascade's own behaviour: a duplicated property in one block resolves to the last.
    expect(parseDeclarations("--a: 1; --a: 2;").get("--a")).toBe("2");
  });

  it("ignores ordinary properties", () => {
    expect([...parseDeclarations("color: red; --a: 1;").keys()]).toEqual(["--a"]);
  });
});

describe("stripComments", () => {
  it("removes multi-line comments", () => {
    expect(stripComments("a/* x\ny */b")).toBe("ab");
  });
});
