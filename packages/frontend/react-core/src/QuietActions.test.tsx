// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { QuietActions } from "./QuietActions";
import { TERP_STYLES_CSS } from "./styles";
import { Button } from "./ui/Button";
import { Code } from "./typography";

afterEach(cleanup);

/** The rules inside the sheet's one hover-capability query. */
function hoverBlock(): string {
  const opener = "@media (hover: hover) {";
  const at = TERP_STYLES_CSS.indexOf(opener);
  if (at === -1) throw new Error("the sheet declares no hover-capability query");
  const first = TERP_STYLES_CSS.indexOf("{", at);
  let depth = 0;
  for (let i = first; i < TERP_STYLES_CSS.length; i += 1) {
    if (TERP_STYLES_CSS[i] === "{") depth += 1;
    else if (TERP_STYLES_CSS[i] === "}") {
      depth -= 1;
      if (depth === 0) return TERP_STYLES_CSS.slice(first + 1, i);
    }
  }
  throw new Error("the hover-capability query is not brace-balanced");
}

describe("QuietActions", () => {
  it("renders the value and the action, with the action in its own slot", () => {
    render(
      <QuietActions actions={<Button aria-label="Copy the fingerprint" />}>
        <Code>9f2c1b7a</Code>
      </QuietActions>,
    );
    const row = document.querySelector('[data-terp="quiet-actions"]')!;
    expect(row.textContent).toContain("9f2c1b7a");
    const slot = row.querySelector('[data-terp="quiet-actions-slot"]')!;
    expect(
      slot.querySelector("button"),
      "the action goes in the slot, which is the box that fades",
    ).toBe(screen.getByRole("button", { name: "Copy the fingerprint" }));
    // The value is NOT in the slot, or it would fade with the action.
    expect(slot.textContent).not.toContain("9f2c1b7a");
  });

  it("leaves the action in the accessibility tree at rest", () => {
    // The property that separates this from hiding something. Opacity is not `visibility`
    // and not `display`, so the action is announced, named and operable at every moment --
    // what changes is only whether a sighted pointer user has to look at it. Asserted
    // through the accessible-name query rather than by reading a style, because that is
    // what a screen reader and a voice-control user actually resolve.
    render(
      <QuietActions actions={<Button aria-label="Copy the fingerprint" />}>
        <Code>9f2c1b7a</Code>
      </QuietActions>,
    );
    const action = screen.getByRole("button", { name: "Copy the fingerprint" });
    expect(action).toBeInTheDocument();
    expect(action, "never hidden from assistive tech").not.toHaveAttribute("aria-hidden");
    expect(action, "and never taken out of the tab order").not.toHaveAttribute("tabindex", "-1");
  });

  it("fades only where hovering exists, and reveals on focus as well", () => {
    // Three declarations, one mechanism, and each one closes a different way this pattern is
    // got wrong. jsdom resolves no media queries, so these are read out of the sheet rather
    // than off the element -- the alternative is a browser, which the workbench lane is.
    const hover = hoverBlock().replace(/\s+/g, " ");

    // 1. The fade is BEHIND the capability query. Unconditional, a touch screen -- which has
    //    no hover to reveal anything with -- would get an action that is permanently
    //    invisible and permanently tappable.
    expect(hover, "the resting state is inside the hover query").toContain(
      '[data-terp="quiet-actions"] [data-terp="quiet-actions-slot"] { opacity: 0; }',
    );
    const outside = TERP_STYLES_CSS.replace(hoverBlock(), "").replace(/\s+/g, " ");
    expect(
      outside,
      "and nowhere else, or a touch device gets an invisible control",
    ).not.toContain('[data-terp="quiet-actions-slot"] { opacity: 0');

    // 2. Focus reveals it too. Opacity does not remove an element from the tab order, so
    //    without this a keyboard user tabs to a control they cannot see.
    expect(hover, "hover reveals it").toContain('[data-terp="quiet-actions"]:hover');
    expect(hover, "and so does focus, or a keyboard lands somewhere invisible").toContain(
      '[data-terp="quiet-actions"]:focus-within',
    );

    // 3. The slot's box is declared OUTSIDE the query, so the space is reserved in every
    //    pointer mode. Inside it, the row would reflow under the cursor.
    expect(outside, "the slot reserves its space unconditionally").toContain(
      '[data-terp="quiet-actions-slot"] {',
    );
    expect(hover, "the fade changes opacity only, never layout").not.toContain("display:");
  });

  it("stamps a gap the sheet has a rule for", () => {
    render(
      <QuietActions gap={3} actions={<Button aria-label="Copy" />}>
        <Code>abc</Code>
      </QuietActions>,
    );
    expect(document.querySelector('[data-terp="quiet-actions"]')!.getAttribute("data-gap")).toBe(
      "3",
    );
    expect(TERP_STYLES_CSS).toContain('[data-terp="quiet-actions"][data-gap="3"]');
    // The default stamps nothing, so the base rule stands rather than being restated.
    cleanup();
    render(
      <QuietActions actions={<Button aria-label="Copy" />}>
        <Code>abc</Code>
      </QuietActions>,
    );
    expect(
      document.querySelector('[data-terp="quiet-actions"]')!.getAttribute("data-gap"),
    ).toBeNull();
  });
});
