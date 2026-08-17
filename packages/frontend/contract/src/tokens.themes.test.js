import fs from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { parseRules } from "./css-rules.js";

// The token sheet's theme structure. `tokens.guard.test.ts` in react-core proves every
// `var(--x)` names a property the sheet declares *somewhere*; that is a spelling check and
// it is blind to which block declares what. This file proves the blocks agree.
//
// Five shapes have to hold, and each one fails silently in the browser rather than
// loudly at build time — which is why they are gates and not review items:
//
//   1. A colour a theme forgets falls through to the base value, so one element renders
//      light-on-light under a dark theme. Every theme is a full set of colours, and the
//      sheet has one block per theme plus the `prefers-color-scheme` copy of the OS dark
//      theme, so a new colour has as many places to land as there are themes.
//   2. The OS-preference block is duplicated from the `systemDark` theme by the generator.
//      Drift between them means the OS preference and the explicit toggle disagree — the same
//      app renders two different darks depending on how the user got there.
//   3. Geometry (space, radius, font, shadow) is deliberately declared once, in `:root`,
//      and inherited by every theme. That is the correct cascade and it must stay
//      that way: a `--space-4` that appears in one theme only is a theme that
//      silently re-spaces itself.
//   4. Every theme declares `color-scheme` matching its declared appearance, or native chrome
//      the framework cannot restyle — the `<select>` popup, a native scrollbar, a caret —
//      renders from the wrong palette.
//   5. The OS-preference block must not match a root that pinned a theme. This is the one
//      that was a live defect: the selector was `:root:not([data-theme='light'])`, which was
//      equivalent while light and dark were the only themes, and which outranks
//      `[data-theme='contrast']` on specificity — so pinning any theme other than light got
//      the dark colours laid over it whenever the OS preferred dark.
//
// Regenerate the sheet with `npm run -w @terpjs/contract tokens` after editing `themes.json`
// or any theme source; CI diffs the result, so these tests and the committed artifact move
// together.

const here = (name) => fileURLToPath(new URL(name, import.meta.url));

const tokensCss = fs.readFileSync(here("./tokens.css"), "utf8");
const registry = JSON.parse(fs.readFileSync(here("../themes.json"), "utf8"));

const BASE = registry.themes.find((theme) => theme.name === registry.base);
const OVERLAYS = registry.themes.filter((theme) => theme.name !== registry.base);

/** The base theme lives on `:root`; every other theme on its own attribute selector. */
const BASE_SELECTOR = ":root";
const selectorFor = (theme) => `[data-theme='${theme.name}']`;
/** The `@media (prefers-color-scheme: dark)` copy of the `systemDark` theme. */
const SYSTEM_DARK_SELECTOR = ":root:not([data-theme])";

const rules = parseRules(tokensCss);

/** The one rule whose selector is exactly `selector`. */
function ruleFor(selector) {
  const matches = rules.filter((rule) => rule.selector === selector);
  if (matches.length !== 1) {
    throw new Error(
      `expected exactly one \`${selector}\` rule in tokens.css, found ${matches.length}`,
    );
  }
  return matches[0];
}

const declarationsFor = (selector) => ruleFor(selector).declarations;

const base = declarationsFor(BASE_SELECTOR);
const isColour = (token) => token.startsWith("--color-");

/** Every theme block that is a set of colour overrides — i.e. all but the base. */
const overlayCases = OVERLAYS.map((theme) => ({
  ...theme,
  selector: selectorFor(theme),
}));

describe("token sheet themes", () => {
  it("parses the sheet it is asserting about", () => {
    // A parser that silently found nothing would make every test below vacuously true, and a
    // theme in the registry that the generator never emitted would make its own cases vanish
    // rather than fail — so the selector list is asserted whole, in order.
    expect(rules.map((rule) => rule.selector)).toEqual([
      BASE_SELECTOR,
      ...OVERLAYS.map(selectorFor),
      SYSTEM_DARK_SELECTOR,
    ]);
    expect(base.size).toBeGreaterThan(0);
    expect([...base.keys()].filter(isColour).length).toBeGreaterThan(0);
  });

  it("ships more than a light and a dark theme", () => {
    // The point of the semantic token layer is that a third theme is expressible without
    // re-deriving every mapping by hand. One that ships only light and dark has not been
    // proven, so this holds the floor the layer was built to clear.
    expect(registry.themes.length).toBeGreaterThanOrEqual(3);
    const appearances = new Set(registry.themes.map((theme) => theme.appearance));
    // Both polarities represented: a set of dark variants would not exercise the layer any
    // harder than dark alone did.
    expect([...appearances].sort()).toEqual(["dark", "light"]);
  });

  it("registers every theme source that exists on disk", () => {
    // A `tokens.<name>.json` nobody registered compiles to nothing and is invisible: no
    // block, no gate, no manifest entry. Registration is explicit on purpose, so the failure
    // mode is a file that silently does nothing rather than a stray file becoming a theme.
    const registered = new Set(registry.themes.map((theme) => theme.source));
    const onDisk = fs
      .readdirSync(here(".."))
      .filter((name) => /^tokens(\.[a-z0-9-]+)?\.json$/.test(name));
    expect(onDisk.filter((name) => !registered.has(name))).toEqual([]);
  });

  it.each(overlayCases)("declares every base colour in $selector", ({ selector }) => {
    // A colour the theme omits inherits the base value: one light-on-light element.
    const theme = declarationsFor(selector);
    const missing = [...base.keys()].filter(
      (token) => isColour(token) && !theme.has(token),
    );
    expect(missing).toEqual([]);
  });

  it.each(overlayCases)("declares no token the base omits in $selector", ({ selector }) => {
    // A theme-only token has no base value to fall back to, so the base render is the one
    // that breaks — and `tokens.guard.test.ts` cannot see it, because the token *is*
    // declared somewhere in the sheet.
    const theme = declarationsFor(selector);
    const orphans = [...theme.keys()].filter((token) => !base.has(token));
    expect(orphans).toEqual([]);
  });

  it.each(overlayCases)("leaves geometry to the base root in $selector", ({ selector }) => {
    // Space, radius, font and shadow are theme-invariant by design: declared once and
    // inherited. Re-declaring one in a single theme is how a theme quietly grows its
    // own spacing scale.
    const theme = declarationsFor(selector);
    const geometry = [...theme.keys()].filter((token) => !isColour(token));
    expect(geometry).toEqual([]);
  });

  it.each([{ name: BASE.name, appearance: BASE.appearance, selector: BASE_SELECTOR }, ...overlayCases])(
    "opts native chrome into the $appearance palette in $selector",
    ({ appearance, selector }) => {
      // Without `color-scheme`, native chrome the framework cannot restyle stays in OS-light
      // rendering under a dark theme — a white `<select>` popup over a black page.
      expect(ruleFor(selector).properties.get("color-scheme")).toBe(appearance);
    },
  );

  it("copies the systemDark theme into the OS-preference block verbatim", () => {
    // They are generated from one source and duplicated. Drift means the OS preference and
    // the explicit toggle render different darks in the same app.
    const systemDark = registry.themes.find((theme) => theme.name === registry.systemDark);
    expect(systemDark, `systemDark "${registry.systemDark}" must be a registered theme`).toBeDefined();
    const explicit = declarationsFor(selectorFor(systemDark));
    const byPreference = declarationsFor(SYSTEM_DARK_SELECTOR);
    expect([...byPreference.entries()]).toEqual([...explicit.entries()]);
    expect(ruleFor(SYSTEM_DARK_SELECTOR).properties.get("color-scheme")).toBe(
      systemDark.appearance,
    );
  });

  it("lets the OS preference apply only to a root with no theme pinned", () => {
    // The defect a third theme exposed. `:root:not([data-theme='light'])` matches
    // `[data-theme='contrast']` and beats it on specificity, so an app that pinned a theme
    // got the OS dark colours laid over it. Matching the *absence* of the attribute is the
    // only form that stays correct as themes are added, so it is pinned here by shape rather
    // than left to the generator's comment.
    const guarded = rules.filter((rule) => rule.selector === SYSTEM_DARK_SELECTOR);
    expect(guarded).toHaveLength(1);
    for (const theme of registry.themes) {
      expect(
        SYSTEM_DARK_SELECTOR.includes(`'${theme.name}'`),
        `the OS-preference selector must not name the ${theme.name} theme`,
      ).toBe(false);
    }
  });
});
