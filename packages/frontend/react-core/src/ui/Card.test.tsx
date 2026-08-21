// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Card } from "./Card";

afterEach(cleanup);

describe("Card", () => {
  it("renders a bordered token-styled section with a semantic h3 title", () => {
    render(
      <Card title="Bezetting per persoon" description="Uren per maand.">
        <p>body</p>
      </Card>,
    );
    const heading = screen.getByRole("heading", { level: 3, name: "Bezetting per persoon" });
    expect(heading).toBeInTheDocument();
    const card = heading.closest('[data-terp="card"]') as HTMLElement;
    expect(card.tagName).toBe("SECTION");
    // The surface is a sheet rule (ADR 0094); the card's own claims are its element, its
    // gap step and that the title is a real h3 inside the header row.
    expect(card.getAttribute("style")).toBeNull();
    expect(card).toHaveAttribute("data-gap", "3");
    expect(heading).toHaveAttribute("data-terp", "card-title");
    expect(heading.closest('[data-terp="card-header"]')).not.toBeNull();
    expect(screen.getByText("Uren per maand.")).toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();
  });

  it("renders the actions slot in the header row", () => {
    render(
      <Card title="Projecten" actions={<button type="button">Nieuw</button>}>
        inhoud
      </Card>,
    );
    expect(screen.getByRole("button", { name: "Nieuw" })).toBeInTheDocument();
  });

  it("renders headerless with children only", () => {
    render(<Card>alleen inhoud</Card>);
    const card = screen.getByText("alleen inhoud").closest('[data-terp="card"]');
    expect(card?.querySelector('[data-terp="card-header"]')).toBeNull();
  });
  it("names the plain variant and leaves the boxed default unmarked", () => {
    // The chrome-less titled region. A variant rather than a `Section` component of its own,
    // because a chrome-less region is this element with three declarations removed — a second
    // component would have meant six more markers describing the same DOM, and a `Surface` is
    // a Card with no title, which this already is.
    const { rerender } = render(<Card variant="plain" title="Plain">body</Card>);
    const plain = screen.getByRole("heading", { name: "Plain" }).closest("section");
    expect(plain).toHaveAttribute("data-variant", "plain");
    rerender(<Card title="Boxed">body</Card>);
    const boxed = screen.getByRole("heading", { name: "Boxed" }).closest("section");
    expect(boxed!.hasAttribute("data-variant")).toBe(false);
    expect(boxed!.getAttribute("style")).toBeNull();
  });
});
