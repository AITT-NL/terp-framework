// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Alert } from "./Alert";

afterEach(cleanup);

describe("Alert", () => {
  it("uses status for informational banners", () => {
    render(<Alert title="Saved">All changes persisted.</Alert>);
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
  });

  it("uses alert for dangerous banners", () => {
    render(<Alert tone="danger">Delete failed.</Alert>);
    expect(screen.getByRole("alert")).toHaveTextContent("Delete failed.");
  });

  it("names its tone on the banner, which is what paints the frame and the glyph", () => {
    render(<Alert tone="warning">Check the mapping.</Alert>);
    const banner = screen.getByRole("alert");
    expect(banner).toHaveAttribute("data-tone", "warning");
    expect(banner.getAttribute("style")).toBeNull();
  });

  it("defaults to the info tone", () => {
    render(<Alert>Nothing to do.</Alert>);
    expect(screen.getByRole("status")).toHaveAttribute("data-tone", "info");
  });
});
