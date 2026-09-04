// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import { TERP_STYLES_ID, TERP_STYLES_CSS, injectTerpStyles } from "./styles";

/** The sheet with comments removed — prose must not satisfy a structural assertion. */
const css = TERP_STYLES_CSS.replace(/\/\*[\s\S]*?\*\//g, "");

/**
 * One source file, read as text, so a union declared in TypeScript can be compared against the
 * rules the sheet declares for it. Narrow on purpose: this file needs exactly one module, and a
 * `./**` glob would pull the 180 KB stylesheet in a second time.
 */
const sources = import.meta.glob("./dataview/types.ts", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

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
  it("adopts a constructable stylesheet when the document supports one", () => {
    // jsdom exposes the CSSStyleSheet constructor but not document.adoptedStyleSheets,
    // so the property is defined here to reach the branch a real browser takes. That
    // branch is the whole point of the injector: an adopted sheet is not governed by
    // CSP's style-src, so a generated app needs no 'unsafe-inline' — measured in
    // Chromium, where a <style> element is reported as style-src-elem and dropped.
    const sheets: CSSStyleSheet[] = [];
    Object.defineProperty(document, "adoptedStyleSheets", {
      configurable: true,
      get: () => sheets,
      set: (next: CSSStyleSheet[]) => {
        sheets.length = 0;
        sheets.push(...next);
      },
    });
    try {
      injectTerpStyles();
      expect(sheets.length).toBe(1);
      // No element: taking the adopted route must not also append a <style>, or the
      // page would carry the rules twice and still need the CSP keyword.
      expect(document.getElementById(TERP_STYLES_ID)).toBeNull();
      expect(sheets[0]?.cssRules.length ?? 0).toBeGreaterThan(0);

      // Idempotent by the sheet's own mark rather than by an element id.
      injectTerpStyles();
      injectTerpStyles();
      expect(sheets.length).toBe(1);
    } finally {
      delete (document as unknown as { adoptedStyleSheets?: unknown }).adoptedStyleSheets;
    }
  });

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
    // And reserves the gutter, so the content box is the same width on a page that
    // scrolls and a page that fits. The structural half; the workbench's computed lane
    // measures the reserved width itself, which is the half that can tell whether the
    // browser honoured it.
    expect(sheet).toContain("scrollbar-gutter: stable");
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

  it("gives the focus ring an opaque colour, not a transparent outline", () => {
    // SC 1.4.11 asks 3:1 of a focus indicator. The ring used to declare a TRANSPARENT
    // outline, which left a translucent box-shadow as the whole visible indicator — and a
    // translucent shadow's effective colour is its alpha blend over the surface behind it.
    // Blended, it measured 1.67 in light and never better than 2.73 in any theme but
    // contrast, so four of five shipped palettes failed on every focusable component.
    //
    // A text assertion because nothing else can hold it: the baselines capture the resting
    // state, axe does not evaluate focus indicators, and the keyboard lane is about where
    // focus goes. Mutating the colour back to transparent must fail here.
    const state = layerBody("terp.state");
    const at = state.indexOf("[data-terp]:focus-visible");
    expect(at).toBeGreaterThan(-1);
    const block = state.slice(state.indexOf("{", at) + 1, state.indexOf("}", at));
    expect(block, "the focus ring's outline must carry a colour").toContain(
      "outline: 2px solid var(--color-fg-accent)",
    );
    expect(block, "a transparent outline leaves only a translucent shadow").not.toContain(
      "solid transparent",
    );
    // And the halo stays, because it is what makes the indicator legible against a busy
    // surface rather than a hairline on it.
    expect(block).toContain("box-shadow: 0 0 0 3px var(--color-focus-ring)");
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

  it("has no rule left that needs an escalation, and says which file was the last", () => {
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
    // This list is empty, and keeping the test rather than deleting it is the point: the
    // direction it guards is the one that shipped a regression (a disabled Combobox painted
    // exactly like an enabled one, from dropping an escalation while an inline consumer
    // remained). It stays as the place a new escalation has to justify itself.
    //
    // AppShell was the last file, and it blocked five of the seven on its own: the shared
    // icon-button hover's background and colour (toggleStyle), the nav link's background and
    // colour (NAV_LINK_STYLE), and the reduced-motion override (three inline transitions, one
    // of them on an <aside> carrying no marker at all).
    const state = layerBody("terp.state");
    const stillInline: [string, string][] = [];
    for (const [rule, consumer] of stillInline) {
      const at = state.indexOf(rule);
      expect(at, `${rule} should still be declared`).toBeGreaterThan(-1);
      expect(
        state.slice(at, state.indexOf("}", at)),
        `${rule} must keep its escalation while ${consumer} is inline`,
      ).toContain("!important");
    }
    // The reduced-motion override no longer shouts either, and that one is a decision rather
    // than bookkeeping. Its three inline consumers are gone, so layer order is enough —
    // terp.motion sits above terp.base and terp.state. Retiring it also has a merit of its own:
    // the block sets `transition: none` for EVERY transition, including pure colour fades that
    // are not motion at all, so leaving it unoverridable was the over-broad choice. An app can
    // now narrow it from theme.css, which is exactly the power this phase exists to hand over.
    const motion = layerBody("terp.motion");
    expect(motion, "the reduced-motion override should still be declared").toContain(
      "transition: none",
    );
    expect(motion, "its last inline consumer migrated with AppShell").not.toContain("!important");
  });

  it("keeps the shared icon-button hover from impersonating a pressed toggle", () => {
    // This rule shouts, because AppShell's toggleStyle declares background and colour inline
    // on the shell's two header toggles and nothing but !important reaches a style attribute.
    // Its two values are byte-identical to the PRESSED look of the DataView toolbar's layout
    // toggles, which wear the same marker — so unguarded, hovering an inactive toggle paints it
    // exactly like the active one, and the toggle group's only job is to say which layout is
    // current.
    //
    // What makes that unrecoverable rather than merely wrong is the escalation. For important
    // declarations the layer order reverses and unlayered styles sort last, so no author rule
    // at any specificity — including an app's theme.css — can put the inactive colour back. The
    // fix is therefore a guard on the rule and not an override anywhere else.
    //
    // Invisible to all three lanes: the baselines capture the resting state, axe reads a static
    // tree, and the keyboard lane asserts where focus goes rather than what it paints.
    const state = layerBody("terp.state");
    const at = state.indexOf('[data-terp="iconbutton"]:hover');
    expect(at, "the shared icon-button hover should still be declared").toBeGreaterThan(-1);
    expect(
      state.slice(at, state.indexOf("{", at)),
      "an !important hover must not reach a pressed toggle",
    ).toContain(':not([aria-pressed="true"])');
    // And the precedent it copies, verbatim, so deleting either guard is one failure and not
    // two independent ones nobody connects.
    expect(
      state,
      "the tab precedent this guard is modelled on must stay in the sheet",
    ).toContain('[data-terp="tab"]:hover:not(:disabled):not([aria-selected="true"])');
  });

  it("keeps the shell declarations no lane can reach", () => {
    // Three groups, and every one of them was established by mutation rather than assumed.
    //
    // Two of the three have since GAINED a baseline, and the reason is worth keeping because
    // the earlier version of this comment said flatly that the screenshot lane could not reach
    // them: it could not, while the viewport was pinned at 1280 for every specimen. A
    // per-specimen `viewport` in the workbench is what changed, and what these two assertions
    // are now is belt rather than the sole gate.
    //
    // The sidebar's flex-shrink. At the pinned 1280 the row has room to spare, so deleting it
    // moves no baseline — measured, and still true. It bites above the mobile breakpoint and
    // below wide, and `app-shell-narrow` (820x900, with a DataView supplying the content
    // pressure a short paragraph does not) is that band: removing the declaration now repaints
    // 124,797 pixels there, in both themes, and leaves the other three shell specimens
    // untouched. A row under no pressure never asks a flex item whether it may shrink, which
    // is why the specimen needed the table and not just the narrower window.
    const base = layerBody("terp.base");
    const at = base.indexOf('[data-terp="appshell-sidebar"] {');
    expect(at, "the sidebar should have a base rule").toBeGreaterThan(-1);
    expect(
      base.slice(base.indexOf("{", at) + 1, base.indexOf("}", at)),
      "without this the rail squeezes instead of the content, between the breakpoint and wide",
    ).toContain("flex-shrink: 0");
    // The three z-index tokens the shell is the first reader of. Before this the family shipped
    // with --z-index-drawer read by nothing at all, while the one element that wanted it — this
    // drawer — hardcoded 50, and the token's only binding anywhere pointed at the popover level
    // instead. A hardcoded number here would move no baseline and read as correct.
    for (const [token, selector] of [
      ["--z-index-drawer", "the mobile drawer"],
      ["--z-index-backdrop", "the drawer's backdrop"],
      ["--z-index-sticky", "the sticky header"],
    ] as const) {
      expect(base, `${selector} must read ${token} rather than hardcoding its number`).toContain(
        `z-index: var(${token})`,
      );
    }
    // The shell's three geometry literals, same shape and the same reason. `15rem`, `4rem` and
    // `3rem` are now published tokens an app moves from its own unlayered `theme.css` with no
    // prop at all (ADR 0097 §1), and restating any of them as a number here would move no
    // baseline — the values are identical, which is what made the conversion provably
    // zero-diff — while quietly taking the knob away again. `tokens.guard.test.ts` holds the
    // other direction: a shell token nothing reads fails there.
    for (const [declaration, what] of [
      ["width: var(--shell-sidebar-width-expanded)", "the expanded sidebar"],
      ["width: var(--shell-sidebar-width-collapsed)", "the collapsed icon rail"],
      ["min-height: var(--shell-header-height)", "the sticky header's floor"],
    ] as const) {
      expect(base, `${what} must read its token rather than restating the length`).toContain(
        declaration,
      );
    }
    // And the content measure, which no structural check can reach through a marker: it is the
    // one shell rule keyed on a descendant of an attribute rather than on a marker of its own,
    // because the mechanism is deliberately NOT a new element (ADR 0097 §2). The `:not(header)`
    // is the whole band: the header keeps the page grid's full track while its siblings take
    // the measure.
    // Selector AND declaration read out of ONE rule body, not as two independent substrings
    // of the layer. Asserted separately, an empty measure rule plus the declaration moved onto
    // some other rule during a consolidation would satisfy both — and the only baseline that
    // moved would read as an intentional layout change.
    const measureRule =
      /\[data-terp="appshell"\]\[data-content-width="measured"\]\s*\n?\s*\[data-terp="page"\] > \*:not\(\[data-terp="page-header"\]\) \{([^}]*)\}/.exec(
        base,
      );
    expect(measureRule, "the content measure must be one rule keyed on the shell's attribute").not
      .toBeNull();
    const measureBody = measureRule![1]!;
    // WIDTH, not max-width, and this assertion is the gate on that. The selector weighs
    // (0,4,0), so as a max-width it outranks every component declaring a narrower one —
    // resource-list, admin-form, dialog and both text measures — and an admin-form inside a
    // measured shell computed 1280px instead of 512px. As a width it composes, because CSS
    // resolves max-width after width. Nothing renders differently for a child with no measure
    // of its own, which is why only a probe found it.
    expect(
      measureBody,
      "the measure must be a width, or it outranks every component's own narrower max-width",
    ).toContain("width: min(100%, var(--shell-content-max-width))");
    expect(
      base.includes("max-width: var(--shell-content-max-width)"),
      "as a max-width the measure would widen resource-list, admin-form, dialog and Text",
    ).toBe(false);
    // And the mobile half of the shell, where the three selectors below now differ from each
    // other and the difference is the interesting part. The BEHAVIOUR is covered throughout by
    // AppShell.test.tsx (focus containment, inert page, close-on-nav) with a stubbed
    // matchMedia; what varies is the geometry.
    //
    // `appshell-main`'s tightened padding is painted: `app-shell-mobile` renders at 420x900,
    // and moving that padding one step to the desktop value repaints 1,309 pixels there in both
    // themes and nothing else.
    //
    // The other two DID wait for a door, and it arrived: `defaultDrawerOpen` plus the
    // `app-shell-drawer-open` specimen (420x900, overlay) paint the drawer's own geometry and
    // its backdrop for the first time. So this loop is belt for all three now rather than the
    // sole gate for two of them — the message below still says "no baseline can hold it", which
    // was true when it was written and is not any more.
    for (const selector of [
      '[data-terp="appshell"][data-variant="mobile"] [data-terp="appshell-sidebar"]',
      '[data-terp="appshell-backdrop"]',
    ]) {
      expect(
        declaresRuleFor(base, selector),
        `${selector} is mobile-only; app-shell-mobile and app-shell-drawer-open are the only ` +
          "pictures of it",
      ).toBe(true);
    }
    // The gutter's phone value is ONE rule where the header and main used to carry a mobile
    // override each, and it is asserted against the UNLAYERED prelude rather than terp.base
    // because that is where it has to live: tokens.css declares --shell-gutter on :root and
    // ships as an extracted <link> ahead of this sheet, so a layered copy would lose to it
    // in a production build while winning in dev — the exposure the density remap beside it
    // records. app-shell-mobile is still its only picture.
    const prelude = css.slice(0, css.indexOf("@layer terp.reset {"));
    expect(
      declaresRuleFor(prelude, '[data-terp="appshell"][data-variant="mobile"]'),
      "the phone gutter must be remapped in the unlayered prelude, or tokens.css outranks it",
    ).toBe(true);
    expect(
      declaresRuleFor(layerBody("terp.base"), '[data-terp="appshell"][data-variant="mobile"]'),
      "a layered copy of the remap loses to tokens.css in a production build",
    ).toBe(false);
    // That the remap actually TIGHTENS is asserted in tokens.guard.test.ts, not here: it
    // compares the remapped value against the one tokens.css publishes, and this file runs
    // in jsdom where import.meta.url is not a file URL. The guard file already reads the
    // token sheet for exactly this kind of claim.
    const remap = /\[data-terp="appshell"\]\[data-variant="mobile"\] \{([^}]*)\}/.exec(prelude);
    expect(remap, "the phone remap should be one rule").not.toBeNull();
    expect(
      remap![1]!,
      "the remap must move --shell-gutter, not something else",
    ).toContain("--shell-gutter:");
  });

  it("keeps the content column's gutter one measure", () => {
    // The bug this exists for: appshell-header carried padding-inline var(--space-4) while
    // appshell-main and appshell-footer carried var(--space-6), so the breadcrumb trail —
    // the first thing inside main on every routed view — sat 0.5rem right of the header's
    // own toggle. Boxes stack in that column and the topmost content in each starts at its
    // inline padding edge, so their gutters are ONE measure and any two disagreeing is the
    // defect.
    //
    // No baseline caught it, and could not have: every app-shell specimen recorded the
    // misalignment as its expected picture from the first run. A screenshot says "this is
    // what it looks like", never "these two edges are meant to be the same edge".
    //
    // It is now a published token with one remap rather than a literal repeated per box,
    // which stopped being a preference when the page band arrived: the band reads the same
    // measure as a NEGATIVE margin to reach the column's edge, so a literal would have had
    // to agree in sign across rules three hundred lines apart.
    const base = layerBody("terp.base");
    const bodyFor = (selector: string): string => {
      for (const match of base.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
        const selectors = match[1].split(",").map((part) => part.trim().replace(/\s+/g, " "));
        if (selectors.includes(selector)) return match[2];
      }
      throw new Error(`the sheet declares no rule for exactly ${selector}`);
    };
    /**
     * The inline padding a rule sets, from either the shorthand's second value or an
     * explicit `padding-inline`. Both spellings are in play on purpose: the header and the
     * footer set block and inline together, main sets one value for all four sides.
     */
    const gutterOf = (selector: string): string => {
      const declarations = bodyFor(selector);
      const inline = /padding-inline:\s*([^;]+);/.exec(declarations);
      if (inline) return inline[1]!.trim();
      const shorthand = /padding:\s*([^;]+);/.exec(declarations);
      if (!shorthand) throw new Error(`${selector} declares no padding at all`);
      const parts = shorthand[1]!.trim().split(/\s+(?![^(]*\))/);
      // One value pads every side, two are block-then-inline. Nothing in this column writes
      // the three- or four-value form, and a rule that started to would land here rather
      // than being read wrong.
      if (parts.length === 1) return parts[0]!;
      if (parts.length === 2) return parts[1]!;
      throw new Error(
        `${selector} writes a ${parts.length}-value padding this reader cannot split`,
      );
    };

    const column = [
      '[data-terp="appshell-header"]',
      '[data-terp="appshell-main"]',
      '[data-terp="appshell-footer"]',
    ].map((selector) => [selector, gutterOf(selector)] as const);
    expect(
      new Set(column.map(([, gutter]) => gutter)).size,
      `the column's boxes must share one inline gutter, got ${column
        .map(([selector, gutter]) => `${selector} = ${gutter}`)
        .join(", ")}`,
    ).toBe(1);
    // And it is the published token, not a spacing step restated three times. A literal here
    // is the exact state the defect was in, and a literal passes the check above.
    expect(column[0]![1], "the gutter must read the shell's own token").toBe(
      "var(--shell-gutter)",
    );

    // The band splits in two, and which half is gated on the shell is the whole point.
    //
    // CHROME is ungated: a bordered row at the app header's height is correct wherever Page
    // renders, the workbench's specimen cards and these tests included. It used to sit in the
    // shell-gated rule while the comment beside it claimed the opposite, so the three
    // page-header specimens pictured a plain flex row that the prose called chrome.
    const chrome = bodyFor(
      '[data-terp="page"]:not([data-measure="narrow"]) > [data-terp="page-header"]',
    );
    // Same height as the app header, by reading the header's own token rather than restating
    // 3rem — and border-box, or the two are a padding apart and the claim is off by 1rem.
    expect(chrome, "the band takes the app header's height").toContain(
      "min-height: var(--shell-header-height)",
    );
    expect(chrome, "without border-box the floor excludes the padding").toContain(
      "box-sizing: border-box",
    );
    expect(chrome, "the band is what separates chrome from content").toContain(
      "border-block-end: 1px solid var(--color-neutral-200)",
    );
    // The block padding, and it has to be the same VALUE in both chrome rows rather than the
    // same intention. A min-height is only a height while nothing legal can beat it, and
    // var(--space-2) did not clear that bar: a 2.25rem control plus 8px of padding plus the
    // 1px border is 53px against a floor of 48, so the app header (which always carries its
    // toggle) was 53px, a band with an action button was 53px, and a band with only a title
    // was 48px — the one row whose whole promise is that it matches the header above it,
    // changing height per page. Measured in the workbench before it was cut, and the
    // resolved heights are pinned there too, in the computed lane; what belongs here is that
    // neither row can move its padding without the other.
    expect(chrome, "the band's block padding is the app header's").toContain(
      "padding-block: var(--space-1)",
    );
    expect(
      bodyFor('[data-terp="appshell-header"]'),
      "both chrome rows spend the same block padding under the floor they share",
    ).toContain("padding: var(--space-1) var(--shell-gutter)");
    expect(
      /padding-inline|padding:/.test(chrome),
      "an inline pad with no bleed would inset the band from the body beneath it",
    ).toBe(false);

    // THE BLEED is gated, because the negative-margin idiom is only correct against a box
    // that pads by exactly this token. ADR 0097 section 2 kept "it works with no shell above
    // it at all" as a property of the mechanism, and this keying is what keeps it. The sign
    // agreement is a fact about two declarations in ONE rule rather than between rules.
    const bleed = bodyFor(
      '[data-terp="appshell-main"] > [data-terp="page"]:not([data-measure="narrow"])'
        + ' > [data-terp="page-header"]',
    );
    expect(bleed, "the band must bleed by negating the gutter it pads by").toContain(
      "margin: calc(-1 * var(--shell-gutter)) calc(-1 * var(--shell-gutter)) 0",
    );
    expect(bleed, "the band must restore the gutter as its own padding").toContain(
      "padding-inline: var(--shell-gutter)",
    );
    expect(
      bleed.includes("margin") && !/margin:[^;]*calc\(-1/.test(bleed),
      "a bleed whose margin is not negative escapes nothing",
    ).toBe(false);
  });

  it("keeps a row's own colour out of the hover wash's reach", () => {
    // A row's tone and its selection tint paint on the tr; the table's hover wash paints on
    // the td, and a cell background paints ABOVE its row's. So an unguarded wash repaints a
    // selected row over its tint and a danger row over its tone: the affordance overwrites
    // the data. The selection half only became visible when --color-interactive-selected
    // split away from --color-neutral-50 — while the two spelled one value the collision was
    // pixel-identical — and the tone half was live before that. Neither is picturable: no
    // specimen renders a hovered row, so this assertion is the only gate.
    // terp.state, not terp.base: a hover is a state, and that is where the sheet keeps it.
    const state = layerBody("terp.state");
    const hover = /\[data-terp="dataview-table"\][^{]*:hover td \{/.exec(state);
    expect(hover, "the table should declare a hover wash").not.toBeNull();
    const selector = state.slice(
      state.lastIndexOf("}", hover!.index) + 1,
      hover!.index + hover![0].length,
    );
    for (const guard of ['[data-tone]', '[data-selected="true"]']) {
      expect(
        selector,
        `the hover wash must exclude :not(${guard}), or it repaints what the row is telling you`,
      ).toContain(`:not(${guard})`);
    }
  });

  it("keeps the hub-card declarations the lanes cannot explain", () => {
    // Both of these were found by mutation: deleting either moves no baseline, and neither is
    // dead. This is their only gate.
    //
    // The placeholder rows. A non-breaking space paints nothing, so a hidden placeholder and a
    // visible one are pixel-identical — measured at width 557 and height 89 either way. The
    // declaration exists for the accessibility tree: visibility: hidden removes the text, and
    // without it a screen reader announces a blank row on every card missing a description or a
    // stat. It must therefore stay `visibility` and never become `opacity`, which hides the text
    // from sight while leaving it announced.
    const base = layerBody("terp.base");
    const at = base.indexOf('[data-terp="hubcard-description"][data-empty="true"]');
    expect(at, "the placeholder rule should be declared").toBeGreaterThan(-1);
    const block = base.slice(base.indexOf("{", at) + 1, base.indexOf("}", at));
    expect(block, "a placeholder row must leave the accessibility tree, not just the page").toContain(
      "visibility: hidden",
    );
    expect(block, "opacity would hide the text from sight and leave it announced").not.toContain(
      "opacity",
    );
    // The card's height chain, and this assertion had to be corrected once: the link's
    // display: block and height: 100% look like the middle rung and are not. Measured in a row
    // stretched past the body's 10rem floor, forcing that anchor inline changes nothing —
    // percentage heights resolve against the nearest block container and skip inline boxes, so
    // the body reaches past the anchor to the <li> the grid stretched. Nor does removing the
    // grid's align-items: stretch (grid's default anyway), its grid-auto-rows: 1fr, or the
    // card's own height: 100%.
    //
    // Exactly one declaration equalises two cards, and this is it. Removing it in that same
    // stretched row drops the bare card to 160 while its neighbour stays at 189 — which
    // hub-card-bare now catches, and catches only because its full card is deliberately long
    // enough to set the row height. Kept here as well as in the baseline, because the baseline
    // cannot say WHY the two cards match.
    const body = base.indexOf('[data-terp="hubcard-body"]');
    expect(body, "the hub-card body rule should be declared").toBeGreaterThan(-1);
    expect(
      base.slice(base.indexOf("{", body) + 1, base.indexOf("}", body)),
      "the body's percentage height is the only thing equalising two cards in a row",
    ).toContain("height: 100%");
  });

  it("puts the DataView's surface on the full variant's TABLE, not on the root or the marker", () => {
    // Both values of data-variant are stamped and only one has a rule, which is what keeps
    // the embedded variant a bare grid. The alternative — surface on the marker, un-declared
    // under [data-variant="embedded"] — needs background: transparent, border: 0 and
    // border-radius: 0, the un-declaring shape ADR 0094 exists to avoid.
    //
    // dataview-embedded is the negative evidence this rests on: deleting the full-variant
    // rule must move the full-variant baselines and leave that one untouched.
    //
    // The OWNER changed and the guarantee did not. The surface used to sit on the root, which
    // made one card of the toolbar, the table and the pagination, divided by internal borders
    // — and left the table's cells flush against the outer frame. It now sits on whatever
    // occupies the table's slot, so the table is the object and the controls above and below
    // it float on the page. Still keyed on the variant, for the reason above.
    const base = layerBody("terp.base");
    expect(declaresRuleFor(base, '[data-terp="dataview"]'), "the root needs a display").toBe(true);
    expect(
      declaresRuleFor(base, '[data-terp="dataview"][data-variant="full"] > [data-terp="dataview-scroll"]'),
      "the surface belongs to the full variant's table slot",
    ).toBe(true);
    expect(
      declaresRuleFor(base, '[data-terp="dataview"][data-variant="full"]'),
      "the root must NOT carry a surface — that is the card this change removed",
    ).toBe(false);
    expect(
      base,
      "un-declaring a surface under the embedded variant is the shape ADR 0094 avoids",
    ).not.toContain('[data-variant="embedded"]');
    // display: grid is asserted HERE because nothing else can: forcing the root to block
    // leaves every measured dimension identical on dataview-wide, dataview-full and
    // dataview-embedded — the three children are full-width block boxes with no margins, which
    // a single-column grid and a block container stack the same way — so deleting it moves no
    // baseline. This assertion is the only thing standing between that declaration and a
    // silent removal.
    //
    // It matters in one direction: under grid, a wide table without the scroll wrapper's
    // overflow-x widens the whole DataView, because a grid item's automatic minimum size is
    // content-based unless its overflow is not visible. The two are coupled, and the second
    // half is what dataview-wide catches.
    const at = base.indexOf('[data-terp="dataview"]');
    expect(base.slice(base.indexOf("{", at) + 1, base.indexOf("}", at))).toContain("display: grid");
    expect(declaresRuleFor(base, '[data-terp="dataview-scroll"]'), "the pair's other half").toBe(
      true,
    );
  });

  it("keeps the toolbar FLOATING — no surface, no divider, and still no ink", () => {
    // This assertion reversed, and the reversal is the change: the band used to declare
    // neutral-0 and two top radii because it was the top third of a card, and nothing else
    // kept the selection colour inside the root's rounded frame. There is no card now. A
    // background on a strip that sits on the page canvas paints a rectangle the design does
    // not have, and a border under it draws a line across nothing.
    //
    // The radii went with the card for the same reason: there is no rounded frame above the
    // toolbar to stay inside. Selection mode keeps a fill — it marks a MODE and losing that
    // makes selection invisible — but as a surface of its own, with its own padding and
    // radius, asserted below.
    //
    // NO colour survives unchanged, and it is the invariant with the sharpest edge: two of
    // this element's direct children are arbitrary caller slots (`children` and `trailing`),
    // so a muted ink here would inherit into app-authored filter controls — a silent restyle
    // of app DOM, which is what the styling migration exists to stop the framework doing.
    const base = layerBody("terp.base");
    const at = base.indexOf('[data-terp="dataview-toolbar"]');
    expect(at, "the toolbar band should have a base rule").toBeGreaterThan(-1);
    const block = base.slice(base.indexOf("{", at) + 1, base.indexOf("}", at));
    expect(block, "a floating strip paints no surface of its own").not.toContain("background:");
    expect(block, "a divider under a floating strip is a line across nothing").not.toContain(
      "border-block-end:",
    );
    expect(
      /(^|;)\s*color:/.test(block),
      "a colour here inherits into the caller's filter slot and trailing slot",
    ).toBe(false);
    // Selection mode is a resting surface, so it belongs in terp.base and wins at (0,2,0)
    // against the band's (0,1,0) — on specificity, with no :not() and no source-order
    // dependency. In terp.state it would beat the focus ring's layer for no reason.
    expect(
      declaresRuleFor(base, '[data-terp="dataview-toolbar"][data-variant="selection"]'),
      "selection mode must be a base rule of its own",
    ).toBe(true);
    expect(
      layerBody("terp.state"),
      "selection mode is a resting surface, not an interaction state",
    ).not.toContain('[data-variant="selection"]');
    // The band used to read --density-cell-pad-x for its INLINE padding, so a compact view's
    // band lined up with its first cell. That alignment target is gone with the card: the
    // toolbar now aligns with the table's outer frame, whose position does not move with
    // density, so inline padding here would push the controls off it. Block padding stays on
    // the spacing scale — vertical rhythm was never the density question.
    expect(block, "the band's block padding stays on the spacing scale").toContain(
      "padding-block: var(--space-2)",
    );
    expect(
      /padding-inline|padding:/.test(block),
      "inline padding would push the controls off the table frame they now align to",
    ).toBe(false);
    // Selection mode is the exception and declares its own inline padding, because there it
    // IS a surface and its fill needs to clear its text.
    const selectionAt = base.indexOf('[data-terp="dataview-toolbar"][data-variant="selection"]');
    const selectionBlock = base.slice(
      base.indexOf("{", selectionAt) + 1,
      base.indexOf("}", selectionAt),
    );
    expect(selectionBlock, "the selection surface reads density for its own inset").toContain(
      "padding-inline: var(--density-cell-pad-x)",
    );
  });

  it("signals the active layout with more than a colour", () => {
    // Two icon-only controls whose entire job is to say which layout is current, so which one
    // is pressed cannot be carried by ink alone (SC 1.4.1) and its indicator has to clear 3:1
    // (SC 1.4.11). Measured over the manifest's per-theme values: the neutral-100 fill against
    // the band's transparent is 1.09-1.16 across the five themes, nowhere near it; the accent
    // border is 4.95 at worst against its own fill and 5.75 at worst against the band.
    //
    // A text assertion because nothing else can hold it. The baselines DO see the border, but
    // they cannot say why it is there — re-recording them is one keystroke, and the reason this
    // rule carries a border rather than only a wash is exactly what a re-record erases.
    //
    // Keyed on aria-pressed rather than a data attribute duplicating it — the
    // [data-terp="tab"][aria-selected="true"] precedent — and the reuse is safe in the strong
    // sense that case defines: DataViewToolbar is the sole author of that attribute on these
    // two elements, setting it from its own layout prop, and no router, wrapper or caller can
    // reach them.
    //
    // Deliberately NOT a box-shadow: [data-terp]:focus-visible sets box-shadow in this same
    // layer at (0,2,0) against this rule's (0,3,0), so an inset shadow here would win and a
    // focused active toggle would lose its focus ring.
    const state = layerBody("terp.state");
    const selector =
      '[data-terp="dataview-toolbar-layout"] > [data-terp="iconbutton"][aria-pressed="true"]';
    expect(declaresRuleFor(state, selector), `${selector} must be declared`).toBe(true);
    const at = state.indexOf(selector);
    const block = state.slice(state.indexOf("{", at) + 1, state.indexOf("}", at));
    expect(block, "pressed must carry a non-colour signal, not a wash alone").toContain(
      "border-color: var(--color-fg-accent)",
    );
    expect(
      block,
      "an inset box-shadow here outranks the shared focus ring in the same layer",
    ).not.toContain("box-shadow");
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
    // BOTH layers. This read only terp.base, so a transition declared in terp.state — where
    // every hover, focus and selected treatment lives — was audited by nothing at all. The one
    // that exists there today passed only because its selector happens to be in the explicit
    // list above, which is luck rather than coverage.
    //
    // And the "marked" heuristic needs the trailing pseudo stripped before it is applied.
    // `\s[a-z]+$` asks whether the selector ends in a bare element name preceded by whitespace,
    // but `[data-terp="card"] span:hover` ends in `:hover` — the character before the final run
    // is a colon, not a space — so the test scored it as marked and waved it through. Reduced
    // motion cannot reach that rule: terp.motion is the last layer and beats any earlier one on
    // the elements its selectors MATCH, and its list matches marked elements and four named
    // descendants. A transition on any other descendant simply escapes.
    const transitionRules = [layerBody("terp.base"), layerBody("terp.state")].flatMap((body) => [
      ...body.matchAll(/([^{}]+)\{([^{}]*transition:[^{}]*)\}/g),
    ]);
    expect(transitionRules.length, "no transition rules were scanned at all").toBeGreaterThan(0);
    for (const match of transitionRules) {
      const selector = match[1].trim().replace(/\s+/g, " ");
      // Strip trailing pseudo-classes / pseudo-elements, so the bare-element test sees the
      // element the selector actually ends on.
      const withoutPseudo = selector.replace(/(::?[a-z-]+(\([^)]*\))?)+$/, "");
      const marked = withoutPseudo.includes("[data-terp") && !/\s[a-z]+$/.test(withoutPseudo);
      expect(
        marked || motion.includes(selector),
        `${selector} declares a transition but reduced motion cannot reach it`,
      ).toBe(true);
    }
  });

  it("times every transition off the published motion scale, never a literal", () => {
    // The scale shipped in 2a and was read by nothing: this sheet wrote `150ms ease`
    // 28 times and `100ms ease` once across 16 declarations, and read a motion token
    // zero times — so a Studio editor built from the manifest would have offered four
    // duration controls that moved nothing. Wiring them was inert by construction:
    // --motion-duration-fast IS 150ms, --motion-duration-instant IS 100ms and
    // --motion-easing-standard IS ease, so every literal mapped onto a token pair.
    //
    // This gate has to be structural, and that is the whole reason it exists here
    // rather than in a baseline. The screenshot lane runs with
    // `animations: "disabled"`, so a duration is invisible to it: a wrong value — or
    // literal number 30 — would move no pixel and nothing would say so.
    //
    // Scoped to `transition` on purpose. The spinner's `animation: terp-spin 0.8s` is
    // a rotation period rather than an interaction step and the scale tops out at
    // 400ms, so there is no token for it to name.
    const declarations = [...css.matchAll(/transition:\s*([^;]+);/g)].map((match) => match[1]!);
    expect(declarations.length).toBeGreaterThan(10);
    expect(
      declarations.filter((value) => /\d+m?s\b/.test(value)),
      "a transition's duration belongs on the published motion scale, not in the rule",
    ).toEqual([]);
  });

  it("puts the responsive Stack rules after the ones they override", () => {
    // A stack with direction { narrow: "row", wide: "column" } carries BOTH
    // data-direction="row" and data-direction-wide="column", and the two selectors weigh the
    // same (0,2,0) — so nothing but source order decides which applies above the cutover.
    // Backwards, the narrow value renders at every width, which looks exactly like the prop
    // not working rather than like a cascade mistake.
    //
    // The same tie the focus ring and the loading cursor both turned on, and the third time
    // it has mattered in this sheet: equal specificity in one layer is settled by position,
    // and position is the one thing a reader cannot see from the rule.
    const base = layerBody("terp.base");
    const wideAt = base.indexOf("@media not all and (max-width: 768px)");
    expect(wideAt, "the wide half of the responsive props should be in terp.base").toBeGreaterThan(
      -1,
    );
    for (const selector of [
      '[data-terp="stack"][data-direction="row"]',
      '[data-terp="stack"][data-gap="8"]',
    ]) {
      const at = base.indexOf(selector);
      expect(at, `${selector} should exist`).toBeGreaterThan(-1);
      expect(at, `${selector} must be declared before the wide block that overrides it`).toBeLessThan(
        wideAt,
      );
    }
  });

  it("puts the DetailList gap rules after the layout rules they override", () => {
    // The same tie as the responsive Stack rules above, on a different component.
    // [data-terp="detail-list"][data-gap="3"] and [data-terp="detail-list"][data-layout="aligned"]
    // both weigh (0,2,0), so nothing but source order decides which row-gap a list carrying both
    // attributes renders. Backwards, the layout default wins and the prop silently does nothing
    // — which reads as a broken prop rather than as a misplaced rule, and no baseline can say
    // which of the two it is looking at.
    const base = layerBody("terp.base");
    const layoutAt = base.indexOf('[data-terp="detail-list"][data-layout="stacked"] {');
    expect(layoutAt, "the layouts' default row gap should have a rule").toBeGreaterThan(-1);
    for (const token of [0, 1, 2, 3, 4, 6, 8]) {
      const at = base.indexOf(`[data-terp="detail-list"][data-gap="${token}"]`);
      expect(at, `detail-list has no rule for gap ${token}`).toBeGreaterThan(-1);
      expect(at, `gap ${token} must be declared after the layout default it overrides`).toBeGreaterThan(
        layoutAt,
      );
    }
  });

  it("wins DetailList's wide rules on specificity, not on where they sit", () => {
    // The mirror of the test above, and the opposite hazard. The sheet has exactly ONE
    // wide-viewport block and DetailList's base rules are declared roughly a hundred lines
    // BELOW it, so source order settles these the wrong way round and cannot be relied on.
    // Specificity is what makes them apply, which is precisely how splitpage-panes already
    // works from this same block — and it is invisible to a reader of either rule.
    //
    // Asserted as a property rather than as a list of pixel values: every selector in here
    // carries the marker plus at least one attribute, so it out-weighs the (0,1,0) base rule
    // it overrides. These selectors are attribute-only, so counting `[` counts specificity's
    // b-component exactly.
    const base = layerBody("terp.base");
    const wideAt = base.indexOf("@media not all and (max-width: 768px)");
    expect(wideAt, "the wide block should be in terp.base").toBeGreaterThan(-1);
    let depth = 0;
    let end = base.length;
    for (let i = base.indexOf("{", wideAt); i < base.length; i += 1) {
      if (base[i] === "{") depth += 1;
      else if (base[i] === "}") {
        depth -= 1;
        if (depth === 0) {
          end = i;
          break;
        }
      }
    }
    const wide = base.slice(wideAt, end);
    for (const selector of [
      '[data-terp="detail-list"][data-columns="2"]',
      '[data-terp="detail-list"][data-layout="aligned"]',
      '[data-terp="detail-list"][data-layout="aligned"][data-columns="2"]',
      '[data-terp="detail-list"][data-layout="aligned"] [data-terp="detail-list-row"]',
      // The full row's un-contents-ing, and the group's subgrid: both are properties of the
      // shared column, so both belong to the width at which there IS one.
      '[data-terp="detail-list"][data-layout="aligned"] [data-terp="detail-list-row"][data-full="true"]',
      '[data-terp="detail-list-group"] > [data-terp="detail-list"][data-layout="aligned"]:not([data-columns])',
    ]) {
      expect(
        declaresRuleFor(wide, selector),
        `${selector} belongs inside the wide block — narrow is one column`,
      ).toBe(true);
      expect(
        (selector.match(/\[/g) ?? []).length,
        `${selector} must out-specify the base rule it overrides, which is declared later`,
      ).toBeGreaterThan(1);
    }
    // And the base rules really are declared after it, or none of the above is load-bearing.
    for (const selector of ['[data-terp="detail-list"] {', '[data-terp="detail-list-row"] {']) {
      expect(base.indexOf(selector), `${selector} should exist`).toBeGreaterThan(-1);
      expect(
        base.indexOf(selector),
        `${selector} is declared before the wide block, so order — not specificity — would settle it`,
      ).toBeGreaterThan(wideAt);
    }
    // The one property the wide block must NOT declare: row-gap belongs to the gap prop, whose
    // roll-call weighs the same (0,2,0) and is declared later on purpose. A row-gap in here
    // would out-order it and the prop would stop working above the cutover only.
    expect(wide, "row-gap in the wide block would silently disable the gap prop").not.toContain(
      "row-gap",
    );
  });

  it("mutes the DetailList label in both non-inline layouts, and in neither sentence", () => {
    // The defect this closes was a divergence: `stacked` muted its term and `aligned` never
    // got the rule, so an aligned label rendered at the VALUE's size, weight and ink — 16px,
    // 500, near-black — and a card of five labelled values read as a wall of bold text with
    // nothing saying which half of a pair to read first.
    //
    // `inline` is deliberately excluded, and that is the half worth pinning: there the term is
    // part of a sentence (the colon comes from a ::after) and muting half a sentence is a
    // different defect. So this asserts the selector list exactly, in both directions.
    // Anchored on the RULES rather than on the section comment, because `css` above has its
    // comments stripped — prose must not satisfy a structural assertion, so prose cannot
    // delimit one either.
    const base = layerBody("terp.base");
    const muting = [...base.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .map((match) => ({
        selectors: match[1].split(",").map((part) => part.trim().replace(/\s+/g, " ")),
        body: match[2],
      }))
      .filter(
        (rule) =>
          rule.selectors.some((selector) => selector.includes('[data-terp="detail-list-term"]')) &&
          rule.body.includes("--color-fg-muted"),
      );
    expect(muting, "one shared rule mutes the label, not one per layout").toHaveLength(1);
    expect(muting[0]!.selectors).toEqual([
      '[data-terp="detail-list"][data-layout="aligned"] [data-terp="detail-list-term"]',
      '[data-terp="detail-list"][data-layout="stacked"] [data-terp="detail-list-term"]',
    ]);
    expect(muting[0]!.body).toContain("var(--font-size-xs)");
    expect(muting[0]!.body).toContain("var(--font-weight-normal)");
    // And the base term rule — the one the inline layout renders — carries no colour of its own.
    const termAt = base.indexOf('[data-terp="detail-list-term"] {');
    expect(termAt, "the base term rule should exist").toBeGreaterThan(-1);
    expect(base.slice(termAt, base.indexOf("}", termAt))).not.toContain("color:");
  });

  it("keeps a Card's actions slot on the title's line, description or not", () => {
    // The measured inconsistency: `actions` is documented as a header-row slot and delivered
    // one only while `description` was unset. The heading declared min-width: 0 alone, so it
    // computed flex: 0 1 auto and its hypothetical main size was the max-content width of a
    // block holding a title AND a sentence — and flex breaks lines on hypothetical main sizes
    // BEFORE it shrinks anything, so with the header's flex-wrap the heading took the line and
    // the control wrapped underneath. 103px against 48px for the same component, one prop apart.
    //
    // A base size of 0 is what makes both fit by construction. min-width: 0 stays for the other
    // half: a flex item's automatic minimum is its content's, so a long unbreakable title would
    // otherwise refuse to shrink past it. Both are asserted, because dropping either brings a
    // different half of the bug back.
    const base = layerBody("terp.base");
    const headingAt = base.indexOf('[data-terp="card-heading"] {');
    expect(headingAt, "card-heading should have a base rule").toBeGreaterThan(-1);
    const heading = base.slice(headingAt, base.indexOf("}", headingAt));
    expect(heading, "a content-sized heading wraps the actions slot onto its own line").toContain(
      "flex: 1 1 0",
    );
    expect(heading, "min-width: 0 is what lets an unbreakable title shrink").toContain(
      "min-width: 0",
    );
    // The conditional half. `center` is right for a title alone — the slot is a control, so its
    // box is taller than one line box — and wrong the moment a description makes the heading a
    // block, where it floats the control in the middle instead of beside the title.
    expect(
      declaresRuleFor(base, '[data-terp="card-header"]:has([data-terp="card-description"])'),
      "the header's alignment must depend on whether there is a description",
    ).toBe(true);
    const conditionalAt = base.indexOf(
      '[data-terp="card-header"]:has([data-terp="card-description"])',
    );
    expect(base.slice(conditionalAt, base.indexOf("}", conditionalAt))).toContain(
      "align-items: start",
    );
    // And the base rule still centres, or the title rides above the control in the common case.
    const headerAt = base.indexOf('[data-terp="card-header"] {');
    expect(base.slice(headerAt, base.indexOf("}", headerAt))).toContain("align-items: center");
  });

  it("gives the breadcrumb trail one line box, leaf included", () => {
    // The trail is a row of items that get CENTRED, so two line heights in it are two
    // baselines. The leaf declared 1.3 while its ancestors inherited `normal`: measured at
    // font-size-sm, a 19.00px ancestor line box against an 18.19px leaf, which left the
    // page's own title 0.59px above the crumb it hangs off with the chevron centred on a
    // third line. One declaration on the trail, inherited by every crumb and by the h1, is
    // what makes the row share a baseline.
    //
    // The published step rather than a bare literal, and that is the second half of the fix
    // rather than house style: `normal` is the FONT's metric, so the mismatch was as big as
    // the app's typeface said it was, and an app on a webfont with taller natural leading got
    // a worse one than the system stack this was measured in.
    const base = layerBody("terp.base");
    const trail = base.slice(base.indexOf('[data-terp="breadcrumbs"] {'));
    expect(
      trail.slice(0, trail.indexOf("}")),
      "the trail declares the line box every crumb shares",
    ).toContain("line-height: var(--font-line-height-snug)");
    const leafAt = base.indexOf('[data-terp="page-title"] {');
    expect(leafAt, "the trail's leaf should have a rule").toBeGreaterThan(-1);
    expect(
      base.slice(leafAt, base.indexOf("}", leafAt)),
      "the leaf takes the trail's line box; a second value here is the misalignment",
    ).not.toContain("line-height");
  });

  it("spans a full row across every track, and makes it a box that can", () => {
    // Two halves, and the second is the one that is easy to miss: a display: contents box
    // generates no box, so grid-column on it is DROPPED and the span silently does not happen.
    // The aligned row is a contents box above the cutover, so the full row has to become a
    // block again there — which also gives it the label-above-value reading, the same pair's
    // narrow shape.
    const base = layerBody("terp.base");
    // Anchored on the newline, because the wide block's rule ENDS with the same selector and
    // an unanchored search finds that one first — which is how this test first passed while
    // reading the wrong rule.
    const spanAt = base.indexOf('\n[data-terp="detail-list-row"][data-full="true"] {');
    expect(spanAt, "the full row should have a span rule").toBeGreaterThan(-1);
    expect(
      base.slice(spanAt, base.indexOf("}", spanAt)),
      "1 / -1, so the row need not know how many tracks the list has",
    ).toContain("grid-column: 1 / -1");
    const unContentsAt = base.indexOf(
      '[data-terp="detail-list"][data-layout="aligned"] [data-terp="detail-list-row"][data-full="true"] {',
    );
    expect(unContentsAt, "the aligned full row should be un-contents-ed").toBeGreaterThan(-1);
    expect(base.slice(unContentsAt, base.indexOf("}", unContentsAt))).toContain("display: block");
  });

  it("floors both tracks of an auto pair, and caps each at a share of the container", () => {
    // The two failures this rule is shaped by, both measured rather than reasoned:
    //
    // A ZERO FLOOR makes an auto-fit repetition count unbounded — 35 pair repetitions with 31
    // collapsed to 0px, every pair on one row — so `auto` is the one place in this component
    // where a track may not be floored at zero. Hence a rem floor per track.
    //
    // A 100% CAP IS NOT ENOUGH FOR A PAIR. Grid's floor is min(16rem, 100%) because one track
    // wider than its container overflows it; two tracks at 100% each can sum to 200%, and the
    // list scrolled sideways in a narrow panel. The percentage shares are what keep one pair
    // inside one container, so they must stay strictly under 100% between them.
    const base = layerBody("terp.base");
    const at = base.indexOf('[data-terp="detail-list"][data-layout="aligned"][data-columns="auto"] {');
    expect(at, "aligned auto should have its own track list").toBeGreaterThan(-1);
    const body = base.slice(at, base.indexOf("}", at));
    const floors = [...body.matchAll(/min\((\d+)rem, (\d+)%\)/g)].map((match) => ({
      rem: Number(match[1]),
      share: Number(match[2]),
    }));
    expect(floors, "both tracks of the pair carry a floor").toHaveLength(2);
    expect(
      floors.every((floor) => floor.rem > 0),
      "a zero floor makes the repetition count unbounded",
    ).toBe(true);
    expect(
      floors.reduce((sum, floor) => sum + floor.share, 0),
      "the shares must leave room for the gap, or one pair overflows its container",
    ).toBeLessThan(100);
    // The layouts with no label column repeat ONE track, and at Grid's own floor, so a stacked
    // auto list and a grid of cards break at the same width by construction.
    const plainAt = base.indexOf('[data-terp="detail-list"][data-columns="auto"] {');
    expect(plainAt, "auto should have a no-label-column track list too").toBeGreaterThan(-1);
    expect(base.slice(plainAt, base.indexOf("}", plainAt))).toContain(
      "repeat(auto-fit, minmax(min(16rem, 100%), 1fr))",
    );
    // And the shared column for an auto list is declared at EVERY width, unlike the closed
    // counts': the cutover is what `auto` exists to not need.
    const rowAt = base.indexOf(
      '[data-terp="detail-list"][data-layout="aligned"][data-columns="auto"]\n  [data-terp="detail-list-row"]',
    );
    expect(rowAt, "the auto row rule should exist").toBeGreaterThan(-1);
    const wideAt = base.indexOf("@media not all and (max-width: 768px)");
    expect(
      rowAt > wideAt && rowAt > base.indexOf("}", base.indexOf('[data-terp="detail-list"] {')),
      "the auto row rule belongs outside the wide block, at every width",
    ).toBe(true);
  });

  it("gives the group the aligned track list verbatim, gutter included", () => {
    // A subgrid takes the PARENT's tracks and the parent's gutter along the axis it subgrids,
    // so these two declarations are one measure written twice — and a group whose tracks
    // disagreed with aligned's would line its lists up with each other and with nothing else
    // on the card. Compared rather than described, because the failure is invisible until two
    // cards are side by side.
    const base = layerBody("terp.base");
    const alignedAt = base.indexOf('[data-terp="detail-list"][data-layout="aligned"] {');
    const aligned = base.slice(alignedAt, base.indexOf("}", alignedAt));
    const groupAt = base.indexOf('[data-terp="detail-list-group"] {');
    expect(groupAt, "the group should have a base rule").toBeGreaterThan(-1);
    const group = base.slice(groupAt, base.indexOf("}", groupAt));
    const tracks = (body: string) => /grid-template-columns:\s*([^;]+);/.exec(body)?.[1]?.trim();
    const columnGap = (body: string) => /column-gap:\s*([^;]+);/.exec(body)?.[1]?.trim();
    expect(tracks(aligned), "aligned declares the shared track list").toBeTruthy();
    expect(tracks(group), "the group shares aligned's track list").toBe(tracks(aligned));
    expect(columnGap(group), "and its gutter, which the subgrid inherits").toBe(
      columnGap(aligned),
    );
    // Every child spans the group, or a subgridded list would occupy one track and its values
    // would land in the label column.
    const childAt = base.indexOf('[data-terp="detail-list-group"] > * {');
    expect(childAt, "the group's children should span it").toBeGreaterThan(-1);
    expect(base.slice(childAt, base.indexOf("}", childAt))).toContain("grid-column: 1 / -1");
    // The group's gap is a row gap at every step, for the list's own reason: the column gap is
    // the shared measure and is not a caller's to move.
    for (const token of [0, 1, 2, 3, 4, 6, 8]) {
      const stepAt = base.indexOf(`[data-terp="detail-list-group"][data-gap="${token}"]`);
      expect(stepAt, `the group has no rule for gap ${token}`).toBeGreaterThan(-1);
      const step = base.slice(stepAt, base.indexOf("}", stepAt));
      expect(step, `gap ${token} must set the row gap only`).toContain(
        `row-gap: var(--space-${token})`,
      );
      expect(/[^-]column-gap|^column-gap/.test(step), `gap ${token} must not touch the columns`).toBe(
        false,
      );
    }
  });

  it("gives the page title, a card title and body copy three different steps", () => {
    // The scale was flat: the single h1 of a view rendered at lg (18px) against a card title at
    // base (16px) against 16px prose — one step from the h1 to a section heading, and a section
    // heading the same size as the text under it. --font-size-xl was published with exactly one
    // reader, so the top of the scale existed and the page that most needs it was not using it.
    //
    // Pinned here rather than left to the baselines because a screenshot cannot say WHICH step a
    // rendered size came from, and the point of the change is that these four are four steps of
    // one published scale rather than four sizes that happen to differ.
    const base = layerBody("terp.base");
    for (const [selector, step] of [
      // page-title left the TOP step when the header became a band, but it still has a step
      // and this is it: sm, the trail's own size, because the title IS the trail's leaf and a
      // 24px leaf on 14px ancestors reads as small-small-BIG rather than as one trail. Pinned
      // rather than dropped — removing it from this loop, which is what the band change first
      // did, left the one marker whose size the change was about free to drift.
      ['[data-terp="page-title"]', "sm"],
      // The top step keeps two readers, which is what stops the token going unread;
      // tokens.guard.test.ts holds that end.
      ['[data-terp="heading"][data-size="xl"]', "xl"],
      ['[data-terp="card-title"]', "lg"],
      ['[data-terp="card-description"]', "sm"],
    ] as const) {
      const at = base.indexOf(`${selector} {`);
      expect(at, `${selector} should have a rule`).toBeGreaterThan(-1);
      expect(
        base.slice(at, base.indexOf("}", at)),
        `${selector} should render the ${step} step of the published scale`,
      ).toContain(`font-size: var(--font-size-${step})`);
    }
  });

  it("declares a wide-half gap rule for every step SpaceToken allows", () => {
    // The narrow half is covered by the roll-call below; this is its counterpart. A responsive
    // gap whose wide step has no rule silently renders the narrow gap at every width — which
    // is the failure mode of the whole responsive idea, and invisible unless a specimen happens
    // to be recorded at both viewports.
    const base = layerBody("terp.base");
    const wide = base.slice(base.indexOf("@media not all and (max-width: 768px)"));
    for (const token of [0, 1, 2, 3, 4, 6, 8]) {
      expect(
        declaresRuleFor(wide, `[data-terp="stack"][data-gap-wide="${token}"]`),
        `the wide half has no rule for gap ${token}`,
      ).toBe(true);
    }
    for (const direction of ["column", "row"]) {
      expect(
        declaresRuleFor(wide, `[data-terp="stack"][data-direction-wide="${direction}"]`),
        `the wide half has no rule for direction ${direction}`,
      ).toBe(true);
    }
  });

  it("pins the four Grid track floors, which no baseline can hold", () => {
    // The grid specimens gate the MECHANISM and not the values, and the gap between those two
    // was measured rather than assumed. An auto-fit grid quantises: a floor only changes the
    // rendered column count when it crosses a threshold for the container's width. At
    // `grid-min-column`'s 66rem, moving the md floor 20rem -> 22rem drops it from three columns
    // to two and repaints 63,524 pixels — while moving it 20rem -> 21rem changes **nothing**,
    // and all ten grid baselines pass. So the pictures prove the attribute selects a different
    // floor; only this proves which floor.
    //
    // The same shape as the shell declarations below, and the reason the values are pinned here
    // rather than promoted to tokens: four published tokens with one consumer is the vocabulary
    // the density cell tokens were deleted for. They become tokens the day an app asks.
    const base = layerBody("terp.base");
    for (const [attribute, floor] of [
      [null, "16rem"],
      ["xs", "10rem"],
      ["md", "20rem"],
      ["lg", "26rem"],
    ] as const) {
      const selector =
        attribute === null
          ? '[data-terp="grid"]'
          : `[data-terp="grid"][data-min-column="${attribute}"]`;
      const at = base.indexOf(`${selector} {`);
      expect(at, `${selector} should have a rule`).toBeGreaterThan(-1);
      expect(
        base.slice(at, base.indexOf("}", at)),
        `${selector} should floor its tracks at ${floor}`,
      ).toContain(`minmax(min(${floor}, 100%), 1fr)`);
    }
    // sm is the default and therefore the base rule, so it has no attribute of its own — and
    // its floor is the same 16rem the hub grid uses, which is why the two agree by construction
    // instead of by coincidence.
    expect(
      declaresRuleFor(base, '[data-terp="grid"][data-min-column="sm"]'),
      "sm is the base rule; an attribute rule for it means the default is described twice",
    ).toBe(false);
    const hub = base.indexOf('[data-terp="hubpage-grid"] {');
    expect(base.slice(hub, base.indexOf("}", hub))).toContain("minmax(min(16rem, 100%), 1fr)");
  });

  it("floors every fixed Grid column at zero, not at min-content", () => {
    // `repeat(N, 1fr)` looks equivalent and is not: a bare 1fr floors at the track's
    // min-content size, so one long unbroken word in a cell widens its column and the grid
    // overflows its container. A two-column form of long field labels walks straight into it,
    // which is the case Grid exists for. minmax(0, 1fr) is the fix, and it is invisible to
    // every baseline that does not happen to contain an overflowing word.
    const base = layerBody("terp.base");
    for (const count of [1, 2, 3, 4]) {
      const selector = `[data-terp="grid"][data-columns="${count}"]`;
      const at = base.indexOf(`${selector} {`);
      expect(at, `${selector} should have a rule`).toBeGreaterThan(-1);
      expect(
        base.slice(at, base.indexOf("}", at)),
        `${selector} must floor its tracks at 0, or a long word widens the column`,
      ).toContain("minmax(0, 1fr)");
    }
  });

  it("declares a rule for every size Button names, and none for its default", () => {
    // The same bargain the gap rules strike: the union and the sheet are two lists kept by
    // hand, so widening ButtonSize without adding a rule would silently fall back to the
    // standard geometry rather than fail.
    //
    // And the converse, which is the part worth pinning: md must have NO rule of its own. Its
    // geometry is the base rule, exactly as "comfortable" is the token sheet's :root value, and
    // a data-size="md" rule appearing here would mean the component had started stamping the
    // attribute for its default — leaving two places that describe the standard control.
    const base = layerBody("terp.base");
    for (const size of ["sm", "lg"]) {
      expect(
        declaresRuleFor(base, `[data-terp="button"][data-size="${size}"]`),
        `Button has no rule for size ${size}`,
      ).toBe(true);
    }
    expect(
      declaresRuleFor(base, '[data-terp="button"][data-size="md"]'),
      "md is the base rule; a rule of its own means the default is described twice",
    ).toBe(false);
    // Sizes read the density token rather than heights of their own, which is what makes the
    // two dimensions compose: the compact re-scoping moves the token these calc() off.
    const at = base.indexOf('[data-terp="button"][data-size="sm"]');
    expect(
      base.slice(at, base.indexOf("}", at)),
      "a size that hardcodes its height stops following density",
    ).toContain("var(--density-control-min-height)");
  });

  it("declares one avatar rule plus a small variant, and nothing for the default size", () => {
    // The tile used to be two rules of eleven declarations each — profile-avatar and
    // user-menu-avatar — identical but for a width, a height and a font size. Merging them is only
    // zero-pixel if the variant keeps BOTH geometries, so this pins the shape of the pair: a base
    // rule carrying md, and an sm rule carrying exactly the three declarations that differ.
    const base = layerBody("terp.base");
    expect(declaresRuleFor(base, '[data-terp="avatar"]')).toBe(true);
    expect(declaresRuleFor(base, '[data-terp="avatar"][data-size="sm"]')).toBe(true);
    // md is the base rule, as with Button. A rule of its own means the default is described twice.
    expect(
      declaresRuleFor(base, '[data-terp="avatar"][data-size="md"]'),
      "md is the base rule; a rule of its own means the default is described twice",
    ).toBe(false);
    const at = base.indexOf('[data-terp="avatar"][data-size="sm"]');
    const body = base.slice(at, base.indexOf("}", at));
    for (const declaration of ["width: 2rem", "height: 2rem", "var(--font-size-sm)"]) {
      expect(body, `the small variant must restate ${declaration}`).toContain(declaration);
    }
    // And nothing else: a declaration here that the base already sets is a second description of
    // the same tile, which is the duplication the merge removed.
    expect(body).not.toContain("border-radius");
    expect(body).not.toContain("background");
  });

  it("declares a min-inline-size for every step ColumnWidth names, and nothing it does not", () => {
    // The Button gate above notes that its union and its sheet are two lists kept by hand. This
    // one reads the union out of the source instead, because a declared track that silently does
    // nothing is exactly the defect this attribute exists to end: `meta.width` was a px hint that
    // `table-layout: auto` shrank away, so widening ColumnWidth without a rule would restore the
    // old behaviour under a new spelling.
    const source = sources["./dataview/types.ts"];
    const union = /export type ColumnWidth =([^;]+);/.exec(source);
    expect(union, "ColumnWidth is not declared where this test looks for it").not.toBeNull();
    const steps = [...(union?.[1] ?? "").matchAll(/"([a-z]+)"/g)].map((match) => match[1]);
    expect(steps.length, "parsed no steps out of ColumnWidth").toBeGreaterThan(0);

    const base = layerBody("terp.base");
    for (const step of steps) {
      const selector = `[data-terp="dataview-table"] > thead > tr > th[data-width="${step}"]`;
      expect(declaresRuleFor(base, selector), `no rule for step ${step}`).toBe(true);
      const at = base.indexOf(selector);
      expect(
        base.slice(at, base.indexOf("}", at)),
        `step ${step} must bind as a minimum; a width is a preference auto layout shrinks away`,
      ).toContain("min-inline-size");
    }
    // And nothing beyond the union. `lg` and `content` were both drafted and declined for having
    // no consumer, so a rule for either means the sheet grew a step the type cannot express.
    for (const absent of ["lg", "xl", "content", "auto"]) {
      expect(
        declaresRuleFor(
          base,
          `[data-terp="dataview-table"] > thead > tr > th[data-width="${absent}"]`,
        ),
        `the sheet declares a step ColumnWidth does not name: ${absent}`,
      ).toBe(false);
    }
  });

  it("keeps the loading cursor where it can beat the disabled cursor", () => {
    // A loading button is also `:disabled` — the component sets both — and the disabled rule
    // lives in terp.state. So a `data-loading` rule in terp.base loses on layer order and the
    // cursor silently stays `not-allowed`, which tells a user "you may not" where the truth is
    // "not yet". It has to be in terp.state, and after the disabled rule, because the two weigh
    // the same (0,2,0) and nothing but source order separates them.
    //
    // This is the focus-ring lesson in miniature, and it is invisible to every other lane:
    // Playwright's screenshots do not paint a pointer, so no baseline has ever held either
    // cursor. The computed lane asserts the resolved values; this asserts the structure that
    // produces them.
    const state = layerBody("terp.state");
    const base = layerBody("terp.base");
    expect(
      declaresRuleFor(base, '[data-terp="button"][data-loading="true"]'),
      "in terp.base this rule loses to the disabled cursor and does nothing",
    ).toBe(false);
    const disabledAt = state.indexOf('[data-terp="button"]:disabled');
    const loadingAt = state.indexOf('[data-terp="button"][data-loading="true"]');
    expect(disabledAt, "the disabled rule should be in terp.state").toBeGreaterThan(-1);
    expect(loadingAt, "the loading rule should be in terp.state").toBeGreaterThan(-1);
    expect(loadingAt).toBeGreaterThan(disabledAt);
  });

  it("declares a gap rule for every step SpaceToken allows", () => {
    // gap moved from a computed inline value to a rule per step, so the union and the sheet
    // are now two lists maintained by hand. Widening SpaceToken without adding rules would
    // silently fall back to the default gap rather than fail.
    const base = layerBody("terp.base");
    for (const token of [0, 1, 2, 3, 4, 6, 8]) {
      // `detail-list` joined the three late, and its absence is why the value it now takes was
      // unreachable: every other layout primitive published a gap on this scale, so a detail
      // list wanting looser rows had nowhere to say so — and app modules may write neither
      // `style` nor `className`. Its rules set `row-gap` rather than the shorthand, for the
      // reason the sheet gives there: the column gap is the layout's, not the caller's.
      for (const marker of ["stack", "card", "grid", "detail-list"]) {
        expect(
          declaresRuleFor(base, `[data-terp="${marker}"][data-gap="${token}"]`),
          `${marker} has no rule for gap ${token}`,
        ).toBe(true);
      }
      // Padding is the same bargain on the same scale, and it is the dimension Stack did not
      // have at all — a padded region used to be reachable only through a Card, which brought
      // its border and background whether or not they were wanted.
      for (const marker of ["stack", "grid"]) {
        expect(
          declaresRuleFor(base, `[data-terp="${marker}"][data-padding="${token}"]`),
          `${marker} has no rule for padding ${token}`,
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
      '[data-terp="dataview-card"][data-clickable="true"]:focus-within',
      // Re-derived rather than assumed, because the condition is not "has something
      // migrated" but "can any element this selector matches still beat it". Of the SEVENTEEN
      // sites wearing the iconbutton marker, only six can carry the disabled attribute at all:
      // the four pagination arrows and the two reorder arrows. The shell's toggles, the toast
      // dismisser, the combobox's clear button, the calendar's month arrows, the expand toggle,
      // the toolbar's clear-search button and two layout toggles and the password reveal have no
      // disabled state —
      // and each of the six set cursor inline until it migrated. The day a calendar arrow gains
      // a min/max bound, this answer changes back.
      '[data-terp="iconbutton"]:disabled',
      // HubPage was the condition for both of these, and it was the condition in the strongest
      // form: hubcard-body's border and hubcard-title's colour were declared inline on the very
      // elements these selectors match, so no layered rule could reach them at any specificity.
      // Both surfaces come from terp.base now.
      '[data-terp="hubcard"]:hover [data-terp="hubcard-body"]',
      '[data-terp="hubcard"]:hover [data-terp="hubcard-title"]',
      // AppShell's, and it blocked these two on its own: toggleStyle declared background and
      // colour inline on the shell's two toggles, the last elements wearing the icon-button
      // marker able to out-rank a layered rule. Their resting look is a scoped base rule now,
      // so this wins on LAYER — terp.state over terp.base — whatever its specificity.
      '[data-terp="iconbutton"]:hover',
      // And the nav link's, whose consumer was NAV_LINK_STYLE: a CSSProperties object exported
      // for every router's link renderer to spread onto its own element, so colour and
      // background were inline on the very elements this selector matches.
      '[data-terp="appshell-nav"] a:hover',
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
    // selector matches, and there is now none anywhere in the package. ConfirmDialog's dialog
    // and Popover's panel were the two that mattered and took their surface from the sheet in
    // stage 4; the three that remained — AppShell's drawer, DataViewCardList's card and
    // LoginView's card — went with those three components' own migrations, the last of them
    // with LoginView. The DataView card is worth remembering anyway: it is a div with onClick
    // and no tabIndex, so it cannot match :focus-visible at all, which is why the sheet reaches
    // it with :focus-within.
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
    // ZERO. Every rule in this sheet is now beatable by an app's unlayered theme.css without
    // !important and without out-specifying anything, which is what the phase was for: an
    // escalation does not merely outrank an app's stylesheet, it makes that one declaration
    // unthemeable, because for important declarations the layer order reverses and unlayered
    // styles sort last.
    //
    // Asserted as exact equality in both directions. A new escalation fails here and has to
    // name its inline consumer in the ledger above, which is now empty.
    const declarations = css.split("!important").length - 1;
    expect(declarations).toBe(0);
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
      // The toolbar's three descendant rules, and the fourth on the layout group. The search
      // wrapper's `> span` is its glyph, unqualified because the clear button is a <button> and
      // the field is an <input>, so a span there can only be the glyph. The field rule has to
      // out-rank input[data-terp="input"] { padding } and does so at (0,2,0) against (0,1,1) —
      // deleting it puts the glyph on top of the text with the marker inventory intact.
      // The skeleton's five bars, structural because repeated identical boxes in a place
      // where only bars sit is the card-main / actions-cell precedent. Deleting it collapses
      // dataview-loading and leaves the marker inventory intact.
      '[data-terp="dataview-skeleton"] > div',
      '[data-terp="dataview-toolbar-search"] > span',
      '[data-terp="dataview-toolbar-search"] > [data-terp="input"]',
      '[data-terp="dataview-toolbar-search"] > [data-terp="iconbutton"]',
      '[data-terp="dataview-toolbar-layout"] > [data-terp="iconbutton"]',
      '[data-terp="dataview-table"] > thead > tr > th',
      '[data-terp="dataview-row"] > td',
      '[data-terp="dataview-row"][data-clickable="true"]',
      'th[data-terp="dataview-expand-cell"]',
      'th[data-terp="dataview-select-cell"]',
      'th[data-terp="dataview-actions-cell"]',
      'td[data-terp="dataview-actions-cell"]',
      'th[data-terp="dataview-actions-cell"] > span',
      '[data-terp="dataview-card-main"] > span',
      // The expand toggle, in both places it renders. It wears the shared iconbutton
      // marker, so its geometry is reachable only through the ancestor it sits in — and
      // losing either selector leaves the toggle unstyled in one of the two layouts,
      // which the marker inventory cannot see because the marker is still rendered.
      '[data-terp="dataview-expand-cell"] > [data-terp="iconbutton"]',
      '[data-terp="dataview-card-main"] > [data-terp="iconbutton"]',
      '[data-terp="dataview-pager"] > [data-terp="iconbutton"]',
      // Two structural span rules in the row-action cluster, and they mean different
      // things: the first reaches the custom-control wrappers (the only span that is a
      // direct child of the cluster — the inline actions are buttons and the overflow
      // menu's root is a div), the second reaches an action's leading icon.
      '[data-terp="dataview-row-actions"] > span',
      '[data-terp="dataview-inline-action"] > span',
      '[data-terp="dataview-column-option"] > label',
      '[data-terp="dataview-column-option"] > [data-terp="iconbutton"]',
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
    // Anchored to the STANDALONE rule, not to the first mention of the marker. A plain indexOf
    // finds whichever selector merely contains it — and one now does: the measured-width
    // reach-through that caps this wrapper's blocks is declared earlier in the layer, so the
    // loose locator sliced that rule's body instead and reported a width where it expected
    // display: contents. The assertion was right and its aim was not.
    const rule = [...base.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find(
      (match) => match[1]!.trim() === '[data-terp="markdown"]',
    );
    expect(rule, 'no standalone [data-terp="markdown"] rule in terp.base').toBeDefined();
    expect(rule![2]!.trim()).toBe("display: contents;");
  });

  it("pins the values of five declarations no lane can reach", () => {
    // Presence is not enough for these five, and that is the distinction the roll-calls above
    // already draw for Button sizes and gap steps: a rule can be present and WRONG, and nothing
    // here would notice. Each of these is reachable through a published prop, and none of them
    // is painted by any specimen — so today their values could be changed to anything and the
    // whole suite stays green.
    //
    // Two disabled paints, both reachable (Combobox and DatePicker each take `disabled`), and
    // neither rendered in that state by any specimen. Mutation: change either colour token.
    const state = layerBody("terp.state");
    const ruleFor = (selector: string) => {
      const match = [...state.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find(
        (rule) => rule[1]!.trim().replace(/\s+/g, " ") === selector,
      );
      expect(match, `${selector} has no rule of its own`).toBeDefined();
      return match![2]!;
    };
    expect(ruleFor('[data-terp="combobox-option"]:disabled')).toContain(
      "color: var(--color-neutral-400)",
    );
    expect(ruleFor('[data-terp="calendar-day"]:disabled')).toContain(
      "color: var(--color-neutral-300)",
    );

    // The split archetype's two outer list widths. `md` is painted by the split-page specimen;
    // `sm` and `lg` are painted by nothing, and they live inside a wide-viewport media block the
    // pinned 1280 does reach — so the rules apply and simply have no picture. A renamed
    // attribute value would silently stop matching. Mutation: rename "sm" to "small", or change
    // either track measure.
    const wide = css.slice(css.indexOf('[data-terp="splitpage-panes"][data-list-width="sm"]'));
    expect(wide.slice(0, 120)).toContain("minmax(0, 18rem) minmax(0, 1fr)");
    const lg = css.slice(css.indexOf('[data-terp="splitpage-panes"][data-list-width="lg"]'));
    expect(lg.slice(0, 120)).toContain("minmax(0, 32rem) minmax(0, 1fr)");
  });

  it("gives every migrated component a base rule in terp.base", () => {
    // markers.test.ts pins the marker join in both directions but cannot see a *deleted*
    // rule: removing a whole block only shrinks the styled set, which still passes. These
    // components render no inline base styles at all, so a missing rule here means the
    // component renders unstyled.
    const base = layerBody("terp.base");
    for (const marker of [
      "button",
      "avatar",
      "badge",
      "alert",
      "tooltip",
      "input",
      "input-password",
      "field",
      "control-label",
      "checkbox",
      "radio",
      "switch",
      "stack",
      "appshell-skip-link",
      "splitpage-panes",
      "splitpane",
      "detail-list",
      "detail-list-group",
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
      "dataview-expanded-cell",
      "dataview-pagination",
      "dataview-pager",
      "dataview-row-actions",
      "dataview-inline-action",
      "dataview",
      "dataview-error",
      "dataview-scroll",
      "dataview-skeleton",
      "dataview-toolbar",
      "dataview-toolbar-actions",
      "dataview-toolbar-count",
      "dataview-toolbar-layout",
      "dataview-toolbar-search",
      "dataview-toolbar-spacer",
      "dataview-toolbar-status",
      "dataview-column-settings",
      "dataview-column-settings-title",
      "dataview-column-option",
      "hubpage-grid",
      "hubcard",
      "hubcard-link",
      "hubcard-body",
      "hubcard-heading",
      "hubcard-icon",
      "hubcard-title",
      "hubcard-description",
      "hubcard-stat",
      "appshell",
      "appshell-sidebar",
      "appshell-backdrop",
      "appshell-brand",
      "appshell-brand-row",
      "appshell-brand-title",
      "appshell-nav",
      "appshell-nav-list",
      "appshell-nav-label",
      "appshell-column",
      "appshell-header",
      "appshell-header-group",
      "appshell-main",
      "appshell-footer",
      "page",
      "page-header",
      "page-heading",
      "page-badges",
      "page-description",
      "page-title",
      "resource-list",
      "resource-list-create",
      "resource-list-error",
      "resource-list-empty",
      "resource-list-items",
      "resource-list-row",
      "module-nav",
      "module-nav-list",
      "module-nav-link",
      "profile-card",
      "profile-email",
      "profile-role",
      "login-view",
      "login-card",
      "login-brand",
      "login-title",
      "login-form",
      "login-sso",
      "login-separator",
      "login-separator-rule",
      "login-error",
      "admin-form",
      "admin-section-title",
      "grid",
      "divider",
      "heading",
      "text",
      "code",
      "code-block",
      "link",
      "detail-list-row",
      // `appshell-nav-group-label` is here; `appshell-nav-group` deliberately is NOT, and the
      // omission joins `appshell-mark` and `appshell-skip-link` above rather than starting a
      // new kind of exception. The wrapper declares nothing on its own — in the sidebar it is a
      // plain block whose whole job is to be a sibling, so its two rules are a `+` pair and a
      // placement override, and it has no standalone selector to match. `declaresRuleFor` wants
      // exact selector equality, which is what makes it worth having: adding the family pattern
      // here to make the list look complete would fail, correctly.
      "appshell-nav-group-label",
      // The 32 below close a gap the roll-call carried quietly: it listed barely more than
      // three quarters of the pinned markers, so a quarter of the sheet's base blocks could be
      // DELETED and only the screenshot lane would notice — and only for a marker some specimen
      // happens to paint. (No figures here on purpose: both sides of that ratio have moved twice
      // since it was written, and a citation keeps where a tally rots.)
      // markers.test.ts cannot see a deleted rule either: removing a block only shrinks the
      // styled set, which still satisfies both of its directions.
      //
      // Seven pinned markers are deliberately NOT here, because they have no standalone base
      // rule to assert. appshell-nav-group declares nothing on its own (it is a
      // sibling-combinator pair plus a placement override); dataview-row, dataview-select-cell,
      // dataview-expand-cell and dataview-actions-cell are styled through their descendants
      // and attribute variants; and drawer-focus-start / drawer-focus-end appear only in the
      // shared visually-hidden selector list. Adding any of them here fails, correctly —
      // declaresRuleFor wants exact selector equality, which is what makes this list mean
      // something.
      "alert-body",
      "alert-icon",
      "alert-title",
      "appshell-mark",
      "breadcrumbs-separator",
      "button-icon",
      "calendar-header",
      "calendar-title",
      "calendar-weekday",
      "card-actions",
      "card-description",
      "card-heading",
      "combobox-empty",
      "combobox-field",
      "detail-list-term",
      "detail-list-value",
      "empty-state-description",
      "empty-state-icon",
      "empty-state-title",
      "error-state-description",
      "error-state-icon",
      "error-state-title",
      "field-error",
      "field-hint",
      "field-label",
      "field-label-text",
      "iconbutton",
      "loading-state-spinner",
      "radio-group",
      "radio-group-legend",
      "radio-group-options",
      "tooltip-anchor",
    ]) {
      expect(
        declaresRuleFor(base, `[data-terp="${marker}"]`),
        `[data-terp="${marker}"] must have a base rule of its own, not merely appear in one`,
      ).toBe(true);
    }
  });
});
