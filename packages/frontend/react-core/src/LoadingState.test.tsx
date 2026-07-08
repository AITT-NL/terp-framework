// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { InlineSpinner, LoadingState } from "./LoadingState";
import { UiTextProvider } from "./uiText";

afterEach(cleanup);

describe("LoadingState", () => {
  it("is a status region with the default loading label", () => {
    render(<LoadingState />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading...");
  });

  it("resolves an explicit UiText label and honours string overrides", () => {
    render(
      <UiTextProvider strings={{ loading: "Laden…" }}>
        <LoadingState />
        <LoadingState label={{ id: "tasks.loading", message: "Loading tasks…" }} />
      </UiTextProvider>,
    );

    const statuses = screen.getAllByRole("status");
    expect(statuses[0]).toHaveTextContent("Laden…");
    expect(statuses[1]).toHaveTextContent("Loading tasks…");
  });
});

describe("InlineSpinner", () => {
  it("renders a decorative svg hidden from assistive tech", () => {
    const { container } = render(<InlineSpinner size={24} />);

    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("width", "24");
  });
});
