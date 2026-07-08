// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ICON_GLYPHS, NavIcon, TerpMark } from "./icons";

afterEach(cleanup);

describe("NavIcon", () => {
  it("renders the named glyph as decorative svg", () => {
    const { container } = render(<NavIcon name="users" label="Users" />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute("aria-hidden", "true");
  });

  it("falls back to the label's initial for an unknown or missing name", () => {
    render(<NavIcon name="no-such-glyph" label="widgets" />);
    expect(screen.getByText("W")).toBeInTheDocument();
    render(<NavIcon label="records" />);
    expect(screen.getByText("R")).toBeInTheDocument();
  });

  it("ships a stable set of named glyphs", () => {
    for (const name of ["home", "list", "users", "shield", "settings", "audit", "hub"]) {
      expect(ICON_GLYPHS[name], name).toBeDefined();
    }
  });
});

describe("TerpMark", () => {
  it("is a decorative, token-coloured placeholder mark", () => {
    const { container } = render(<TerpMark />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(container.innerHTML).toContain("var(--color-brand-primary)");
  });
});
