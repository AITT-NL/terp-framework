import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { NARROW_VIEWPORT, WIDE_VIEWPORT_QUERY } from "./breakpoints";
import { TERP_STYLES_CSS } from "./styles";

// Vitest stubs .css imports to empty modules, so the sheet is read from disk.
const tokensCss = readFileSync(
  new URL("../../contract/src/tokens.css", import.meta.url),
  "utf-8",
);

// The package keeps its deliberate `"types": []` isolation: react-core source must never
// see ambient Node globals. The source scan uses Vite's raw glob and the sheet needs fs;
// both are declared minimally in raw.d.ts, shared with the other scanning tests.
const sources = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
});

/** Every custom property the token sheet declares (any palette block). */
const declared = new Set(
  [...tokensCss.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((match) => match[1]!),
);

/** The framework sheet with its comments removed — prose naming a token is not a reader. */
const sheet = TERP_STYLES_CSS.replace(/\/\*[\s\S]*?\*\//g, "");

/**
 * Published motion tokens no rule in the sheet reads, as an exact list.
 *
 * The other three are wired: every `transition` in the sheet names
 * `--motion-duration-fast` / `--motion-duration-instant` with
 * `--motion-easing-standard`, which was inert by construction because those tokens'
 * values ARE the `150ms` / `100ms` / `ease` literals they replaced.
 *
 * These four are not, and leaving them that way is a position rather than an omission.
 * They map onto no literal this sheet contains, so there is nothing to convert. The two
 * ways out are both worse than naming them here: deleting them is a **contract change**,
 * since `tokens.manifest.json` publishes them and a consumer may already read one; and
 * giving them readers means inventing overlay entrance/exit animations, which is a
 * behaviour change wearing a token wiring's clothes — and one the screenshot lane cannot
 * see either way, because it runs with `animations: "disabled"`.
 *
 * Exact equality in both directions, which is what makes it a decision instead of drift:
 * wiring one has to shrink this list, and publishing an eighth motion token has to
 * either name a reader or land here with a reason.
 */
const UNREAD_MOTION_TOKENS = [
  "--motion-duration-base",
  "--motion-duration-slow",
  "--motion-easing-entrance",
  "--motion-easing-exit",
];

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

  it("opts native chrome into the palette via color-scheme (light + dark)", () => {
    // Without `color-scheme`, native chrome the framework cannot restyle — the
    // <select> option popup, and any scrollbar a browser draws natively — stays
    // in OS-light rendering even under the dark theme. The light root declares
    // it and both dark blocks (explicit [data-theme='dark'] and the
    // prefers-color-scheme media query) flip it.
    expect(tokensCss).toContain("color-scheme: light");
    expect(tokensCss.match(/color-scheme: dark/g)?.length ?? 0).toBeGreaterThanOrEqual(2);
  });

  it("spells the one viewport cutover from the published token, in one place", () => {
    // The breakpoint is the other token family nothing can `var()`: CSS forbids a custom
    // property in a media-query condition, and `matchMedia` takes a string, so neither
    // consumer can read `--breakpoint-md` the way a colour is read. The literal is therefore
    // unavoidable — and unguarded it was already written twice, verbatim, in `AppShell` and
    // `DataView`, which is the duplication the diagnosis named.
    //
    // So this holds three things together that CANNOT agree by construction: the token the
    // contract publishes, the string the components hand to `matchMedia`, and the query the
    // stylesheet uses. The third one at least is the complement of the second by construction
    // rather than by a second literal.
    const declaredMd = /--breakpoint-md:\s*([^;]+);/.exec(tokensCss)?.[1]?.trim();
    expect(declaredMd, "the contract should publish --breakpoint-md").toBe("768px");
    expect(NARROW_VIEWPORT).toBe(`(max-width: ${declaredMd})`);
    expect(WIDE_VIEWPORT_QUERY).toBe(`not all and ${NARROW_VIEWPORT}`);
    expect(sheet).toContain(`@media ${WIDE_VIEWPORT_QUERY}`);

    // And nobody re-spells it. The two components import the constant now; a third copy is
    // exactly how the first two came to disagree with nothing noticing.
    const offenders = Object.entries(sources)
      .filter(([file]) => !file.includes(".test.") && file !== "./breakpoints.ts")
      .filter(([, text]) => text.includes("max-width: 768px"))
      .map(([file]) => file);
    expect(offenders, "the breakpoint belongs in ./breakpoints.ts and nowhere else").toEqual([]);
  });

  it("names every published motion token the sheet does not read", () => {
    // The other direction of this file's join. The test above catches a `var()` naming a
    // token the contract never declared; this one catches a token the contract publishes
    // that nothing consumes — the `--color-fg-on-brand` shape, which was deleted for
    // being declared in five themes and read by none. A Studio editor built from the
    // manifest offers a control per published token, so an unread one is a knob that
    // does nothing.
    const motionTokens = [
      ...new Set([...tokensCss.matchAll(/(--motion-[a-z-]+)\s*:/g)].map((match) => match[1]!)),
    ];
    expect(motionTokens.length).toBeGreaterThan(UNREAD_MOTION_TOKENS.length);
    expect(
      motionTokens.filter((token) => !sheet.includes(`var(${token})`)).sort(),
      "a published motion token gained or lost a reader — wire it, or record it here with a reason",
    ).toEqual(UNREAD_MOTION_TOKENS);
  });
});
