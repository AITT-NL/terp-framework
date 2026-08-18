// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ICON_GLYPHS, NavIcon, TerpMark } from "./icons";

afterEach(cleanup);

describe("NavIcon", () => {
  it("renders the named glyph as decorative svg", () => {
    const { container } = render(<NavIcon name="users" label="Users" />);
    const slot = container.querySelector('[data-terp="nav-icon"]');
    const svg = container.querySelector("svg");
    // The rail slot's fixed 1.25rem box is a sheet rule now (ADR 0094); what this test
    // owns is that the named glyph resolved and stayed decorative.
    expect(slot).not.toBeNull();
    expect(slot?.getAttribute("style")).toBeNull();
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute("aria-hidden", "true");
  });

  it("falls back to the label's initial for an unknown or missing name", () => {
    const { container } = render(<NavIcon name="no-such-glyph" label="widgets" />);
    expect(screen.getByText("W")).toBeInTheDocument();
    // The fallback tile is its own marker, so the rail can style "an initial in a tile"
    // separately from "a glyph" — which is the distinction a theme cares about.
    expect(
      container.querySelector('[data-terp="nav-icon-fallback"]'),
      "the initial renders in the fallback tile",
    ).not.toBeNull();
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
