import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Vitest stubs .css imports to empty modules, so the sheet is read from disk.
const tokensCss = readFileSync(
  new URL("../../contract/src/tokens.css", import.meta.url),
  "utf-8",
);

// Typed locally so the package keeps its deliberate `"types": []` isolation:
// react-core source must never see ambient Node globals. The source scan uses
// Vite's raw glob; only the CSS sheet needs fs (declared minimally in raw.d.ts).
declare global {
  interface ImportMeta {
    glob: (
      pattern: string,
      options: { query: "?raw"; import: "default"; eager: true },
    ) => Record<string, string>;
  }
}

const sources = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
});

/** Every custom property the token sheet declares (any palette block). */
const declared = new Set(
  [...tokensCss.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((match) => match[1]!),
);

describe("design tokens", () => {
  it("only references custom properties the contract token sheet declares", () => {
    // A fallback-less var() against an undeclared token silently computes to the
    // inherited/initial value — the exact class of bug this guard pins down
    // (e.g. a font-weight token typo reintroducing parent-font inheritance).
    expect(declared.size).toBeGreaterThan(0);
    expect(Object.keys(sources).length).toBeGreaterThan(0);
    const offenders: string[] = [];
    for (const [file, text] of Object.entries(sources)) {
      for (const match of text.matchAll(/var\((--[a-z0-9-]+)\)/g)) {
        const token = match[1]!;
        if (!declared.has(token)) {
          offenders.push(`${file}: ${token}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
