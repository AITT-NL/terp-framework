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

/**
 * The laid-out width of the root box, and the viewport width it sits in.
 *
 * `getBoundingClientRect()`, and NOT `documentElement.clientWidth`, which is the obvious
 * probe and the wrong one: for the root element `clientWidth` reports the viewport, so it
 * reads 1280 whether or not a gutter is reserved. Measured on this page with the gutter
 * live — `innerWidth` 1280, `clientWidth` 1280, root rect 1270 — so a test written against
 * `clientWidth` passes identically before and after the declaration and proves nothing.
 */
async function rootWidth(page: import("@playwright/test").Page) {
  return page.evaluate(() => ({
    root: document.documentElement.getBoundingClientRect().width,
    viewport: window.innerWidth,
  }));
}

test("the scrollbar gutter is reserved on a page that fits and one that does not", async ({
  page,
}) => {
  // `scrollbar-gutter: stable` exists so the content box is the same width whether or not a
  // page overflows, which is what stops the whole layout shifting sideways and back as a
  // user navigates between a short screen and a long one.
  //
  // What this lane can and cannot say about that is worth stating exactly, because the
  // obvious test is vacuous here and looks fine. **This Chromium reserves no layout space
  // for the viewport scrollbar at all.** Measured against the sheet with the declaration
  // removed: a solo specimen page (does not overflow) and the full catalog (many screens
  // tall) both report a root box of 1280 in a 1280 viewport, and the specimen card comes out
  // at 1232 on both. So there is no jump in this browser to prevent, and an assertion that
  // the two page shapes agree passes identically before and after the declaration — it
  // measures the browser, not the sheet.
  //
  // What IS checkable is the reservation itself: with the declaration the root box is 1270
  // on both page shapes. So this asserts the gutter is present, on both shapes, and the
  // "no jump" property it buys is left to the browsers that take scrollbar space — which is
  // most desktop Chrome and Firefox on Windows and Linux, i.e. the users, just not the lane.
  //
  // Note also that `documentElement.clientWidth` cannot see this at all (see rootWidth).
  //
  // Making the harness model a space-taking scrollbar is possible — Chromium takes a flag —
  // and is deliberately not done: it would also give every INNER scroll container a
  // space-taking bar, starting with the DataView's horizontal overflow, which is a change to
  // component layout wearing a harness change's clothes.
  for (const url of ["/?theme=light&only=button-variants", "/?theme=light"]) {
    await page.goto(url);
    await page.locator("[data-specimen]").first().waitFor({ state: "visible" });
    const { root, viewport } = await rootWidth(page);
    expect(root, `${url} reserves no scrollbar gutter`).toBeLessThan(viewport);
  }
});

test("the three button cursors resolve, and loading beats disabled", async ({ page }) => {
  // A cursor is invisible to every other lane: Playwright does not paint a pointer into a
  // screenshot and axe does not read one, so no baseline in this suite has ever held
  // `cursor: pointer`, `not-allowed` or `progress` — three declarations, all unobservable.
  //
  // The pair that matters is the last two. A loading button IS disabled, the component sets
  // both, and the disabled rule lives in terp.state — so a `data-loading` rule in terp.base
  // loses on layer order and the cursor silently stays `not-allowed`, which tells a user "you
  // may not" where the truth is "not yet". `styles.test.ts` pins the structure that produces
  // the right answer; this reads the answer.
  await page.goto("/?theme=light&only=button-variants");
  await page.locator('[data-terp="button"]').first().waitFor({ state: "visible" });
  expect(
    await page.evaluate(
      () => getComputedStyle(document.querySelector('[data-terp="button"]')!).cursor,
    ),
  ).toBe("pointer");

  await page.goto("/?theme=light&only=button-disabled");
  await page.locator('[data-terp="button"]').first().waitFor({ state: "visible" });
  expect(
    await page.evaluate(
      () => getComputedStyle(document.querySelector('[data-terp="button"]')!).cursor,
    ),
  ).toBe("not-allowed");

  await page.goto("/?theme=light&only=button-loading");
  await page.locator('[data-terp="button"]').first().waitFor({ state: "visible" });
  const loading = await page.evaluate(() => {
    const button = document.querySelector('[data-terp="button"][data-loading="true"]')!;
    return {
      cursor: getComputedStyle(button).cursor,
      disabled: (button as HTMLButtonElement).disabled,
      busy: button.getAttribute("aria-busy"),
    };
  });
  // Disabled and busy as well as progress — the assertion is that all three hold at once,
  // because `progress` on a control a second click could still fire is decoration.
  expect(loading).toEqual({ cursor: "progress", disabled: true, busy: "true" });
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

test("the audit payload is a scroll container, not a box that grew", async ({ page }) => {
  // `admin-payload` declares `overflow-x: auto`, and whether that does anything is a fact
  // about resolved layout rather than about the sheet — so a structural test cannot tell the
  // two apart and the baseline can only see the consequence.
  //
  // It is here because the first version of the specimen gated NOTHING and looked like it did.
  // Rendered inside a real expanded `DataViewTable` row — the way `AuditLogAdmin` renders it —
  // the `<pre>` measured 1594px with `scrollWidth === clientWidth`: it never scrolled, it grew,
  // and it pushed the table from 1232 to 1626. A `<td>` under `table-layout: auto` is
  // shrink-to-fit, so nothing there ever constrains the box, and `overflow-x` on a box that is
  // never narrower than its content is inert. The picture was a clipped `<pre>` either way.
  //
  // So the specimen constrains the container, and this reads the numbers back: content wider
  // than the box, and the box scrolling rather than the page. Deleting `overflow-x: auto`
  // repaints both payload baselines by ~91,500 pixels AND fails this, which is the pair worth
  // having — one says the picture changed, the other says why.
  await page.goto("/?theme=light&only=admin-payload");
  await page.locator('[data-terp="admin-payload"]').waitFor({ state: "visible" });
  const box = await page.evaluate(() => {
    const pre = document.querySelector('[data-terp="admin-payload"]')!;
    return {
      client: pre.clientWidth,
      scroll: pre.scrollWidth,
      overflowX: getComputedStyle(pre).overflowX,
      // A scroll container has to be reachable by keyboard (SC 2.1.1) — the same reason
      // Code block carries one. axe reports the absence as scrollable-region-focusable, and it
      // did, on this specimen's first run.
      //
      // This assertion holds the SPECIMEN to the component, not the component to the contract:
      // the specimen writes its own <pre> with its own literal tabIndex, so deleting the
      // attribute from AuditLogAdmin would leave every lane here green. The component's own
      // gate is in admin.test.tsx ("keeps the audit payload's scroll container reachable by
      // keyboard"), which renders the packaged screen and expands a real row. Worth saying,
      // because a test that asserts its own fixture back to itself reads exactly like coverage.
      tabIndex: (pre as HTMLElement).tabIndex,
    };
  });
  expect(box.overflowX).toBe("auto");
  expect(box.scroll, "the payload must be wider than its box or the rule is inert").toBeGreaterThan(
    box.client,
  );
  expect(box.tabIndex).toBe(0);
});

test("the content measure caps the body and leaves the header on the full track", async ({
  page,
}) => {
  // The measure and the subheader band are one mechanism (ADR 0097 §2), and the baseline can
  // only say "these two are different widths". The numbers are the contract, so they live
  // here: the page's own header keeps the article's full track while every other direct child
  // is capped at `--shell-content-max-width`.
  //
  // It is also the anti-vacuity guard for `app-shell-measured`, and that is not theoretical.
  // The rule only fires once the article's track is wider than the 80rem measure, and the
  // article is much narrower than the window — the sidebar, `appshell-main`'s padding, the
  // specimen's own box and the scrollbar gutter all come off it. Measured at three widths:
  // 1280 gives article 898 / body 898, 1600 gives 1218 / 1218, and only 1920 gives 1538 / 1280.
  // So both the pinned viewport AND the obvious wider one would have recorded a green baseline
  // over a declaration that never fired.
  await page.setViewportSize({ width: 1920, height: 900 });
  await page.goto("/?theme=light&only=app-shell-measured");
  await page.locator('[data-terp="page"]').waitFor({ state: "visible" });

  const measured = await page.evaluate(() => {
    const article = document.querySelector('[data-terp="page"]')!;
    const header = article.querySelector(':scope > header')!;
    const body = [...article.children].filter((child) => child.tagName !== "HEADER");
    const width = (element: Element) => Math.round(element.getBoundingClientRect().width);
    return {
      article: width(article),
      header: width(header),
      body: body.map(width),
      token: getComputedStyle(document.documentElement)
        .getPropertyValue("--shell-content-max-width")
        .trim(),
    };
  });

  expect(measured.token).toBe("80rem");
  // The header spans the track, and the track is genuinely wider than the measure — assert
  // that rather than a bare inequality, or the test passes on a page too narrow to cap.
  expect(measured.header).toBe(measured.article);
  expect(
    measured.article,
    "the specimen's viewport must leave a track wider than the measure, or nothing is capped",
  ).toBeGreaterThan(1280);
  // Every body child sits at the measure, not at the track.
  expect(measured.body.length).toBeGreaterThan(0);
  expect(measured.body).toEqual(measured.body.map(() => 1280));
});

test("the measure applies to nothing until the shell asks for it", async ({ page }) => {
  // The other half of "nothing moves for any app today": with `contentWidth` at its default the
  // shell stamps no attribute and the rule matches nothing.
  //
  // The first version of this test could not fail, and the way it could not is worth keeping.
  // It loaded `app-shell` — whose body is a bare `<p>`, with no `[data-terp="page"]` anywhere —
  // so the second half of the selector under test matched nothing regardless of the attribute;
  // it then measured `main.firstElementChild` into a variable and never asserted it, leaving
  // two assertions about a flex column's width that the measure cannot affect in either state.
  // A control that shares no mechanism with the thing it controls for is not a control.
  //
  // So the control is the SAME tree, with the attribute removed at runtime: a page that is
  // demonstrably capped, uncapped by exactly the one input under test. No second specimen, and
  // nothing left to differ except the attribute.
  await page.setViewportSize({ width: 1920, height: 900 });
  await page.goto("/?theme=light&only=app-shell-measured");
  await page.locator('[data-terp="page"]').waitFor({ state: "visible" });

  const bodyWidth = () =>
    page.evaluate(() => {
      const article = document.querySelector('[data-terp="page"]')!;
      const body = [...article.children].filter(
        (child) => child.getAttribute("data-terp") !== "page-header",
      );
      return {
        attribute: document
          .querySelector('[data-terp="appshell"]')!
          .getAttribute("data-content-width"),
        article: Math.round(article.getBoundingClientRect().width),
        body: body.map((child) => Math.round(child.getBoundingClientRect().width)),
      };
    });

  const capped = await bodyWidth();
  expect(capped.attribute).toBe("measured");
  expect(capped.body).toEqual(capped.body.map(() => 1280));

  await page.evaluate(() => {
    document.querySelector('[data-terp="appshell"]')!.removeAttribute("data-content-width");
  });

  const uncapped = await bodyWidth();
  expect(uncapped.attribute).toBeNull();
  // The same children, now at the full track — so the attribute is doing the whole job.
  expect(uncapped.article).toBeGreaterThan(1280);
  expect(uncapped.body).toEqual(uncapped.body.map(() => uncapped.article));
});

test("the measure composes with a component's own narrower measure instead of replacing it", async ({
  page,
}) => {
  // The regression guard for the defect that made the measure a `width` rather than a
  // `max-width`, and it is here rather than in a baseline because no picture can hold it.
  //
  // The measure's selector weighs (0,4,0) — four attribute selectors, one of them inside
  // `:not()` — so as a `max-width` it outranked every component declaring a narrower one, and
  // five of them are legal children of a governed body. Measured before the fix: an
  // `admin-form` inside a measured shell computed 1280px instead of 512px, so the packaged
  // provisioning form rendered two and a half times too wide. The shell was WIDENING the
  // components that already carry their own measure — `Text`'s `measure` prop included, which
  // is the prop this mechanism was modelled on.
  //
  // As a `width` it composes, because CSS resolves `max-width` after `width`. Each of the five
  // must come back at its OWN measure, and a child with none must come back at the shell's —
  // that last case is what stops a fix that simply disables the rule from passing.
  //
  // Probes are injected rather than rendered as specimens on purpose: the contract is a
  // cascade interaction across five unrelated components, and a specimen holding all of them
  // would be a kitchen sink whose picture proves nothing about any single one.
  await page.setViewportSize({ width: 1920, height: 900 });
  await page.goto("/?theme=light&only=app-shell-measured");
  await page.locator('[data-terp="page"]').waitFor({ state: "visible" });

  const widths = await page.evaluate(() => {
    const article = document.querySelector('[data-terp="page"]')!;
    const probe = (marker: string, attribute?: [string, string]) => {
      const element = document.createElement("div");
      element.setAttribute("data-terp", marker);
      if (attribute !== undefined) {
        element.setAttribute(attribute[0], attribute[1]);
      }
      article.append(element);
      const width = Math.round(element.getBoundingClientRect().width);
      element.remove();
      return width;
    };
    return {
      // 32rem, 40rem and 26rem respectively — each component's own declaration.
      adminForm: probe("admin-form"),
      resourceList: probe("resource-list"),
      dialog: probe("dialog"),
      // 48ch, which is a font-relative measure and therefore not a round pixel count.
      textNarrow: probe("text", ["data-measure", "narrow"]),
      // No measure of its own, so this one takes the shell's.
      stack: probe("stack"),
    };
  });

  expect(widths.adminForm, "admin-form declares max-width: 32rem").toBe(512);
  expect(widths.resourceList, "resource-list declares max-width: 40rem").toBe(640);
  expect(widths.dialog, "dialog declares max-width: 26rem").toBe(416);
  expect(widths.textNarrow, "Text measure=narrow declares max-width: 48ch").toBeLessThan(512);
  // And the shell's measure still applies where nothing else claims one, or a "fix" that
  // deleted the rule would satisfy every assertion above.
  expect(widths.stack, "a child with no measure of its own takes the shell's").toBe(1280);
});

test("the header-placed nav is not a scroll container", async ({ page }) => {
  // The third of the header placement's three rules, and the only one no baseline can hold:
  // `overflow` only shows itself around something that overflows, and at rest nothing does.
  //
  // It is a fix rather than a reset. The nav's sidebar rule sets `overflow-y: auto` so a long
  // nav scrolls inside a full-height column — and a computed `overflow-y` other than `visible`
  // forces `overflow-x` to `auto` as well. In the header the box is exactly one link tall, so
  // that scroller can never scroll and its only effect is to clip a focused link's 2px outline
  // and 3px ring on both edges.
  //
  // The pair is the assertion: the same marker, the same component, two placements. Without
  // the sidebar half a rule that simply set `overflow: visible` everywhere would pass here and
  // silently take the sidebar's scrolling away.
  const overflowOf = (selector: string) =>
    page.evaluate((css) => {
      const element = document.querySelector(css);
      if (element === null) {
        return null;
      }
      const style = getComputedStyle(element);
      return { x: style.overflowX, y: style.overflowY };
    }, selector);

  await page.goto("/?theme=light&only=app-shell-header-nav");
  await page.locator('[data-terp="appshell-nav"]').waitFor({ state: "visible" });
  expect(await page.locator('[data-terp="appshell-sidebar"]').count()).toBe(0);
  expect(await overflowOf('[data-terp="appshell-nav"]')).toEqual({
    x: "visible",
    y: "visible",
  });

  await page.goto("/?theme=light&only=app-shell");
  await page.locator('[data-terp="appshell-sidebar"]').waitFor({ state: "visible" });
  expect(await overflowOf('[data-terp="appshell-nav"]')).toEqual({ x: "auto", y: "auto" });
});

test("the nav group's stacking margin is scoped to the sidebar, and the header row is flat", async ({
  page,
}) => {
  // The defect this exists for was found by review, not by a lane, and no lane could have found
  // it. The separation between navigation groups is `margin-block-start` on an adjacent sibling.
  // In the sidebar that is a block-axis margin between two stacked blocks, which is the whole
  // intent. In header placement the nav is a flex ROW, and there the same declaration is a
  // CROSS-axis margin on a flex item — never collapsed, always applied — so every group after
  // the first is pushed down and drags the sticky header's height with it.
  //
  // A screenshot cannot gate that. The header-groups baseline is NEW, and Playwright writes a
  // missing baseline before failing, so its first recording would simply have captured the
  // defect and called it the truth. The value has to be read.
  //
  // The pair is the assertion, on the same reasoning as the overflow test above: the same
  // marker, the same component, two placements. Assert only the header half and a rule that
  // deleted the margin outright would pass here while silently un-grouping the sidebar.
  const marginOf = (selector: string) =>
    page.evaluate((css) => {
      const element = document.querySelectorAll(css)[1];
      if (element === undefined) {
        return null;
      }
      return getComputedStyle(element).marginBlockStart;
    }, selector);

  // Header: the second group carries no stacking margin...
  await page.goto("/?theme=light&only=app-shell-header-nav-groups");
  await page.locator('[data-terp="appshell-nav"]').waitFor({ state: "visible" });
  expect(await page.locator('[data-terp="appshell-nav-group"]').count()).toBe(3);
  expect(await marginOf('[data-terp="appshell-nav-group"]')).toBe("0px");

  // ...and the consequence, which is the thing anyone actually cares about: the first link of
  // each group sits on one line. Read as geometry rather than as a declaration, so it stays true
  // however the row is expressed.
  const linkTops = await page.evaluate(() =>
    [...document.querySelectorAll('[data-terp="appshell-nav-group"]')].map((group) => {
      const anchor = group.querySelector("a");
      return anchor === null ? null : Math.round(anchor.getBoundingClientRect().top);
    }),
  );
  expect(new Set(linkTops.filter((top) => top !== null)).size).toBe(1);

  // Sidebar: the same second group DOES carry it. 1rem at the root font size.
  await page.goto("/?theme=light&only=app-shell-nav-groups");
  await page.locator('[data-terp="appshell-sidebar"]').waitFor({ state: "visible" });
  expect(await marginOf('[data-terp="appshell-nav-group"]')).toBe("16px");
});
