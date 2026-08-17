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

const here = (name) => fileURLToPath(new URL(name, import.meta.url));

const tokensCss = fs.readFileSync(here("./tokens.css"), "utf8");
const registry = JSON.parse(fs.readFileSync(here("../themes.json"), "utf8"));

/** WCAG 2.1 AA, normal-size text. Large text and UI boundaries would be 3.0. */
const AA_NORMAL_TEXT = 4.5;

/** WCAG 2.1 AAA, normal-size text — the bar a theme named for contrast has to clear. */
const AAA_NORMAL_TEXT = 7;

/**
 * Pairings the framework renders as text, read from the shared data file.
 *
 * `token-pairs.json` is the single source: this gate holds each pairing to AA, and the
 * generated manifest publishes the same list so a theme editor or an agent can tell which
 * tokens must stay legible against which. Restating them here would let the gate and the
 * published contract disagree about what is guaranteed.
 *
 * `label` names the component surface so a failure says what a user would be looking at, and
 * `id` is the stable key — labels intentionally repeat across the primitive and semantic
 * layers ("body text on the canvas" describes both), so only the id can identify a pairing.
 */
const TEXT_PAIRS = JSON.parse(fs.readFileSync(here("../token-pairs.json"), "utf8")).textPairs;


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
 *
 * Every entry is in `light` or `dark`, the two themes that shipped before the table existed.
 * The themes added since carry none: a theme authored against this gate has no reason to land
 * below AA, so an allowance for a new theme is a design mistake and not a legacy to record.
 */
const BELOW_AA = new Map([
  ["dark/primary-button-label", 3.6779],
  ["light/danger-badge", 4.4148],
  ["light/info-badge", 3.8416],
  ["light/success-badge", 3.1484],
  ["light/warning-badge", 3.0721],
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

// A theme is the base root with its own colours laid over it — the same resolution the
// cascade performs, so a pairing is measured at the value a browser would paint. The theme
// list comes from the registry rather than from a literal here, so a theme cannot be added to
// the sheet without this gate measuring it.
const base = declarationsFor(":root");
const THEMES = Object.fromEntries(
  registry.themes.map((theme) => [
    theme.name,
    theme.name === registry.base
      ? base
      : new Map([...base, ...declarationsFor(`[data-theme='${theme.name}']`)]),
  ]),
);

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

/**
 * The ratio a theme's pairings must reach. AA for normal text by default; a theme may declare
 * a higher floor in `themes.json`, which is how the high-contrast theme's promise is a gate
 * rather than a sentence in its description.
 */
const floorFor = (name) =>
  registry.themes.find((theme) => theme.name === name)?.minimumContrast ?? AA_NORMAL_TEXT;

/** Every pairing, in every registered theme, tagged with its `BELOW_AA` key. */
const cases = Object.entries(THEMES).flatMap(([theme, declarations]) =>
  TEXT_PAIRS.map((pair) => ({
    ...pair,
    theme,
    declarations,
    key: `${theme}/${pair.id}`,
    floor: floorFor(theme),
  })),
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

  it("gives every pairing a unique id", () => {
    // The id is the ratchet key and the manifest's handle. A duplicate would silently make
    // one pairing's allowance apply to another, and labels cannot substitute — they repeat
    // across the primitive and semantic layers on purpose.
    const ids = TEXT_PAIRS.map((pair) => pair.id);
    expect(ids.filter((id) => !id)).toEqual([]);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("measures every registered theme", () => {
    // The theme list is read from `themes.json`, so a theme added to the sheet is measured
    // automatically — but only if the resolution above actually found its block. A theme that
    // resolved to an empty map would produce cases that all read the base values and pass,
    // which is the failure mode worth pinning: silent, and it looks like coverage.
    expect(Object.keys(THEMES)).toEqual(registry.themes.map((theme) => theme.name));
    for (const [name, declarations] of Object.entries(THEMES)) {
      expect(declarations.size, `${name} resolved to nothing`).toBe(base.size);
    }
    expect(cases).toHaveLength(registry.themes.length * TEXT_PAIRS.length);
  });

  it("keeps the known gaps to the themes that predate the gate", () => {
    // A theme authored against this gate has no reason to land below AA, so an allowance for a
    // newer theme would be a design mistake being recorded as history. Naming the two
    // grandfathered themes explicitly is what stops the table from becoming a general amnesty.
    const grandfathered = new Set(["light", "dark"]);
    const themeOf = (key) => key.slice(0, key.indexOf("/"));
    expect([...BELOW_AA.keys()].filter((key) => !grandfathered.has(themeOf(key)))).toEqual([]);
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

  it.each(meetsAa)("$theme: $id ($label) reaches $floor:1 for normal text", (testCase) => {
    const { ratio, painted } = measure(testCase);
    expect(ratio, painted).toBeGreaterThanOrEqual(testCase.floor);
  });

  it("holds the high-contrast theme to AAA rather than AA", () => {
    // A theme called "high contrast" that only cleared the same bar as every other theme would
    // be a name doing the work a measurement should. The floor is declared per theme in
    // `themes.json`; this asserts at least one theme actually raises it, so the mechanism
    // cannot rot into an unused field that reads as enforcement.
    const raised = registry.themes.filter((theme) => theme.minimumContrast !== undefined);
    expect(raised.length).toBeGreaterThan(0);
    for (const theme of raised) {
      expect(theme.minimumContrast, `${theme.name} floor`).toBeGreaterThanOrEqual(
        AAA_NORMAL_TEXT,
      );
      expect(
        [...BELOW_AA.keys()].filter((key) => key.startsWith(`${theme.name}/`)),
        `${theme.name} raises its floor, so it cannot also carry an allowance`,
      ).toEqual([]);
    }
  });

  // Deliberately titled as a gap, not as a pass: a green line reading "warning badge
  // reaches AA" for a pairing measuring 3.07 is worse than no test, because it is the line
  // a reviewer trusts.
  it.each(knownGaps)(
    "$theme: $id ($label) is a known contrast gap, held at its floor",
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
