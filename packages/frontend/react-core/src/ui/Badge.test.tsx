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
});
