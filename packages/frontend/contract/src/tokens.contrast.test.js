import fs from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { parseRules } from "./css-rules.js";

// Text legibility of the token sheet, measured rather than reviewed.
//
// The sheet is the single source of every colour a Terp app renders, and a foreground and
// a background are chosen independently — one token moves for a good reason and a pairing
// three components away stops being readable. Nothing catches that today: the token guard
// checks spelling, the theme test checks completeness, and neither knows that
// `--color-status-warning` is only ever painted on `--color-status-warning-soft`.
//
// So the pairings are declared here, as data, and held to WCAG 2.1 contrast. Each entry is
// a pairing some framework component actually renders as text; decorative boundaries are
// deliberately absent, because WCAG sets no ratio for a divider and asserting one would
// only teach the next reader to ignore this file.

const tokensCss = fs.readFileSync(
  fileURLToPath(new URL("./tokens.css", import.meta.url)),
  "utf8",
);

/** WCAG 2.1 AA, normal-size text. Large text and UI boundaries would be 3.0. */
const AA_NORMAL_TEXT = 4.5;

/**
 * Pairings the framework renders as text, as foreground/background token names.
 *
 * `label` names the component surface so a failure says what a user would be looking at,
 * not just which two tokens disagree.
 */
const TEXT_PAIRS = [
  { label: "body text on a card", fg: "--color-neutral-900", bg: "--color-neutral-0" },
  { label: "body text on the canvas", fg: "--color-neutral-900", bg: "--color-neutral-50" },
  { label: "muted text on a card", fg: "--color-neutral-600", bg: "--color-neutral-0" },
  { label: "muted text on the canvas", fg: "--color-neutral-600", bg: "--color-neutral-50" },
  {
    label: "primary button label",
    fg: "--color-brand-primary-contrast",
    bg: "--color-brand-primary",
  },
  {
    label: "success badge",
    fg: "--color-status-success",
    bg: "--color-status-success-soft",
  },
  {
    label: "warning badge",
    fg: "--color-status-warning",
    bg: "--color-status-warning-soft",
  },
  { label: "danger badge", fg: "--color-status-danger", bg: "--color-status-danger-soft" },
  { label: "info badge", fg: "--color-status-info", bg: "--color-status-info-soft" },

  // The semantic layer. These name the same surfaces the primitive pairs above describe by
  // position, and they are gated separately because the two layers can drift: a theme may
  // remap `--color-bg-surface` without touching `--color-neutral-0`, and once components read
  // the semantic names the primitive pairs stop describing what anyone actually sees.
  { label: "body text on a surface", fg: "--color-fg-default", bg: "--color-bg-surface" },
  { label: "body text on the canvas", fg: "--color-fg-default", bg: "--color-bg-canvas" },
  { label: "body text on a raised surface", fg: "--color-fg-default", bg: "--color-bg-raised" },
  { label: "muted text on a surface", fg: "--color-fg-muted", bg: "--color-bg-surface" },
  { label: "muted text on the canvas", fg: "--color-fg-muted", bg: "--color-bg-canvas" },
  { label: "subtle text on a surface", fg: "--color-fg-subtle", bg: "--color-bg-surface" },
  { label: "sidebar text", fg: "--color-sidebar-fg", bg: "--color-sidebar-bg" },
  { label: "sidebar muted text", fg: "--color-sidebar-muted", bg: "--color-sidebar-bg" },
];

/**
 * Pairings that do not reach AA today, with the ratio measured when they were recorded.
 *
 * A ratchet, not a mute button, and it moves in one direction only: a pairing may not drop
 * below its recorded floor, and once it reaches AA it must leave this table — so an
 * improvement cannot quietly leave a stale allowance behind, and a regression cannot hide
 * behind an existing one. Keyed `<theme>/<label>`.
 *
 * Floors are the measured ratio truncated to four places, and the comparison below is
 * against the *raw* ratio. Rounding to two places would straddle the AA boundary in both
 * directions — 4.4951 would round into a pass, and two of these floors would only hold
 * because rounding lifted them — so neither the gate nor the ratchet may depend on it.
 *
 * All five clear 3.0 (AA for large text and UI components) and fail 4.5 (normal text).
 * Badge copy and button labels are normal text, so these are real defects, deliberately
 * left visible: changing a token value repaints every app, which belongs to the semantic
 * token layer rather than to the test that found it. Emptying this table is that work's
 * acceptance criterion.
 */
const BELOW_AA = new Map([
  ["dark/primary button label", 3.6779],
  ["light/danger badge", 4.4148],
  ["light/info badge", 3.8416],
  ["light/success badge", 3.1484],
  ["light/warning badge", 3.0721],
]);

/** The declarations of the one rule whose selector is exactly `selector`. */
function declarationsFor(selector) {
  const matches = parseRules(tokensCss).filter((rule) => rule.selector === selector);
  if (matches.length !== 1) {
    throw new Error(
      `expected exactly one \`${selector}\` rule in tokens.css, found ${matches.length}`,
    );
  }
  return matches[0].declarations;
}

// A theme is the light root with its own colours laid over it — the same resolution the
// cascade performs, so a pairing is measured at the value a browser would paint.
const light = declarationsFor(":root");
const dark = new Map([...light, ...declarationsFor("[data-theme='dark']")]);
const THEMES = { light, dark };

/** sRGB channel → linear light, per WCAG 2.1 relative luminance. */
function linearise(channel) {
  const scaled = channel / 255;
  return scaled <= 0.04045 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
}

/** Relative luminance of a `#rrggbb` value. */
function relativeLuminance(hex) {
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!match) throw new Error(`not a six-digit hex colour: ${hex}`);
  const [red, green, blue] = [0, 2, 4].map((offset) =>
    linearise(Number.parseInt(match[1].slice(offset, offset + 2), 16)),
  );
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

/** WCAG 2.1 contrast ratio between two `#rrggbb` values, 1.0 – 21.0. */
function contrastRatio(a, b) {
  const [darker, lighter] = [relativeLuminance(a), relativeLuminance(b)].sort(
    (x, y) => x - y,
  );
  return (lighter + 0.05) / (darker + 0.05);
}

/** Every pairing, in both themes, tagged with its `BELOW_AA` key. */
const cases = Object.entries(THEMES).flatMap(([theme, declarations]) =>
  TEXT_PAIRS.map((pair) => ({ ...pair, theme, declarations, key: `${theme}/${pair.label}` })),
);

/** The measured ratio for one case, with the painted values for the failure message. */
function measure({ fg, bg, declarations }) {
  const foreground = declarations.get(fg);
  const background = declarations.get(bg);
  expect(foreground, `${fg} is not declared`).toBeDefined();
  expect(background, `${bg} is not declared`).toBeDefined();
  return {
    ratio: contrastRatio(foreground, background),
    painted: `${fg} (${foreground}) on ${bg} (${background})`,
  };
}

const meetsAa = cases.filter(({ key }) => !BELOW_AA.has(key));
const knownGaps = cases.filter(({ key }) => BELOW_AA.has(key));

describe("token sheet text contrast", () => {
  it("measures a known ratio correctly", () => {
    // The calculator itself needs a fixture, or a subtly wrong exponent would move every
    // ratio below in the same direction and the suite would still look green.
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrastRatio("#ffffff", "#ffffff")).toBeCloseTo(1, 5);
    // A published mid-tone pair, so the curve is checked and not just its endpoints.
    expect(contrastRatio("#767676", "#ffffff")).toBeCloseTo(4.5422, 4);
  });

  it("holds every pairing in exactly one of the two sets", () => {
    // A typo in a `BELOW_AA` key would silently move a pairing from the strict set into
    // neither set, so the gate would stop asserting anything about it.
    expect(meetsAa.length + knownGaps.length).toBe(cases.length);
    expect(knownGaps).toHaveLength(BELOW_AA.size);
    const known = new Set(cases.map(({ key }) => key));
    expect([...BELOW_AA.keys()].filter((key) => !known.has(key))).toEqual([]);
    expect([...BELOW_AA.keys()]).toEqual([...BELOW_AA.keys()].sort());
  });

  it.each(meetsAa)("$theme: $label reaches AA for normal text", (testCase) => {
    const { ratio, painted } = measure(testCase);
    expect(ratio, painted).toBeGreaterThanOrEqual(AA_NORMAL_TEXT);
  });

  // Deliberately titled as a gap, not as a pass: a green line reading "warning badge
  // reaches AA" for a pairing measuring 3.07 is worse than no test, because it is the line
  // a reviewer trusts.
  it.each(knownGaps)(
    "$theme: $label is a known contrast gap, held at its floor",
    (testCase) => {
      const { ratio, painted } = measure(testCase);
      const floor = BELOW_AA.get(testCase.key);
      expect(ratio, `${painted} regressed below its recorded floor`).toBeGreaterThanOrEqual(
        floor,
      );
      expect(ratio, `${painted} now reaches AA — remove it from BELOW_AA`).toBeLessThan(
        AA_NORMAL_TEXT,
      );
    },
  );
});
