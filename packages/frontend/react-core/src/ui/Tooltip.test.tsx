// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { afterEach, describe, expect, it } from "vitest";

import { Button } from "./Button";
import { Tooltip, placeBubble } from "./Tooltip";

afterEach(cleanup);

describe("Tooltip", () => {
  it("describes its trigger and opens on focus and hover", () => {
    render(
      <Tooltip content="More information">
        <Button>Help</Button>
      </Tooltip>,
    );
    const trigger = screen.getByRole("button", { name: "Help" });
    const tooltip = screen.getByRole("tooltip", { hidden: true });
    expect(trigger).toHaveAttribute("aria-describedby", tooltip.id);
    expect(tooltip).not.toBeVisible();
    fireEvent.focus(trigger);
    expect(tooltip).toBeVisible();
    fireEvent.blur(trigger);
    expect(tooltip).not.toBeVisible();
    fireEvent.mouseEnter(trigger.parentElement!);
    expect(tooltip).toBeVisible();
  });

  it("dismisses on Escape without moving the pointer or focus", () => {
    // WCAG 1.4.13, Dismissible. There was no key handler of any kind, so a bubble covering the
    // content under it could only be escaped by moving away from the control the user was
    // reading about. Bound on the document, because the pointer-opened case has no focus
    // anywhere near this component and a trigger-bound handler would never see the key.
    // Mutation: delete the keydown effect.
    render(
      <Tooltip content="More information" defaultOpen>
        <Button>Help</Button>
      </Tooltip>,
    );
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toBeVisible();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(tooltip).not.toBeVisible();
  });

  it("stays open while the pointer crosses to the bubble", () => {
    // WCAG 1.4.13, Hoverable. The bubble used to declare pointer-events: none, which makes
    // reaching it impossible by construction; that is gone, and the close is delayed so the
    // visual gap between trigger and bubble can be crossed. Re-entering cancels the close.
    // Mutation: close synchronously on mouseleave, and this fails.
    vi.useFakeTimers();
    try {
      render(
        <Tooltip content="More information" defaultOpen>
          <Button>Help</Button>
        </Tooltip>,
      );
      const tooltip = screen.getByRole("tooltip");
      // The trigger's parent, not the bubble's: the bubble is portalled to the body.
      const anchor = screen.getByRole("button", { name: "Help" }).parentElement!;
      fireEvent.mouseLeave(anchor);
      // Still open partway through the grace period...
      act(() => {
        vi.advanceTimersByTime(60);
      });
      expect(tooltip).toBeVisible();
      // ...and re-entering cancels the close entirely.
      fireEvent.mouseEnter(anchor);
      act(() => {
        vi.advanceTimersByTime(500);
      });
      expect(tooltip).toBeVisible();
      // Leaving and staying away does close it.
      fireEvent.mouseLeave(anchor);
      act(() => {
        vi.advanceTimersByTime(500);
      });
      expect(tooltip).not.toBeVisible();
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders the bubble outside its anchor, so no scroll container can clip it", () => {
    // An absolutely positioned child of the anchor was clipped by any ancestor whose overflow
    // was not visible, whatever its z-index -- a tooltip in a DataView cell was cut off at the
    // table's edge. Portalled, the bubble has no ancestor but the body. The description link
    // survives the move: aria-describedby is by id, not by position in the tree.
    // Mutation: render the bubble inside the anchor again, and the first assertion fails.
    render(
      <div data-testid="scroller">
        <Tooltip content="More information" defaultOpen>
          <Button>Help</Button>
        </Tooltip>
      </div>,
    );
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip.parentElement).toBe(document.body);
    expect(screen.getByTestId("scroller")).not.toContainElement(tooltip);
    expect(screen.getByRole("button", { name: "Help" })).toHaveAccessibleDescription(
      "More information",
    );
  });

  it("stays open while the pointer moves from the trigger onto the portalled bubble", () => {
    // Hoverable survives the portal because React dispatches enter and leave along the
    // component tree, where the bubble is still inside the anchor. Driven with the native pair
    // React actually listens to (mouseout/mouseover), from the trigger straight onto the bubble.
    // Mutation: portal the bubble from a sibling of the anchor instead of from inside it, and
    // this leave reaches the anchor and closes it.
    vi.useFakeTimers();
    try {
      render(
        <Tooltip content="More information" defaultOpen>
          <Button>Help</Button>
        </Tooltip>,
      );
      const tooltip = screen.getByRole("tooltip");
      const trigger = screen.getByRole("button", { name: "Help" });
      fireEvent.mouseOut(trigger, { relatedTarget: tooltip });
      fireEvent.mouseOver(tooltip, { relatedTarget: trigger });
      act(() => {
        vi.advanceTimersByTime(500);
      });
      expect(tooltip).toBeVisible();
    } finally {
      vi.useRealTimers();
    }
  });

  it("places an open bubble from what it measured, inside the window", () => {
    // A trigger at the top-right corner -- a page band's primary action -- is the case that put
    // the message off screen: it opened above, at the trigger's left edge, a trigger's width
    // wide. Measured now: above does not fit, so it flips below, and it is pushed in from the
    // right edge by exactly its own width.
    // Mutation: drop the layout effect, and the bubble stays at 0,0 and hidden.
    const rects = new Map<string, Partial<DOMRect>>([
      ["tooltip-anchor", { left: 950, right: 1010, top: 10, bottom: 46, width: 60, height: 36 }],
      ["tooltip", { left: 0, right: 200, top: 0, bottom: 40, width: 200, height: 40 }],
    ]);
    const original = HTMLElement.prototype.getBoundingClientRect;
    HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement) {
      const rect = rects.get(this.getAttribute("data-terp") ?? "");
      return rect === undefined ? original.call(this) : (rect as DOMRect);
    };
    try {
      render(
        <Tooltip content="More information" defaultOpen>
          <Button>Help</Button>
        </Tooltip>,
      );
      const tooltip = screen.getByRole("tooltip");
      expect(tooltip.style.visibility).toBe("visible");
      expect(tooltip.style.top).toBe("50px"); // below: bottom 46 + gap 4
      expect(tooltip.style.left).toBe(`${window.innerWidth - 200 - 8}px`);
    } finally {
      HTMLElement.prototype.getBoundingClientRect = original;
    }
  });
});

describe("placeBubble", () => {
  const viewport = { width: 1280, height: 900 };
  const bubble = { width: 200, height: 40 };

  it("opens above a trigger with room above it, at the trigger's start edge", () => {
    expect(placeBubble({ left: 100, right: 160, top: 300, bottom: 336 }, bubble, viewport)).toEqual(
      { left: 100, top: 256 },
    );
  });

  it("flips below a trigger too close to the top", () => {
    expect(placeBubble({ left: 100, right: 160, top: 20, bottom: 56 }, bubble, viewport)).toEqual({
      left: 100,
      top: 60,
    });
  });

  it("is pushed in from the right edge rather than crossing it", () => {
    expect(
      placeBubble({ left: 1200, right: 1260, top: 300, bottom: 336 }, bubble, viewport).left,
    ).toBe(1280 - 200 - 8);
  });

  it("aligns to the trigger's right edge in a right-to-left document, and stays in from the left", () => {
    expect(
      placeBubble({ left: 600, right: 660, top: 300, bottom: 336 }, bubble, viewport, true).left,
    ).toBe(460);
    expect(
      placeBubble({ left: 10, right: 70, top: 300, bottom: 336 }, bubble, viewport, true).left,
    ).toBe(8);
  });

  it("stays on screen in a window too short for either side, over the trigger", () => {
    expect(
      placeBubble({ left: 100, right: 160, top: 20, bottom: 56 }, bubble, { width: 1280, height: 90 })
        .top,
    ).toBe(8);
  });
});
