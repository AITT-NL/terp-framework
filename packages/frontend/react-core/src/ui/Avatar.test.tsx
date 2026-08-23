// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Avatar, userInitials } from "./Avatar";

afterEach(cleanup);

describe("Avatar", () => {
  it("derives initials from an email's local part", () => {
    expect(userInitials("jane.doe@example.com")).toBe("JD");
    expect(userInitials("admin@example.test")).toBe("A");
    expect(userInitials("@example.test")).toBe("?");
  });

  it("takes explicit initials over anything it would have derived", () => {
    render(<Avatar from="jane.doe@example.com" initials="ZZ" />);
    expect(screen.getByText("ZZ")).toBeInTheDocument();
    expect(screen.queryByText("JD")).toBeNull();
  });

  it("stamps a size attribute for sm and none for the default", () => {
    // The same bargain as every other sized component: md IS the base rule, so an attribute for it
    // would leave two places describing the standard tile. The sheet gate asserts the converse —
    // that no `[data-size="md"]` rule exists — and this asserts the component never emits one.
    const { container, rerender } = render(<Avatar from="a.b@example.com" />);
    const tile = () => container.querySelector('[data-terp="avatar"]');
    expect(tile()).not.toBeNull();
    expect(tile()).not.toHaveAttribute("data-size");
    rerender(<Avatar from="a.b@example.com" size="md" />);
    expect(tile()).not.toHaveAttribute("data-size");
    rerender(<Avatar from="a.b@example.com" size="sm" />);
    expect(tile()).toHaveAttribute("data-size", "sm");
  });

  it("is hidden from assistive tech, because the name it abbreviates is rendered beside it", () => {
    // Announcing "JD" before "jane.doe@example.com" is a puzzle rather than information, and both
    // callers render the full identity next to the tile.
    render(<Avatar from="jane.doe@example.com" />);
    expect(screen.getByText("JD")).toHaveAttribute("aria-hidden", "true");
  });
});
