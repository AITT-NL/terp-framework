// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import { TERP_STYLES_ID, TERP_STYLES_CSS, injectTerpStyles } from "./styles";

/** The sheet with comments removed — prose must not satisfy a structural assertion. */
const css = TERP_STYLES_CSS.replace(/\/\*[\s\S]*?\*\//g, "");

/**
 * The body of one `@layer <name> { … }` block, brace-matched.
 *
 * Throws rather than returning "" for a name that is not in the sheet: several assertions
 * below are `.not.toContain(...)`, which an empty string satisfies, so a typo'd or renamed
 * layer would silently disable them instead of failing.
 */
function layerBody(name: string): string {
  const open = css.indexOf(`@layer ${name} {`);
  if (open === -1) throw new Error(`styles.ts declares no @layer ${name}`);
  let depth = 0;
  for (let i = css.indexOf("{", open); i < css.length; i += 1) {
    if (css[i] === "{") depth += 1;
    else if (css[i] === "}") {
      depth -= 1;
      if (depth === 0) return css.slice(css.indexOf("{", open) + 1, i);
    }
  }
  throw new Error(`@layer ${name} is not brace-balanced`);
}

/**
 * Whether `body` declares a rule whose selector list contains EXACTLY `selector` — not
 * merely a selector containing it as a substring.
 *
 * The distinction is the whole point: `[data-terp="button"]` is a substring of
 * `[data-terp="button"][data-variant="primary"]`, so a substring check keeps passing after
 * the component's actual base block is deleted and only its variants remain.
 */
function declaresRuleFor(body: string, selector: string): boolean {
  // The selector group excludes braces, so each match starts naturally after the previous
  // rule's closing brace. Anchoring on that brace instead would consume it and match only
  // every other rule — which is how this helper first read the sheet, and what made it
  // report a missing base rule for `input` and a missing gap-0 rule for `stack`.
  for (const match of body.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = match[1].split(",").map((part) => part.trim().replace(/\s+/g, " "));
    if (selectors.includes(selector) && match[2].trim().length > 0) return true;
  }
  return false;
}

afterEach(() => {
  document.querySelectorAll(`style#${TERP_STYLES_ID}`).forEach((node) => node.remove());
});

describe("injectTerpStyles", () => {
  it("appends the stylesheet once and is idempotent on re-invocation", () => {
    injectTerpStyles();
    injectTerpStyles();
    injectTerpStyles();
    const nodes = document.querySelectorAll(`style#${TERP_STYLES_ID}`);
    expect(nodes.length).toBe(1);
    expect(nodes[0]?.textContent ?? "").toContain("data-terp");
    expect(nodes[0]?.textContent ?? "").toContain('[data-terp="input"][type="number"]');
    expect(nodes[0]?.textContent ?? "").toContain("::-webkit-inner-spin-button");
  });

  it("themes scrollbars against the token palette (thin, not the OS default)", () => {
    injectTerpStyles();
    const sheet = document.querySelector(`style#${TERP_STYLES_ID}`)?.textContent ?? "";
    expect(sheet).toContain("scrollbar-width: thin");
    expect(sheet).toContain("scrollbar-color: var(--color-neutral-300) transparent");
    expect(sheet).toContain("::-webkit-scrollbar");
    expect(sheet).toContain("::-webkit-scrollbar-thumb");
  });
});

// The cascade structure the migration rests on (ADR 0094). None of it was pinned by
// anything, and it is invisible to every other lane in the repo: jsdom does not compute the
// cascade, and the visual baselines only capture resting state, so a broken focus ring, a
// broken disabled treatment or an ignored reduced-motion preference all render as a passing
// suite. These assertions are cheap precisely because they read the sheet as text.
describe("cascade structure", () => {
  it("declares the layer order the rules depend on, before any rule", () => {
    // Without this statement the layers would be ordered by first appearance, which is the
    // same order today and would silently stop being so the moment a rule is added above.
    expect(css).toContain("@layer terp.reset, terp.base, terp.state, terp.motion;");
    expect(css.indexOf("@layer terp.reset, terp.base")).toBeLessThan(css.indexOf("@layer terp.base {"));
  });

  it("keeps the shared focus ring in terp.state, not terp.base", () => {
    // The ring and [data-terp="button"][data-variant="primary"] both weigh (0,2,0), so in a
    // single layer the later rule wins — and the ring is declared first. In terp.base the
    // primary button's resting box-shadow suppresses it entirely (measured: the focused
    // button computes its resting shadow instead of the ring).
    expect(layerBody("terp.state")).toContain("[data-terp]:focus-visible");
    expect(layerBody("terp.base")).not.toContain(":focus-visible");
  });

  it("declares no !important in terp.base — a base rule never needs to shout", () => {
    // !important in this sheet means exactly one thing: a rule that must beat an inline base
    // style on a component that has not migrated yet. That is always a state rule, so an
    // !important appearing in terp.base is a sign someone escalated a resting style.
    expect(layerBody("terp.base")).not.toContain("!important");
  });

  it("keeps !important on every rule a component with inline base styles still relies on", () => {
    // The tax comes off per CONSUMER, not per rule, and the condition is the LAST element a
    // selector matches rather than the first. Every entry below names the inline declaration it
    // has to out-shout, so the next reader can re-derive when it may retire instead of trusting
    // this list — the previous version of this test named ConfirmDialog and Popover as reasons
    // for the focus ring, and both had migrated a stage earlier.
    //
    // This direction matters more than the converse and used to be pinned six times worse: the
    // regression that shipped — a disabled Combobox painted exactly like an enabled one — came
    // from dropping an escalation early, and only three of twelve were asserted. Every rule here
    // is a hover, disabled or focus state, which is to say invisible to both lanes: the
    // baselines capture the resting state and axe does not evaluate hover.
    const state = layerBody("terp.state");
    for (const [rule, consumer] of [
      // Six of the ten elements wearing this marker still declare background and colour inline:
      // AppShell's two header toggles (toggleStyle) and DataViewPagination's four arrows
      // (pagerButtonStyle). The marker deliberately has no base rule.
      ['[data-terp="iconbutton"]:hover', "AppShell toggleStyle / DataViewPagination pagerButtonStyle"],
      // Only the pager can be disabled, and pagerButtonStyle sets cursor inline.
      ['[data-terp="iconbutton"]:disabled', "DataViewPagination pagerButtonStyle cursor"],
      // The shell's nav anchors carry colour inline (NAV_LINK_STYLE).
      ['[data-terp="appshell-nav"] a:hover', "AppShell NAV_LINK_STYLE colour"],
      // HubCard's visible edge is a border on hubcard-body, declared inline by HubPage. Worth
      // pinning because the rule this replaced was DEAD: it recoloured the outer <li>, which
      // computes `0px none`, so the accent edge never painted at all — measured in a browser,
      // since no baseline captures a hover.
      ['[data-terp="hubcard"]:hover [data-terp="hubcard-body"]', "HubPage cardBodyStyle border"],
      // The card title's colour and transition are inline (titleTextStyle).
      ['[data-terp="hubcard"]:hover [data-terp="hubcard-title"]', "HubPage titleTextStyle colour"],
    ] as const) {
      const at = state.indexOf(rule);
      expect(at, `${rule} should still be declared`).toBeGreaterThan(-1);
      expect(
        state.slice(at, state.indexOf("}", at)),
        `${rule} must keep its escalation while ${consumer} is inline`,
      ).toContain("!important");
    }
    // And the reduced-motion transition override, which reaches AppShell's nav links and
    // HubPage's card title — both of which declare `transition` in a style object, and no layer
    // beats the style attribute. NOT the sidebar collapse: that <aside> carries no marker, so no
    // selector in the block matches it and a reduced-motion user still sees the rail animate.
    // The sheet's own comment says so; this one used to claim otherwise.
    expect(layerBody("terp.motion")).toContain("transition: none !important");
  });

  it("keeps the focus-within tint scoped to rows something will actually open", () => {
    // The row marker is unconditional, so this selector reaches every row unless it says
    // otherwise. Unguarded it paints a brand wash on any row holding focus — a selection
    // checkbox in a view with no onRowClick — over that row's status tone, for a row nothing
    // will open. Invisible to all three lanes: resting baselines, a static tree, and a
    // keyboard lane that asserts where focus goes rather than what it paints.
    const state = layerBody("terp.state");
    expect(
      declaresRuleFor(state, '[data-terp="dataview-row"][data-clickable="true"]:focus-within td'),
      "the row's focus-within tint must be guarded on data-clickable",
    ).toBe(true);
    expect(
      state,
      "an unguarded row focus-within selector would reach every row with a checkbox in it",
    ).not.toContain('[data-terp="dataview-row"]:focus-within');
  });

  it("names every element the reduced-motion block has to reach", () => {
    // The layer wins the cascade, but only over elements a selector actually matches. A
    // transition on an element with no data-terp of its own escapes unless it is listed
    // here by name — which is how the breadcrumb link kept animating.
    const motion = layerBody("terp.motion");
    for (const selector of [
      "[data-terp]",
      '[data-terp="appshell-nav"] a',
      '[data-terp="breadcrumbs"] a',
      '[data-terp="dataview-table"] tbody tr',
    ]) {
      expect(motion, `${selector} must be in the reduced-motion selector list`).toContain(selector);
    }
    // Every transition this sheet declares is either on a marked element or on one of the
    // descendant selectors above. A new descendant rule with a transition has to join them.
    const base = layerBody("terp.base");
    for (const match of base.matchAll(/([^{}]+)\{([^{}]*transition:[^{}]*)\}/g)) {
      const selector = match[1].trim().replace(/\s+/g, " ");
      const marked = selector.includes("[data-terp") && !/\s[a-z]+$/.test(selector);
      expect(
        marked || motion.includes(selector),
        `${selector} declares a transition but reduced motion cannot reach it`,
      ).toBe(true);
    }
  });

  it("declares a gap rule for every step SpaceToken allows", () => {
    // gap moved from a computed inline value to a rule per step, so the union and the sheet
    // are now two lists maintained by hand. Widening SpaceToken without adding rules would
    // silently fall back to the default gap rather than fail.
    const base = layerBody("terp.base");
    for (const token of [0, 1, 2, 3, 4, 6, 8]) {
      for (const marker of ["stack", "card"]) {
        expect(
          declaresRuleFor(base, `[data-terp="${marker}"][data-gap="${token}"]`),
          `${marker} has no rule for gap ${token}`,
        ).toBe(true);
      }
    }
  });

  it("carries no !important on a marker whose every consumer has migrated", () => {
    // The converse, so the escalation cannot outlive its reason. A rule left shouting after
    // its last inline consumer is gone is invisible: it works, and it silently outranks the
    // app theme.css that ADR 0094 exists to empower.
    const state = layerBody("terp.state");
    for (const rule of [
      '[data-terp="input"]:hover',
      '[data-terp="input"]:focus',
      '[data-terp="input"]:disabled',
      '[data-terp="input"][aria-invalid="true"]',
      '[data-terp="tab"]:hover',
      '[data-terp="tab"]:disabled',
      // MenuItem is the only element in the package wearing this marker, so its escalation
      // retired the moment the component stopped carrying inline base styles — unlike
      // `input`, which six elements wear and which had to wait for the last of them.
      '[data-terp="menu-item"]:hover',
      '[data-terp="menu-item"][data-selected="true"]',
      '[data-terp="menu-item"]:disabled',
      '[data-terp="menu-trigger"]:hover',
      // The brand link declares no inline background — brandLinkStyle sets colour, radius and
      // box-sizing and nothing else — so this rule never had anything to out-shout.
      '[data-terp="appshell-brand"]:hover',
      // The textbook per-consumer case, in both directions. This selector has two halves
      // and they were never in the same state: the row half had nothing to out-shout,
      // because a body cell declares no background, while the card half faced
      // DataViewCardList's inline background on the element it matches. The escalation
      // came off when the card migrated, which is the LAST of the two rather than the
      // first — and the card's tone rules now lose to it on layer instead.
      '[data-terp="dataview-card"]:focus-within',
    ]) {
      const at = state.indexOf(rule);
      expect(at, `${rule} should still be declared`).toBeGreaterThan(-1);
      const block = state.slice(at, state.indexOf("}", at));
      expect(block, `${rule}: every element wearing that marker is migrated`)
        .not.toContain("!important");
    }

    // The two widest escalations in the sheet retired in stage 4, and they are worth their own
    // assertions because both had a real consumer until it migrated.
    //
    // The focus ring's !important could only ever beat an INLINE box-shadow on an element the
    // selector matches, and there is none left: ConfirmDialog's dialog and Popover's panel were
    // the two, and both took their surface from the sheet in stage 4. Of the three inline
    // box-shadows remaining, AppShell's drawer and LoginView's panel sit on elements with no
    // marker at all, and DataViewCardList's card is a div with onClick and no tabIndex, so it
    // cannot match :focus-visible — which is why the sheet reaches it with :focus-within.
    // Measured after removing it: a keyboard-focused primary button and a focused menu item both
    // still compute rgba(37,99,235,0.35) 0 0 0 3px, because the LAYER carries the ring, not the
    // escalation. That was always the claim in this file's header; the escalation was belt.
    const at = state.indexOf("[data-terp]:focus-visible");
    expect(at, "the shared focus ring should still be declared").toBeGreaterThan(-1);
    expect(
      state.slice(at, state.indexOf("}", at)),
      "the focus ring's last inline box-shadow consumer migrated in stage 4",
    ).not.toContain("!important");

    // And the spinner's reduced-motion override never had a consumer: the rotation is declared by
    // this sheet in terp.state, terp.motion sits above it, and no component has ever set
    // `animation` in a style object. Measured under prefers-reduced-motion: animation-name
    // computes `none` either way.
    const motion = layerBody("terp.motion");
    const spin = motion.indexOf('[data-terp="spinner-ring"]');
    expect(spin, "the spinner's reduced-motion rule should still be declared").toBeGreaterThan(-1);
    expect(
      motion.slice(spin, motion.indexOf("}", spin)),
      "the spinner's animation is a sheet rule in a lower layer, so layer order already wins",
    ).not.toContain("!important");
  });

  it("states the real cost of an escalation: a layered !important is a wall, not a hurdle", () => {
    // The reason both directions of this ledger are gated, recorded where the rules are.
    //
    // For NORMAL declarations an unlayered author rule beats a layered one whatever its
    // specificity, which is what lets an app's theme.css override this sheet. For IMPORTANT
    // declarations the layer order REVERSES, and unlayered styles sort last — so a layered
    // !important beats an unlayered !important. Measured in a browser against the real sheet:
    // with the ring escalated, an unlayered rule lost both with and without !important; with it
    // retired, an unlayered rule wins either way.
    //
    // So an escalation does not merely outrank theme.css. It makes that declaration
    // UNTHEMEABLE — there is no author-side override at all. That is why the count is the
    // phase's measurable and why retiring one is a feature rather than tidying.
    expect(css).toContain("@layer terp.reset, terp.base, terp.state, terp.motion;");
    // Eight left, every one of them named in the must-keep list above with its inline
    // consumer. The ninth retired with DataViewCardList.
    const declarations = css.split("!important").length - 1;
    expect(declarations).toBe(8);
  });

  it("declares a rule for every DataView surface reached structurally", () => {
    // The check below asks for an EXACT `[data-terp="x"]` selector, and several DataView
    // surfaces deliberately have none: a table has hundreds of cells, so stamping an
    // attribute on each of them buys nothing a descendant selector does not already do.
    // Those rules are therefore invisible to that check — deleting one leaves the marker
    // inventory intact and the whole table unpadded. So they are named here as the
    // selectors they actually are.
    //
    // Note which ancestor each descends from. Cells hang off the ROW rather than off the
    // table, because a "tbody td" selector also matches the expanded row's cell — which
    // carries a padding and a border of its own and would then have to out-specify this
    // rule instead of simply not matching it. And the two visually-hidden surfaces are
    // qualified by element: the actions BODY cell's only child is the row-actions cluster,
    // so an unqualified `> span` would clip a live control out of the layout.
    const base = layerBody("terp.base");
    for (const selector of [
      '[data-terp="dataview-table"] > thead > tr > th',
      '[data-terp="dataview-row"] > td',
      '[data-terp="dataview-row"][data-clickable="true"]',
      'th[data-terp="dataview-expand-cell"]',
      'th[data-terp="dataview-select-cell"]',
      'th[data-terp="dataview-actions-cell"]',
      'td[data-terp="dataview-actions-cell"]',
      'th[data-terp="dataview-actions-cell"] > span',
      '[data-terp="dataview-card-main"] > span',
    ]) {
      expect(
        declaresRuleFor(base, selector),
        `${selector} must be declared as a rule of its own`,
      ).toBe(true);
    }
    // Every row tone, or a tone silently renders untinted — and the row-tones baseline only
    // covers the three the specimen happens to use.
    for (const tone of ["neutral", "info", "success", "warning", "danger"]) {
      expect(
        declaresRuleFor(base, `[data-terp="dataview-row"][data-tone="${tone}"]`),
        `row tone ${tone} has no rule`,
      ).toBe(true);
      expect(
        declaresRuleFor(base, `[data-terp="dataview-card"][data-tone="${tone}"]`),
        `card tone ${tone} has no rule`,
      ).toBe(true);
    }
    // The selection tint must stay guarded against a toned row. Both weigh (0,2,0) without
    // the :not(), which would leave source order deciding whether a failed row reads as
    // failed or merely as selected.
    expect(
      declaresRuleFor(base, '[data-terp="dataview-row"][data-selected="true"]:not([data-tone])'),
      "the selection tint must exclude toned rows explicitly, not by source order",
    ).toBe(true);
  });

  it("reads the density tokens from rules, and re-scopes them unlayered", () => {
    // The four cell-padding tokens were published a stage before anything read them and
    // were deleted for exactly that. These are the readers; without them the tokens are
    // back to being decoration, and the compact attribute silently does nothing.
    for (const token of ["--density-cell-pad-y", "--density-cell-pad-x"]) {
      expect(css, `${token} is published but nothing reads it`).toContain(`var(${token})`);
    }
    // And the re-scoping stays OUTSIDE every layer. Inside one it would lose to the
    // contract's own unlayered :root values whenever the attribute sits on the same element
    // those target — the app-wide case, data-density on <html> — and compact would do
    // nothing at all. Asserted by subtracting the layer bodies from the sheet.
    const density = '[data-density="compact"]';
    expect(css).toContain(density);
    for (const layer of ["terp.reset", "terp.base", "terp.state", "terp.motion"]) {
      expect(layerBody(layer), `${density} must not be inside @layer ${layer}`).not.toContain(
        density,
      );
    }
    const at = css.indexOf(density);
    const block = css.slice(at, css.indexOf("}", at));
    for (const token of [
      "--density-control-min-height",
      "--density-cell-pad-y",
      "--density-cell-pad-x",
    ]) {
      expect(block, `${token} is not re-scoped under compact`).toContain(`${token}: var(`);
    }
  });

  it("keeps the markdown wrapper boxless", () => {
    // display: contents is the entire rule, and it has to stay the entire rule. Every
    // non-inherited property on such an element is silently dropped, so a padding or a border
    // added here would do nothing and nothing else in the suite would say so — the base-rule
    // check below only asks that the block is non-empty, which a block of dead declarations
    // satisfies. Prose rhythm belongs in descendant rules.
    const base = layerBody("terp.base");
    const at = base.indexOf('[data-terp="markdown"]');
    expect(at).toBeGreaterThan(-1);
    const block = base.slice(base.indexOf("{", at) + 1, base.indexOf("}", at));
    expect(block.trim()).toBe("display: contents;");
  });

  it("gives every migrated component a base rule in terp.base", () => {
    // markers.test.ts pins the marker join in both directions but cannot see a *deleted*
    // rule: removing a whole block only shrinks the styled set, which still passes. These
    // components render no inline base styles at all, so a missing rule here means the
    // component renders unstyled.
    const base = layerBody("terp.base");
    for (const marker of [
      "button",
      "badge",
      "alert",
      "tooltip",
      "input",
      "field",
      "control-label",
      "checkbox",
      "radio",
      "switch",
      "stack",
      "detail-list",
      "combobox",
      "combobox-list",
      "combobox-option",
      "calendar",
      "calendar-day",
      "calendar-grid",
      "calendar-week",
      "card",
      "card-header",
      "card-title",
      "tabs",
      "tab",
      "tab-list",
      "tab-panel",
      "breadcrumbs",
      "empty-state",
      "error-state",
      "loading-state",
      "spinner-ring",
      "icon",
      "nav-icon",
      "nav-icon-fallback",
      "language-switcher",
      "theme-toggle",
      "theme-toggle-label",
      "language-switcher-label",
      "markdown",
      "menu",
      "menu-item",
      "menu-trigger",
      "menu-item-icon",
      "menu-item-check",
      "page-actions",
      "popover",
      "popover-panel",
      "toast-viewport",
      "toast",
      "toast-icon",
      "toast-body",
      "toast-title",
      "dialog",
      "dialog-body",
      "dialog-title",
      "dialog-description",
      "dialog-actions",
      "user-menu",
      "user-menu-avatar",
      "user-menu-email",
      "user-menu-header",
      "user-menu-identity",
      "user-menu-role",
      "breadcrumbs-current",
      "dataview-table",
      "dataview-column-sort",
      "dataview-column-resizer",
      "dataview-row-open",
      "dataview-card",
      "dataview-card-list",
      "dataview-card-main",
      "dataview-card-body",
      "dataview-card-expanded",
      "dataview-card-fields",
      "dataview-card-heading",
      "dataview-card-title",
      "dataview-card-status",
      "dataview-card-meta",
    ]) {
      expect(
        declaresRuleFor(base, `[data-terp="${marker}"]`),
        `[data-terp="${marker}"] must have a base rule of its own, not merely appear in one`,
      ).toBe(true);
    }
  });
});
