import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { ALL_SPECIMENS } from "../src/specimens";
import { THEMES } from "../src/themes";

// Automated accessibility over every component, in every shipped theme.
//
// The Terp Standard recommends an `a11y` lane — "automated accessibility checks over the
// running app (e.g. axe)" — and nothing realised it. The design notes also promise
// conformance proves "the same a11y landmarks"; that check did not exist either.
//
// Scoped per specimen, for the same reason the screenshots are: a page-wide run reports a
// list of violations with no owner, and the first thing anyone does with an unattributed
// list is stop reading it. One run per specimen means a violation names the component.
//
// Contrast is included deliberately even though `tokens.contrast.test.js` already measures
// the token pairings. That test reads the declared pairs; axe reads what the browser actually
// painted, including a pairing nobody declared. The two disagreeing is information.
//
// This is the lane every shipped theme runs in, and it is the one that matters most for a theme
// added after the declared-pairings list was written: the static gate can only measure pairings
// somebody thought to declare, and a new palette is exactly where an undeclared pairing goes
// wrong. The per-specimen *screenshots* stay on the two default themes — see `src/themes.ts`
// for why colour-only variants do not need their own geometry baselines.

/** WCAG 2.0/2.1 A and AA — the levels the Standard's lane is written against. */
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

/**
 * The one rule with known outstanding failures, and the `<theme>/<specimen>` keys that fail
 * it today.
 *
 * These are the same token pairings `tokens.contrast.test.js` measures — axe reaching the
 * same conclusion from the painted pixels is corroboration, not duplication, and it found
 * more surfaces than the declared-pairs list does. Fixing them means changing token values,
 * which repaints every app, so it belongs to the semantic token layer and not to the suite
 * that found it.
 *
 * A ratchet in both directions: a key that stops failing must be removed, and a specimen that
 * starts failing is refused outright. Every other rule is held at zero with no allowance at
 * all — the list is a statement about *one* known defect class, not a general amnesty.
 *
 * Every key names `light` or `dark`, the two themes that shipped before this lane existed. The
 * themes added since carry none, and `holds no allowance for a theme added after the lane` below
 * refuses one: a palette authored against a working contrast gate has no reason to paint an
 * illegible surface, so an allowance for a new theme would be a design mistake being filed as
 * history.
 */
const KNOWN_CONTRAST_FAILURES = new Set<string>([]);

test("holds no allowance for a theme added after the lane", () => {
  // The two themes that predate this list are allowed to carry known defects; nothing else is.
  // Without this, the cheapest way to make a new theme green would be to add its failures here,
  // which is precisely the move the ratchet exists to prevent.
  const grandfathered = new Set(["light", "dark"]);
  const themeOf = (key: string) => key.slice(0, key.indexOf("/"));
  expect([...KNOWN_CONTRAST_FAILURES].filter((key) => !grandfathered.has(themeOf(key)))).toEqual(
    [],
  );
  // And the lane has to actually be running in more than those two, or the assertion above is
  // true for a reason that has nothing to do with the new themes being legible.
  expect(THEMES.length).toBeGreaterThan(grandfathered.size);
});

// Each run renders its specimen alone, exactly as the screenshot lane does. The context axe
// measures is unchanged — the solo page reuses the same page background and specimen card — but
// a navigation now builds one specimen instead of all fifty. With five themes that was 250
// full-catalog renders per run, which had grown slow enough to start timing out under parallel
// load; the failure looked like an accessibility violation and was a cold page.
//
// An `overlay` specimen widens the scope from the specimen element to `body`, because
// `Popover` portals its panel to `document.body` — so the panel is not a DESCENDANT of the
// specimen and `.include()` cannot reach it. Scoped to the element, an open-panel specimen
// returns a clean run that examined the trigger and nothing else: silent false coverage on
// precisely the subtrees that have none today. `body` rather than the whole page on purpose,
// so the document-level rules (`html-has-lang`, `document-title`) stay out — those belong to
// the workbench shell, and this lane is a gate on react-core.
test.describe("component accessibility", () => {
  for (const theme of THEMES) {
    test.describe(theme, () => {
      for (const specimen of ALL_SPECIMENS) {
        test(`${specimen.groupId}/${specimen.id}`, async ({ page }) => {
          await page.goto(`/?theme=${theme}&only=${specimen.id}`);
          const selector = `[data-specimen="${specimen.id}"]`;
          await page.locator(selector).waitFor({ state: "visible" });
          // Settle the fonts before axe reads anything, exactly as the screenshot lane does.
          // axe's colour-contrast rule resolves computed foreground and background from the
          // painted page, so it is measuring a moving target until layout and text rendering
          // have finished — and the way that surfaces is a contrast violation on a specimen
          // whose colours are fine, which is indistinguishable from a real defect. This lane
          // has been bitten by the cold-page shape before (it once loaded the whole catalog
          // for all 285 runs and timed out under parallel load); the two lanes waiting for
          // different things was the remaining asymmetry.
          await page.evaluate(() => document.fonts.ready);
          const results = await new AxeBuilder({ page })
            .include(specimen.overlay === true ? "body" : selector)
            .withTags(TAGS)
            .analyze();
          const key = `${theme}/${specimen.id}`;
          // The message carries rule id, impact and the offending markup, because a bare
          // count tells a reader nothing about what to fix.
          const describe = (rules: typeof results.violations) =>
            rules.map((violation) => ({
              rule: violation.id,
              impact: violation.impact,
              nodes: violation.nodes.map((node) => node.html),
            }));

          const contrast = results.violations.filter((v) => v.id === "color-contrast");
          const everythingElse = results.violations.filter((v) => v.id !== "color-contrast");

          // No allowance for anything but contrast.
          expect(describe(everythingElse), key).toEqual([]);

          if (KNOWN_CONTRAST_FAILURES.has(key)) {
            expect(
              describe(contrast),
              `${key} no longer fails contrast — remove it from KNOWN_CONTRAST_FAILURES`,
            ).not.toEqual([]);
          } else {
            expect(describe(contrast), key).toEqual([]);
          }
        });
      }
    });
  }
});
