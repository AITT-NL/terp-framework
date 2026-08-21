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

/**
 * Which pane each focusable element belongs to, in tab order.
 *
 * Reads the pane from the element's ancestor `data-role`, so the answer is about structure
 * rather than about position — a check on coordinates would pass a layout that visually
 * reversed the panes as long as it also reversed the DOM.
 */
async function paneTabOrder(page: import("@playwright/test").Page, steps: number) {
  const seen: (string | null)[] = [];
  for (let step = 0; step < steps; step += 1) {
    await page.keyboard.press("Tab");
    seen.push(
      await page.evaluate(() => {
        const active = document.activeElement;
        const pane = active?.closest('[data-terp="splitpane"]') ?? null;
        return pane === null ? null : pane.getAttribute("data-role");
      }),
    );
  }
  return seen;
}

for (const { name, width, height } of [
  { name: "two columns", width: 1280, height: 900 },
  { name: "stacked", width: 700, height: 900 },
]) {
  test(`the split's tab order is list then detail — ${name}`, async ({ page }) => {
    // The keyboard property `SplitPage` owns, asserted as TWO claims, because the obvious one
    // alone cannot fail for the reason it names.
    //
    // A first version asserted only that Tab visits the list before the detail. That is a fact
    // about DOM order, and CSS cannot change it — so `direction: rtl`, `row-reverse` or a
    // `grid-column` putting the detail track first would each leave this green while the screen
    // read backwards. Which is precisely the WCAG 1.3.2 / 2.4.3 failure the test was written
    // for: a reading order that disagrees with the focus order.
    //
    // So the second claim is geometric — the list pane must PAINT before the detail pane, left
    // of it in two columns and above it when stacked — and together they say the two orders
    // agree. Neither a DOM swap nor a CSS reorder survives the pair.
    //
    // At both widths, because the two-column rule lives in a media block: one width alone
    // cannot tell "correct" from "correct here".
    const id = width < 768 ? "split-page-narrow" : "split-page";
    await page.setViewportSize({ width, height });
    await page.goto(`/?theme=light&only=${id}`);
    await page.locator('[data-terp="splitpage-panes"]').waitFor({ state: "visible" });

    // One full document cycle, then filter to the steps that landed in a pane. Both halves of
    // that were arrived at by getting them wrong.
    //
    // A round eight steps wrapped past the end and began a second pass, returning
    // `list -> list -> list -> detail -> list -> list -> list` — an assertion right about the
    // property and wrong about the window it holds over. And bounding the walk to the PANES'
    // own focusable count under-reaches instead: this specimen has a breadcrumb link and a page
    // action ahead of them, so the first steps never enter a pane at all.
    //
    // Counting every focusable on the page and filtering is exact, because one cycle visits
    // each exactly once — so the filtered sequence IS the pane order, with no arithmetic about
    // what precedes the panes.
    const SELECTOR = "a[href], button:not(:disabled), input:not(:disabled), select, textarea";
    const total = await page.locator(SELECTOR).count();
    const inPanes = await page.locator(`[data-terp="splitpane"] :is(${SELECTOR})`).count();
    expect(inPanes, "the panes must contain something focusable to order").toBeGreaterThan(1);
    const order = (await paneTabOrder(page, total)).filter((role) => role !== null);
    expect(order.length, "one cycle should visit every pane focusable once").toBe(inPanes);
    // Every list stop precedes every detail stop: compare against the sorted-by-first-seen
    // sequence rather than a hard-coded list, so adding a focusable element to a pane does not
    // rewrite the assertion.
    const firstDetail = order.indexOf("detail");
    const lastList = order.lastIndexOf("list");
    expect(firstDetail, "the detail pane must be reachable by Tab").toBeGreaterThan(-1);
    expect(lastList, "the list pane must be reachable by Tab").toBeGreaterThan(-1);
    expect(lastList, `tab order was ${order.join(" -> ")}`).toBeLessThan(firstDetail);

    // And the panes paint in that same order, which is the half CSS can break.
    const boxes = await page.evaluate(() => {
      const box = (role: string) => {
        const rect = document
          .querySelector(`[data-terp="splitpane"][data-role="${role}"]`)!
          .getBoundingClientRect();
        return { left: Math.round(rect.left), top: Math.round(rect.top) };
      };
      return { list: box("list"), detail: box("detail") };
    });
    const stacked = boxes.list.left === boxes.detail.left;
    if (stacked) {
      expect(boxes.list.top, "stacked, the list must paint above the detail").toBeLessThan(
        boxes.detail.top,
      );
    } else {
      expect(boxes.list.left, "in two columns, the list must paint left of the detail").toBeLessThan(
        boxes.detail.left,
      );
    }
  });
}

test("the skip link is the first tab stop, and Enter moves focus into main", async ({ page }) => {
  // Two claims, because the first one alone is the version that looks right and does nothing.
  //
  // Reaching the link is easy: it is first in the DOM. What decides whether it WORKS is where
  // focus ends up after activating it — and following a fragment link sets the browser's
  // sequential-navigation starting point without moving document.activeElement unless the
  // target is focusable. A skip link over a plain <main id> therefore scrolls the viewport,
  // leaves focus in the chrome, and sends the next Tab straight back into the navigation it
  // exists to skip. It looks correct in a screenshot and in a manual click.
  //
  // Probed with a REAL Tab rather than .focus(), because the resting rule hides the link and
  // only :focus-visible reveals it — and a programmatic focus does not match :focus-visible.
  await page.goto("/?theme=light&only=app-shell");
  await page.locator('[data-terp="appshell"]').waitFor({ state: "visible" });

  await page.keyboard.press("Tab");
  const first = await page.evaluate(() => {
    const active = document.activeElement as HTMLElement | null;
    return {
      marker: active?.getAttribute("data-terp") ?? null,
      text: active?.textContent ?? null,
      visible: active === null ? false : active.getBoundingClientRect().width > 1,
    };
  });
  expect(first.marker, "the skip link must be the first thing Tab reaches").toBe(
    "appshell-skip-link",
  );
  expect(first.text).toBe("Skip to content");
  // And it has to become visible, or a sighted keyboard user cannot see where they are.
  expect(first.visible, "the focused skip link must leave its 1px hidden box").toBe(true);

  await page.keyboard.press("Enter");
  const landed = await page.evaluate(() => {
    const active = document.activeElement;
    const link = document.querySelector('[data-terp="appshell-skip-link"]') as HTMLAnchorElement | null;
    return {
      marker: active?.getAttribute("data-terp") ?? null,
      id: active?.id ?? "",
      href: (link?.getAttribute("href") ?? "").replace(/^#/, ""),
    };
  });
  expect(landed.marker, "Enter must move focus to main, not merely scroll to it").toBe(
    "appshell-main",
  );
  // The id is per shell instance (useId), not a constant, so the contract is that the LINK
  // points at the element that took focus — asserting a literal would pin the id scheme and
  // did: this line read `toBe("terp-main")` until the constant was replaced, and it failed on
  // `_r_0_` while the behaviour was correct.
  expect(landed.id).toBe(landed.href);
  expect(landed.id, "the skip target must carry an id at all").not.toBe("");
});

test("the open drawer keeps focus, including away from the new skip link", async ({ page }) => {
  // The drawer is role="dialog" aria-modal, so escaping it is a real defect and not a nicety.
  // Adding a skip link OUTSIDE the inert content column was the plausible way to break that:
  // the link sits before the drawer in DOM order and is not covered by the inert attribute the
  // shell puts on appshell-column, so shift-Tab past the drawer's first element is exactly the
  // route that would reach it — and following it would move focus into inert content.
  //
  // It does not, because the drawer's two focus sentinels bounce focus back to the far edge.
  // Asserted in BOTH directions, since only one of them is the interesting one and a test that
  // walked forward alone would say nothing about the route that worries.
  await page.setViewportSize({ width: 420, height: 900 });
  await page.goto("/?theme=light&only=app-shell-drawer-open");
  await page.locator('[data-terp="appshell-sidebar"]').waitFor({ state: "visible" });

  const where = () =>
    page.evaluate(() => {
      const active = document.activeElement;
      return active === null || active.closest('[data-terp="appshell-sidebar"]') === null
        ? (active?.getAttribute("data-terp") ?? active?.tagName.toLowerCase() ?? "none")
        : null;
    });

  // A full cycle forward — more steps than the drawer has focusables, so it wraps at least once.
  for (let step = 0; step < 12; step += 1) {
    await page.keyboard.press("Tab");
    expect(await where(), `Tab step ${step + 1} left the drawer`).toBeNull();
  }
  // And backwards, which is the direction the skip link is actually in.
  for (let step = 0; step < 6; step += 1) {
    await page.keyboard.press("Shift+Tab");
    expect(await where(), `Shift+Tab step ${step + 1} left the drawer`).toBeNull();
  }
});
