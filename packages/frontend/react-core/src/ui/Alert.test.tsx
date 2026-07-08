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
});
