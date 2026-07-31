// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Badge } from "./Badge";

afterEach(cleanup);

describe("Badge", () => {
  it("renders a token-styled status pill", () => {
    render(<Badge label="Active" tone="success" />);
    expect(screen.getByText("Active").style.color).toContain("var(--color-status-success)");
  });

  it("takes its text as children too, the way every other component does", () => {
    render(<Badge tone="danger">No drift</Badge>);
    expect(screen.getByText("No drift").style.color).toContain("var(--color-status-danger)");
  });
});
