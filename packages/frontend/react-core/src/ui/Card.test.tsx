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
    expect(card.style.border).toContain("var(--color-neutral-200)");
    expect(card.style.background).toContain("var(--color-neutral-0)");
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
});
