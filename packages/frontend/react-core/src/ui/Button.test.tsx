// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Button } from "./Button";

afterEach(cleanup);

describe("Button", () => {
  // These assert the attributes rather than `style.background` (ADR 0094). The variant is
  // the semantic claim — that the sheet paints it is the sheet's business, and the visual
  // baselines are what prove the paint. Asserting the absence of an inline style is the
  // other half: it is what makes the rules in the sheet reachable at all, so a component
  // that quietly regrew a base `style={}` would silently take back its own restyleability.
  it("renders an accessible button with a default type and no inline styling", () => {
    render(<Button>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveAttribute("data-terp", "button");
    expect(button).toHaveAttribute("data-variant", "primary");
    expect(button.getAttribute("style")).toBeNull();
  });

  it("names the ghost variant on the element", () => {
    render(<Button variant="ghost">Cancel</Button>);
    const button = screen.getByRole("button", { name: "Cancel" });
    expect(button).toHaveAttribute("data-variant", "ghost");
    expect(button.getAttribute("style")).toBeNull();
  });

  it("renders a leading icon before the children", () => {
    render(
      <Button icon={<span data-testid="ico">i</span>}>Do it</Button>,
    );
    const button = screen.getByRole("button", { name: "Do it" });
    const icon = screen.getByTestId("ico");
    expect(button.contains(icon)).toBe(true);
    expect(button.textContent).toBe("iDo it");
  });

  it("still forwards an explicit style, so framework callers keep their escape", () => {
    // The sheet owns the base; a one-off geometry override (LoginView's full-width submit)
    // is inline and therefore still wins, which is the boundary ADR 0094 draws between
    // styling policy and a measured value.
    render(<Button style={{ width: "100%" }}>Wide</Button>);
    expect(screen.getByRole("button", { name: "Wide" }).style.width).toBe("100%");
  });
});

