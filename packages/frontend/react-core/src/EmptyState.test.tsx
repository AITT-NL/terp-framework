// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { EmptyState } from "./EmptyState";

afterEach(cleanup);

describe("EmptyState size", () => {
  it("stamps no attribute at the default size", () => {
    // The full-page block's geometry IS the base rule, so the default matches no
    // attribute selector — the same shape Button's sizes and the shell's density take.
    render(<EmptyState title="Nothing yet" />);
    expect(screen.getByText("Nothing yet").closest("[data-terp='empty-state']")).not.toHaveAttribute(
      "data-size",
    );
  });

  it("stamps compact, and keeps the frame and the wording", () => {
    // Two default blocks stacked on one screen were 480px of chrome repeating a sentence:
    // the emptiness of one section is not the page's headline. Compact takes the space back
    // without changing what the block says or that it is recognisably an empty state.
    render(
      <EmptyState size="compact" title="No connections" description="Add one to begin." />,
    );
    const block = screen.getByText("No connections").closest("[data-terp='empty-state']");
    expect(block).toHaveAttribute("data-size", "compact");
    expect(screen.getByText("Add one to begin.")).toBeInTheDocument();
  });
});
