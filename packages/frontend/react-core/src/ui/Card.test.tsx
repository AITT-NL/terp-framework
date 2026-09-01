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

  it("keeps the actions slot a sibling of the heading, description or not", () => {
    // The DOM half of a defect whose visible half was CSS. `actions` is documented as a slot in
    // the header ROW, and it stopped being one the moment `description` was set: the heading was
    // sized from its content, a block holding a title and a sentence is as wide as the sentence,
    // and flex breaks lines on that width before it shrinks anything — so the header wrapped and
    // the control landed underneath. Measured 103px against 48px for the same component one prop
    // apart.
    //
    // What the sheet's fix needs from the markup is exactly this shape: the description inside
    // the heading (so :has() can find it and so the two lines stay one block) and the actions
    // slot OUTSIDE it, as a sibling. Nesting the slot in the heading, or lifting the description
    // out of it, would each render plausibly and defeat the rule silently — which is why this is
    // asserted structurally rather than left to a screenshot.
    for (const description of [undefined, "Wat dit blok beschrijft."]) {
      cleanup();
      render(
        <Card
          title="Projecten"
          description={description}
          actions={<button type="button">Nieuw</button>}
        >
          inhoud
        </Card>,
      );
      const header = screen
        .getByRole("heading", { level: 3, name: "Projecten" })
        .closest('[data-terp="card-header"]') as HTMLElement;
      const heading = header.querySelector('[data-terp="card-heading"]') as HTMLElement;
      const actions = header.querySelector('[data-terp="card-actions"]') as HTMLElement;
      expect(actions.parentElement, "the actions slot is the heading's sibling").toBe(header);
      expect(heading.contains(actions)).toBe(false);
      expect(
        heading.querySelector('[data-terp="card-description"]') !== null,
        "the description lives inside the heading, which is what the :has() rule reads",
      ).toBe(description !== undefined);
    }
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
