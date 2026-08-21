import { expect, test } from "@playwright/test";

// Declarations whose COMPUTED value is the contract — the fourth thing none of the other
// three lanes can see.
//
// The screenshot lane runs with `animations: "disabled"`, so every duration and easing in the
// sheet is invisible to it by construction: a transition that is 150ms, 400ms or gone
// entirely produces identical baselines. axe reads a static tree and says nothing about
// computed style. And the keyboard lane is deliberately scoped to where a keystroke sends
// focus, which this is not.
//
// The gap that argument describes is not hypothetical, and it is why this file exists rather
// than one more structural assertion in `styles.test.ts`. Wiring the published motion scale
// into the sheet replaced 29 literal `150ms ease` / `100ms ease` pairs with `var()` reads, and
// a `var()` in a shorthand fails in a particular way: if the substitution is invalid, the
// whole declaration becomes invalid at computed-value time and falls back to the INITIAL
// value — `transition: all 0s ease 0s`. Every element still paints identically at rest, every
// baseline still passes, axe still finds nothing, and every transition in the package is
// silently dead. A structural test proving the sheet *names* a token cannot tell the
// difference; only reading the value the browser resolved can.
//
// Same shape as the rule the sheet already relies on and states about itself: a rule can be
// right, wrong or absent and the baselines only see it if some rendered context depends on it.
// A duration has no such context at all while animations are disabled.
//
// Deliberately small, on the keyboard lane's terms: this holds cases where the resolved value
// is the contract and nothing else. Appearance belongs in a baseline; the static tree belongs
// to axe; focus belongs next door.

/** The resolved transition longhands for the first element matching `selector`. */
async function transitionOf(page: import("@playwright/test").Page, selector: string) {
  return page.evaluate((css) => {
    const element = document.querySelector(css);
    if (element === null) {
      return null;
    }
    const style = getComputedStyle(element);
    return {
      property: style.transitionProperty,
      duration: style.transitionDuration,
      easing: style.transitionTimingFunction,
    };
  }, selector);
}

test("the sheet's transitions resolve through the published motion scale", async ({ page }) => {
  // Stated as no-preference explicitly rather than inherited, so this test and its
  // reduced-motion counterpart below differ in exactly one input.
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/?theme=light&only=app-shell");
  await page.locator('[data-terp="appshell-sidebar"]').waitFor({ state: "visible" });

  // The sidebar's rail collapse: `transition: width var(--motion-duration-fast)
  // var(--motion-easing-standard)`. 0.15s is the token's published value, and it is also
  // what the literal said before the wiring — which is the point. The assertion that
  // carries the information is not the number but that it is not `0s`: an invalid
  // substitution resolves the shorthand to its initial value, and `transition-property`
  // would come back as `all` rather than `width`.
  const sidebar = await transitionOf(page, '[data-terp="appshell-sidebar"]');
  expect(sidebar).not.toBeNull();
  expect(sidebar!.property).toBe("width");
  expect(sidebar!.duration).toBe("0.15s");
  expect(sidebar!.easing).toBe("ease");

  // A nav link resolves the same pair across a two-property list, which is the form 15 of
  // the sheet's 16 transition declarations take.
  const link = await transitionOf(page, '[data-terp="appshell-nav"] a');
  expect(link).not.toBeNull();
  expect(link!.duration).toBe("0.15s, 0.15s");
  expect(link!.property).toBe("background-color, color");
});

test("reduced motion reaches the three shapes the sheet names", async ({ page }) => {
  // The sheet claims this was "measured, not assumed", and nothing gated the measurement.
  // Three distinct shapes, and the middle one is the reason the block needs a selector list
  // rather than `[data-terp]` alone: the block wins on layer order, but only over elements
  // one of its selectors matches, and a nav link and a breadcrumb link are bare <a>s
  // carrying no marker of their own.
  await page.emulateMedia({ reducedMotion: "reduce" });

  await page.goto("/?theme=light&only=app-shell");
  await page.locator('[data-terp="appshell-sidebar"]').waitFor({ state: "visible" });
  // A marked element, reached by `[data-terp]`.
  expect((await transitionOf(page, '[data-terp="appshell-sidebar"]'))!.duration).toBe("0s");
  // An unmarked descendant, reached only by its own selector.
  expect((await transitionOf(page, '[data-terp="appshell-nav"] a'))!.duration).toBe("0s");

  await page.goto("/?theme=light&only=breadcrumbs");
  await page.locator('[data-terp="breadcrumbs"]').waitFor({ state: "visible" });
  expect((await transitionOf(page, '[data-terp="breadcrumbs"] a'))!.duration).toBe("0s");
});
