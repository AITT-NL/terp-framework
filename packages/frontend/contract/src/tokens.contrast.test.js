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
 * WCAG 2.1 SC 1.4.11, non-text contrast: the bar for a control's visual boundary and for a
 * state or focus indicator. Flat across every theme, including the one that raises its text
 * floor to AAA, because WCAG defines no AAA tier for non-text contrast — `minimumContrast` in
 * themes.json is a promise about reading, and inventing a stricter non-text bar from it would
 * be this file asserting a standard nobody wrote.
 */
const UI_COMPONENT = 3;

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
const PAIRS = JSON.parse(fs.readFileSync(here("../token-pairs.json"), "utf8"));
const TEXT_PAIRS = PAIRS.textPairs;

/**
 * Pairings the framework renders as a boundary or an indicator rather than as text, from the
 * same file, held to {@link UI_COMPONENT} instead of AA.
 *
 * The section exists because three measured ratios had nowhere to live and so were recorded as
 * prose in `styles.ts` — the shared focus ring, the border that says which layout toggle is
 * active, and the neutral-300 control outline. A number in a comment is not a gate: the focus
 * ring shipped at 1.67:1 for exactly as long as its value was only ever read by a person.
 *
 * What is deliberately NOT here is as load-bearing as what is. The focus ring's translucent
 * box-shadow halo is excluded: the opaque outline is the indicator SC 1.4.11 measures, and the
 * halo is reinforcement around it — declaring the halo would assert a ratio WCAG does not ask
 * for, which is the same reason dividers are absent from `textPairs`. The active toggle's
 * neutral-100 fill is excluded for the same reason, at 1.10, and it is why that rule carries a
 * border at all rather than a wash. And neither the toggle's border against the toolbar band
 * nor the focus ring on a card is an entry, because both name the same two tokens as the TEXT
 * pairing `accent-on-surface` — measuring one pairing twice under two names would make the
 * ratchet lie about how much is covered, and here the other name is held to a stricter bar.
 * `declares no pairing the text section already holds to a stricter bar` enforces that.
 */
const NON_TEXT_PAIRS = PAIRS.nonTextPairs;


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
const BELOW_AA = new Map([]);

/**
 * Non-text pairings that do not reach 3:1 today, with the ratio measured when they were
 * recorded. Same ratchet contract as {@link BELOW_AA}: a floor may only rise, and a pairing
 * that reaches the bar must leave the table.
 *
 * Every entry is the same defect. `--color-neutral-300` is the control outline — the border on
 * an input, a secondary button, a card, a combobox, a menu, the layout toggles — and against
 * the surfaces those controls sit on it measures 1.42 to 2.36, so a bordered control's edge is
 * effectively invisible to anyone who needs the boundary in order to see the control. That is a
 * genuine SC 1.4.11 failure in four of the five themes, deliberately recorded rather than
 * fixed: the fix is the token value, and moving it repaints every bordered control in the
 * package, which is a decision about how the framework looks and not a side effect of adding a
 * gate. The contrast theme already clears it at 10.37, which is what shows the fix is a value
 * and not a structure.
 *
 * Unlike {@link BELOW_AA} the entries are not confined to the themes that predate the gate, and
 * pretending otherwise would be the dishonest option — every palette inherited the same
 * 300-step boundary, so the defect is one token's value seen five times rather than five
 * independent mistakes. The guard below is therefore different in kind: the allowance may name
 * only the control-boundary pairings. A new pairing cannot be added to it at all.
 */
const BELOW_UI = new Map([
  ["dark/control-boundary-on-canvas", 2.3559],
  ["dark/control-boundary-on-surface", 1.9305],
  ["light/control-boundary-on-canvas", 1.419],
  ["light/control-boundary-on-surface", 1.4847],
  ["midnight/control-boundary-on-canvas", 1.6826],
  ["midnight/control-boundary-on-surface", 1.5506],
  ["twilight/control-boundary-on-canvas", 1.982],
  ["twilight/control-boundary-on-surface", 1.7807],
]);

/** The only pairings {@link BELOW_UI} is allowed to name. */
const CONTROL_BOUNDARY_IDS = ["control-boundary-on-canvas", "control-boundary-on-surface"];

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

/**
 * Every pairing in *list*, in every registered theme, tagged with its ratchet key and the
 * ratio it has to reach.
 *
 * Shared by both suites because they differ in exactly one thing — the bar — and writing the
 * fan-out twice is how the two would drift into measuring different theme sets.
 */
const casesFor = (list, floorOf) =>
  Object.entries(THEMES).flatMap(([theme, declarations]) =>
    list.map((pair) => ({
      ...pair,
      theme,
      declarations,
      key: `${theme}/${pair.id}`,
      floor: floorOf(theme),
    })),
  );

/** Every text pairing, in every registered theme, tagged with its `BELOW_AA` key. */
const cases = casesFor(TEXT_PAIRS, floorFor);

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

/** The same three lists for the non-text section. Its bar is flat, so every floor is the same. */
const uiCases = casesFor(NON_TEXT_PAIRS, () => UI_COMPONENT);
const meetsUi = uiCases.filter(({ key }) => !BELOW_UI.has(key));
const uiGaps = uiCases.filter(({ key }) => BELOW_UI.has(key));

describe("token sheet text contrast", () => {
  it("measures a known ratio correctly", () => {
    // The calculator itself needs a fixture, or a subtly wrong exponent would move every
    // ratio below in the same direction and the suite would still look green.
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrastRatio("#ffffff", "#ffffff")).toBeCloseTo(1, 5);
    // A published mid-tone pair, so the curve is checked and not just its endpoints.
    expect(contrastRatio("#767676", "#ffffff")).toBeCloseTo(4.5422, 4);
  });

  it("gives every pairing a unique id, across both sections", () => {
    // The id is the ratchet key and the manifest's handle. A duplicate would silently make
    // one pairing's allowance apply to another, and labels cannot substitute — they repeat
    // across the primitive and semantic layers on purpose.
    //
    // Both sections at once, because the two ratchets key the same way: `light/x` has to name
    // one pairing whichever table it appears in, or an allowance would apply the wrong bar.
    const ids = [...TEXT_PAIRS, ...NON_TEXT_PAIRS].map((pair) => pair.id);
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

describe("token sheet non-text contrast", () => {
  it("declares no pairing the text section already holds to a stricter bar", () => {
    // The guard this section was one review away from needing. `focus-ring-on-surface` shipped
    // here naming --color-fg-accent on --color-bg-surface, which is exactly what the text
    // pairing `accent-on-surface` already holds to 4.5 — so the non-text case could never fail
    // unless the stricter one had failed first, and its only effect was to make the section
    // look like it covered one surface more than it did. The ring on a card is still measured;
    // it is measured by the entry that would go red first.
    //
    // Compared on token NAMES rather than values on purpose: `body-on-card` and
    // `body-on-surface` resolve to identical values in every theme and are both declared,
    // because a theme author retargeting the semantic alias needs the alias measured too. That
    // is the file working as intended; two names for one pair inside one bar is not.
    const textPairKeys = new Set(TEXT_PAIRS.map((pair) => `${pair.fg} on ${pair.bg}`));
    const restated = NON_TEXT_PAIRS.filter((pair) =>
      textPairKeys.has(`${pair.fg} on ${pair.bg}`),
    ).map((pair) => pair.id);
    expect(restated).toEqual([]);
  });

  it("covers every registered theme once per pairing", () => {
    // Narrower than its namesake in the text suite on purpose: that one also proves each theme
    // RESOLVED, which is the failure mode that looks like coverage, and it proves it for the
    // shared THEMES map this suite reads. Re-asserting it here would be a second copy of one
    // fact. What is not covered there is the empty-list case — with no pairings the count check
    // would read 0 === 0 and pass — so that is the assertion this one adds.
    expect(NON_TEXT_PAIRS.length).toBeGreaterThan(0);
    expect(uiCases).toHaveLength(registry.themes.length * NON_TEXT_PAIRS.length);
  });

  it("holds every pairing in exactly one of the two sets", () => {
    expect(meetsUi.length + uiGaps.length).toBe(uiCases.length);
    expect(uiGaps).toHaveLength(BELOW_UI.size);
    const known = new Set(uiCases.map(({ key }) => key));
    expect([...BELOW_UI.keys()].filter((key) => !known.has(key))).toEqual([]);
    expect([...BELOW_UI.keys()]).toEqual([...BELOW_UI.keys()].sort());
  });

  it("lets the allowance name the control boundary and nothing else", () => {
    // The one guard that keeps this from becoming a general amnesty. BELOW_AA restricts its
    // allowance by THEME, which works there because a new theme has no excuse to ship below AA.
    // That reasoning does not transfer: this defect is one token value that every palette
    // inherited, so it shows up in themes that postdate the gate through no fault of their own.
    // Restricting by PAIRING instead says the same thing the theme rule says — no new debt —
    // without pretending the existing debt is older than it is.
    const idOf = (key) => key.slice(key.indexOf("/") + 1);
    expect([...BELOW_UI.keys()].filter((key) => !CONTROL_BOUNDARY_IDS.includes(idOf(key)))).toEqual(
      [],
    );
  });

  it.each(meetsUi)("$theme: $id ($label) reaches $floor:1 as a non-text pairing", (testCase) => {
    const { ratio, painted } = measure(testCase);
    expect(ratio, painted).toBeGreaterThanOrEqual(testCase.floor);
  });

  it.each(uiGaps)("$theme: $id ($label) is a known non-text gap, held at its floor", (testCase) => {
    const { ratio, painted } = measure(testCase);
    const floor = BELOW_UI.get(testCase.key);
    expect(ratio, `${painted} regressed below its recorded floor`).toBeGreaterThanOrEqual(floor);
    expect(ratio, `${painted} now reaches 3:1 — remove it from BELOW_UI`).toBeLessThan(
      UI_COMPONENT,
    );
  });
});
