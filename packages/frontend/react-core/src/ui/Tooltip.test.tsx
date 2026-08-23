// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { afterEach, describe, expect, it } from "vitest";

import { Button } from "./Button";
import { Tooltip } from "./Tooltip";

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
      const anchor = tooltip.parentElement!;
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
});
