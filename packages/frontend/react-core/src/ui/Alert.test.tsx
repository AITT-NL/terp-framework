// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
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

describe("Alert's actions (ADR 0169 §5)", () => {
  it("renders what to do inside the alert, under its message", () => {
    // The remedy belongs to the alert it answers; a second row beside it left the tint behind.
    render(
      <Alert tone="warning" actions={<button type="button">Revoke</button>}>
        Access to a module that is no longer declared.
      </Alert>,
    );
    const alert = screen.getByRole("alert");
    const actions = alert.querySelector('[data-terp="alert-actions"]')!;
    expect(actions).not.toBeNull();
    expect(within(actions as HTMLElement).getByRole("button", { name: "Revoke" })).toBeInTheDocument();
  });

  it("renders no empty row for actions that render nothing", () => {
    for (const actions of [undefined, null, false] as const) {
      const { unmount } = render(<Alert actions={actions}>A message.</Alert>);
      expect(document.querySelector('[data-terp="alert-actions"]')).toBeNull();
      unmount();
    }
  });
});
