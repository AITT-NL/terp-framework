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

  it("names a non-default size and leaves the standard control unmarked", () => {
    // md is the absence of an attribute, because the standard control's geometry IS the base
    // rule — the shape density already uses, where "comfortable" matches no rule either. So
    // this asserts the absence as deliberately as it asserts the presence: stamping
    // data-size="md" would be harmless but would make the sheet's two-rule split read as an
    // omission.
    const { rerender } = render(<Button size="sm">Small</Button>);
    expect(screen.getByRole("button", { name: "Small" })).toHaveAttribute("data-size", "sm");
    rerender(<Button size="lg">Large</Button>);
    expect(screen.getByRole("button", { name: "Large" })).toHaveAttribute("data-size", "lg");
    rerender(<Button>Standard</Button>);
    const standard = screen.getByRole("button", { name: "Standard" });
    expect(standard.hasAttribute("data-size")).toBe(false);
    expect(standard.getAttribute("style")).toBeNull();
  });

  it("fills its container from an attribute rather than an inline width", () => {
    // The point of the prop: `style={{ width: "100%" }}` is the only other way there, and app
    // modules may not write it (ADR 0059) — so full width was a shape the framework could
    // produce and its consumers could not ask for. The absence of a style attribute is the
    // half that matters, because an inline width would outrank the app theme.css that ADR 0094
    // exists to empower.
    render(<Button fullWidth>Wide</Button>);
    const button = screen.getByRole("button", { name: "Wide" });
    expect(button).toHaveAttribute("data-full-width", "true");
    expect(button.getAttribute("style")).toBeNull();
  });

  it("marks a loading button busy, disables it, and shows the spinner in the icon slot", () => {
    render(
      <Button loading icon={<span data-testid="ico">i</span>}>
        Saving
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Saving" });
    expect(button).toHaveAttribute("data-loading", "true");
    expect(button).toHaveAttribute("aria-busy", "true");
    // Disabled, so a second click cannot start the same request twice — the reason the state
    // exists at all rather than being decoration on a still-live control.
    expect(button).toBeDisabled();
    // The spinner REPLACES the icon rather than joining it, so the button's width does not
    // jump as it enters and leaves the state.
    expect(screen.queryByTestId("ico")).toBeNull();
    expect(button.querySelector('[data-terp="spinner-ring"]')).not.toBeNull();
    expect(button.getAttribute("style")).toBeNull();
  });

  it("keeps a loading button disabled even when the caller says otherwise", () => {
    // `disabled={false}` and `loading` together is a real combination — a form that computes
    // one from validity and the other from the request in flight — and the request has to
    // win, or the state is advisory.
    render(
      <Button loading disabled={false}>
        Saving
      </Button>,
    );
    expect(screen.getByRole("button", { name: "Saving" })).toBeDisabled();
  });

  it("still forwards an explicit style, so framework callers keep their escape", () => {
    // The sheet owns the base, and the escape still has to work: a caller may pass a measured
    // value the sheet has no business owning, and it wins because a style attribute outranks
    // any author rule (ADR 0094 §3).
    //
    // This comment has now cited three different homes for the same 100%, which is the useful
    // part of it. First it was LoginView's inline style. Then a rule on the login form's group,
    // because a fixed 100% is layout policy rather than a measured value and the sheet could
    // reach it — with a prop declined as API the package did not need for one internal caller.
    // Now it is `fullWidth`, because the constraint that mattered was never the internal caller:
    // app modules may not write `style` at all, so full width was a shape the framework could
    // produce and its consumers could not ask for. The group rule is gone and LoginView passes
    // the prop. The escape below is unaffected either way, which is why it is still here.
    render(<Button style={{ width: "100%" }}>Wide</Button>);
    expect(screen.getByRole("button", { name: "Wide" }).style.width).toBe("100%");
  });
});

