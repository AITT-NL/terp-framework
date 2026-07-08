// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Button } from "./Button";

afterEach(cleanup);

describe("Button", () => {
  it("renders an accessible button with a default type and token styling", () => {
    render(<Button>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveAttribute("data-terp", "button");
    expect(button).toHaveAttribute("data-variant", "primary");
    expect(button.style.background).toContain("var(--color-brand-primary)");
  });

  it("renders the ghost variant with a transparent background", () => {
    render(<Button variant="ghost">Cancel</Button>);
    const button = screen.getByRole("button", { name: "Cancel" });
    expect(button).toHaveAttribute("data-variant", "ghost");
    expect(button.style.background).toBe("transparent");
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
});

