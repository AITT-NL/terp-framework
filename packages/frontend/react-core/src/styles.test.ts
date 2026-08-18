// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import { TERP_STYLES_ID, TERP_STYLES_CSS, injectTerpStyles } from "./styles";

/** The sheet with comments removed — prose must not satisfy a structural assertion. */
const css = TERP_STYLES_CSS.replace(/\/\*[\s\S]*?\*\//g, "");

/** The body of one `@layer <name> { … }` block, brace-matched. */
function layerBody(name: string): string {
  const open = css.indexOf(`@layer ${name} {`);
  if (open === -1) return "";
  let depth = 0;
  for (let i = css.indexOf("{", open); i < css.length; i += 1) {
    if (css[i] === "{") depth += 1;
    else if (css[i] === "}") {
      depth -= 1;
      if (depth === 0) return css.slice(css.indexOf("{", open) + 1, i);
    }
  }
  return "";
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
    // The tax comes off per CONSUMER, not per rule, and the condition is the LAST component
    // a selector matches rather than the first. The reduced-motion block reaches AppShell's
    // nav links and collapse and HubPage's card title, all of which still declare transition
    // in a style object — and no layer beats the style attribute, so without !important a
    // reduced-motion user still gets those animations. It comes off when they migrate.
    //
    // `[data-terp="input"]` used to be listed here for the same reason and no longer is:
    // Combobox and both date-picker triggers now take their base from the sheet, so all six
    // elements wearing that marker are migrated. That transition is the point of this test —
    // it fails loudly in whichever direction the sheet and the components disagree.
    expect(layerBody("terp.motion")).toContain("transition: none !important");
    expect(layerBody("terp.motion")).toContain("animation: none !important");
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
    ]) {
      const at = state.indexOf(rule);
      expect(at, `${rule} should still be declared`).toBeGreaterThan(-1);
      const block = state.slice(at, state.indexOf("}", at));
      expect(block, `${rule}: every element wearing the input marker is migrated`)
        .not.toContain("!important");
    }
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
    ]) {
      expect(base, `[data-terp="${marker}"] must have a base rule`).toContain(
        `[data-terp="${marker}"]`,
      );
    }
  });
});
