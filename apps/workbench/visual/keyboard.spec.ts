import { expect, test } from "@playwright/test";

// Keyboard behaviour the other two lanes cannot see — and, for one of these, that jsdom cannot
// see either.
//
// The screenshot lane captures the resting state and axe reads a static tree, so neither says
// anything about where focus goes when a key is pressed. Stage 4 found two focus defects in
// surfaces it was migrating, and one of them is the reason this file exists: the calendar's
// roving cursor moved `tabIndex` but not DOM focus, and the repaired version was still wrong
// across a month boundary. A unit test cannot gate that repair, because the failure depends on
// the browser moving focus to `<body>` when the focused node is removed — jsdom keeps focus on
// the detached node, so the same test passes against the bug and against the fix. Measured
// both ways before this file was written.
//
// Deliberately small. This is not an e2e suite and must not grow into one: it holds the cases
// where a keystroke's effect on FOCUS is the contract, nothing else. Anything about appearance
// belongs in a baseline, anything about the static tree belongs to axe.

/** Where focus is, and whether the roving cursor is holding it. */
async function focusState(page: import("@playwright/test").Page) {
  return page.evaluate(() => {
    const grid = document.querySelector('[role="grid"]');
    const cursor = grid?.querySelector('[tabindex="0"]') ?? null;
    const active = document.activeElement;
    return {
      month: grid?.getAttribute("aria-label") ?? null,
      cursor: cursor?.textContent ?? null,
      cursorHoldsFocus: cursor !== null && cursor === active,
    };
  });
}

test("the calendar's cursor keeps DOM focus across a month boundary", async ({ page }) => {
  await page.goto("/?theme=light&only=date-picker-open");
  await page.locator('[role="grid"]').waitFor({ state: "visible" });
  // The opening focus is deferred a tick, because the panel is portalled and positioned in a
  // layout effect.
  await expect
    .poll(async () => (await focusState(page)).cursorHoldsFocus)
    .toBe(true);
  expect((await focusState(page)).cursor).toBe("15");

  // Down three weeks: 15 -> 22 -> 29 January, then into February. That last step re-keys the
  // week rows, so the row holding the focused cell is unmounted — which is what used to drop
  // focus to <body> and leave the calendar keyboard-dead, since the grid's handler is the only
  // key listener in the subtree.
  for (const expected of ["22", "29", "5"]) {
    await page.keyboard.press("ArrowDown");
    await expect.poll(async () => (await focusState(page)).cursor).toBe(expected);
    expect(
      (await focusState(page)).cursorHoldsFocus,
      `focus should follow the cursor onto ${expected}`,
    ).toBe(true);
  }
  expect((await focusState(page)).month).toContain("February");

  // And the keyboard still reaches the grid afterwards, which is the half a cursor-position
  // assertion alone would miss: tabIndex moved correctly even while focus was on <body>.
  await page.keyboard.press("ArrowRight");
  await expect.poll(async () => (await focusState(page)).cursor).toBe("6");
  expect((await focusState(page)).cursorHoldsFocus).toBe(true);
});

test("the month buttons keep the focus the pointer gave them", async ({ page }) => {
  await page.goto("/?theme=light&only=date-picker-open");
  await page.locator('[role="grid"]').waitFor({ state: "visible" });
  await expect.poll(async () => (await focusState(page)).cursorHoldsFocus).toBe(true);

  // The other direction, and the reason the cursor follows an intent recorded at the keystroke
  // rather than a guess made afterwards: paging the month from the header must NOT yank focus
  // off the button the pointer just pressed, even though it moves the cursor too.
  const next = page.getByRole("button", { name: "Next month" });
  await next.click();
  await expect(page.locator('[role="grid"]')).toHaveAttribute("aria-label", /February/);
  expect(await page.evaluate(() => document.activeElement?.getAttribute("aria-label"))).toBe(
    "Next month",
  );
});

test("Tab out of an open menu continues the tab order after the trigger", async ({ page }) => {
  // On `page-actions`, because the assertion needs something to land ON: PageActions renders the
  // overflow trigger, then the secondary button, then the primary one. That order is what makes
  // the APG contract measurable — "Tab closes the popup and moves focus to the next element in
  // the tab sequence after the button".
  await page.goto("/?theme=light&only=page-actions");
  const trigger = page.getByRole("button", { name: "More actions" });
  await trigger.click();
  await expect(page.locator('[role="menu"]')).toHaveCount(1);

  await page.keyboard.press("Tab");

  // Closing without restoring focus first left it on a tabIndex=-1 item inside a panel portalled
  // to the END of document.body, which is then unmounted — so the browser's sequential-navigation
  // starting point was a removed node at the wrong end of the document, and Tab landed past all
  // page content instead of on the button after the trigger. Restoring focus to the trigger and
  // then letting the default action run is what produces the contract, in both directions.
  await expect(page.locator('[role="menu"]')).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save draft" })).toBeFocused();
});
