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

  it("splits a NAME on whitespace, which is the other half of what `from` documents", () => {
    // The prop and the README both say "an email or a name". The split had no whitespace class, so
    // a name produced one letter — a documented input with an undocumented answer.
    expect(userInitials("Jane Doe")).toBe("JD");
    expect(userInitials("ada lovelace king")).toBe("AL");
    // And an email still behaves exactly as before.
    expect(userInitials("jane.doe@example.com")).toBe("JD");
  });

  it("treats an empty string as absent on both props", () => {
    // `??` only catches null and undefined, so an empty override painted a blank tile — which
    // reads as a loading state rather than as "no initials".
    const { container, rerender } = render(<Avatar from="jane.doe@example.com" initials="" />);
    const tile = () => container.querySelector('[data-terp="avatar"]');
    expect(tile()).toHaveTextContent("JD");
    rerender(<Avatar from="" />);
    expect(tile()).toHaveTextContent("?");
    rerender(<Avatar />);
    expect(tile()).toHaveTextContent("?");
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
