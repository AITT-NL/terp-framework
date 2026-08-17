import fs from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { parseRules } from "./css-rules.js";

// The token sheet's theme structure. `tokens.guard.test.ts` in react-core proves every
// `var(--x)` names a property the sheet declares *somewhere*; that is a spelling check and
// it is blind to which block declares what. This file proves the blocks agree.
//
// Three shapes have to hold, and each one fails silently in the browser rather than
// loudly at build time — which is why they are gates and not review items:
//
//   1. A colour a theme forgets falls through to the light value, so one element renders
//      light-on-light under the dark theme. The sheet has *two* dark blocks (an explicit
//      `[data-theme='dark']` and the `prefers-color-scheme` media query), so a new colour
//      has three places to land and forgetting the third is the likeliest mistake.
//   2. The two dark blocks are duplicated verbatim by the generator. Drift between them
//      means the OS preference and the explicit toggle disagree — the same app renders two
//      different darks depending on how the user got there.
//   3. Geometry (space, radius, font, shadow) is deliberately declared once, in `:root`,
//      and inherited by both dark blocks. That is the correct cascade and it must stay
//      that way: a `--space-4` that appears in one dark block only is a theme that
//      silently re-spaces itself.
//
// Regenerate the sheet with `npm run -w @terpjs/contract tokens` after editing
// `tokens.json` / `tokens.dark.json`; CI diffs the result, so these tests and the
// committed artifact move together.

const tokensCss = fs.readFileSync(
  fileURLToPath(new URL("./tokens.css", import.meta.url)),
  "utf8",
);

/** The explicit dark selector, and the media-nested one that follows the OS preference. */
const LIGHT_SELECTOR = ":root";
const DARK_SELECTORS = ["[data-theme='dark']", ":root:not([data-theme='light'])"];

const rules = parseRules(tokensCss);

/** The declarations of the one rule whose selector is exactly `selector`. */
function declarationsFor(selector) {
  const matches = rules.filter((rule) => rule.selector === selector);
  if (matches.length !== 1) {
    throw new Error(
      `expected exactly one \`${selector}\` rule in tokens.css, found ${matches.length}`,
    );
  }
  return matches[0].declarations;
}

const light = declarationsFor(LIGHT_SELECTOR);
const isColour = (token) => token.startsWith("--color-");

describe("token sheet themes", () => {
  it("parses the sheet it is asserting about", () => {
    // A parser that silently found nothing would make every test below vacuously true.
    expect(rules.map((rule) => rule.selector)).toEqual([
      LIGHT_SELECTOR,
      ...DARK_SELECTORS,
    ]);
    expect(light.size).toBeGreaterThan(0);
    expect([...light.keys()].filter(isColour).length).toBeGreaterThan(0);
  });

  it.each(DARK_SELECTORS)("declares every light colour in %s", (selector) => {
    // A colour the theme omits inherits the light value: one light-on-light element.
    const dark = declarationsFor(selector);
    const missing = [...light.keys()].filter(
      (token) => isColour(token) && !dark.has(token),
    );
    expect(missing).toEqual([]);
  });

  it.each(DARK_SELECTORS)("declares no token the light root omits in %s", (selector) => {
    // A theme-only token has no light value to fall back to, so the light render is the
    // one that breaks — and `tokens.guard.test.ts` cannot see it, because the token *is*
    // declared somewhere in the sheet.
    const dark = declarationsFor(selector);
    const orphans = [...dark.keys()].filter((token) => !light.has(token));
    expect(orphans).toEqual([]);
  });

  it.each(DARK_SELECTORS)("leaves geometry to the light root in %s", (selector) => {
    // Space, radius, font and shadow are theme-invariant by design: declared once and
    // inherited. Re-declaring one in a single dark block is how a theme quietly grows its
    // own spacing scale.
    const dark = declarationsFor(selector);
    const geometry = [...dark.keys()].filter((token) => !isColour(token));
    expect(geometry).toEqual([]);
  });

  it("keeps the two dark blocks identical", () => {
    // They are generated from one source and duplicated. Drift means the OS preference and
    // the explicit toggle render different darks in the same app.
    const [explicit, byPreference] = DARK_SELECTORS.map(declarationsFor);
    expect([...byPreference.entries()]).toEqual([...explicit.entries()]);
  });
});
