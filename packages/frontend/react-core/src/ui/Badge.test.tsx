// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Badge } from "./Badge";

afterEach(cleanup);

describe("Badge", () => {
  // The tone is asserted as the attribute the sheet keys on, not as a resolved colour
  // (ADR 0094) — which is also the tone DataView reads to tint a row, so the two can
  // never disagree about what "success" means.
  it("names its tone on the pill and carries no inline styling", () => {
    render(<Badge label="Active" tone="success" />);
    const pill = screen.getByText("Active");
    expect(pill).toHaveAttribute("data-terp", "badge");
    expect(pill).toHaveAttribute("data-tone", "success");
    expect(pill.getAttribute("style")).toBeNull();
  });

  it("takes its text as children too, the way every other component does", () => {
    render(<Badge tone="danger">No drift</Badge>);
    expect(screen.getByText("No drift")).toHaveAttribute("data-tone", "danger");
  });

  it("defaults to the neutral tone", () => {
    render(<Badge label="Draft" />);
    expect(screen.getByText("Draft")).toHaveAttribute("data-tone", "neutral");
  });
});
