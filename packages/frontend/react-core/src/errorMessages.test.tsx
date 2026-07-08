// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ErrorState } from "./ErrorState";
import { ErrorMessagesProvider, useErrorMessage } from "./errorMessages";
import { UiTextProvider } from "./uiText";
import { ApiError } from "./unwrap";

afterEach(cleanup);

function Probe({ error }: { error: unknown }) {
  const messageForCode = useErrorMessage();
  return <output>{messageForCode(error) ?? "(none)"}</output>;
}

describe("useErrorMessage", () => {
  it("maps a known code to the default client-owned copy", () => {
    render(<Probe error={new ApiError("backend detail", { code: "stale_data", status: 409 })} />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "This item was changed by someone else. Refresh and try again.",
    );
  });

  it("returns null for unknown codes and non-envelope errors", () => {
    render(
      <>
        <Probe error={new ApiError("backend detail", { code: "freight_locked", status: 409 })} />
        <Probe error={new Error("plain")} />
        <Probe error="boom" />
      </>,
    );

    for (const status of screen.getAllByRole("status")) {
      expect(status).toHaveTextContent("(none)");
    }
  });

  it("lets nested providers override and extend the map, resolving UiText descriptors", () => {
    render(
      <ErrorMessagesProvider
        messages={{
          stale_data: { id: "errors.stale", message: "Someone edited this. Reload." },
        }}
      >
        <ErrorMessagesProvider messages={{ freight_locked: "This freight is locked." }}>
          <Probe error={new ApiError("x", { code: "stale_data", status: 409 })} />
          <Probe error={new ApiError("x", { code: "freight_locked", status: 409 })} />
        </ErrorMessagesProvider>
      </ErrorMessagesProvider>,
    );

    const statuses = screen.getAllByRole("status");
    expect(statuses[0]).toHaveTextContent("Someone edited this. Reload.");
    expect(statuses[1]).toHaveTextContent("This freight is locked.");
  });
});

describe("ErrorState with coded errors", () => {
  it("prefers the mapped message over the backend detail for known codes", () => {
    render(
      <ErrorState
        error={new ApiError("Backend-produced detail.", { code: "permission_denied", status: 403 })}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "You do not have permission to do this.",
    );
    expect(screen.queryByText("Backend-produced detail.")).not.toBeInTheDocument();
  });

  it("falls back to the backend detail for unknown codes", () => {
    render(
      <UiTextProvider>
        <ErrorState error={new ApiError("Module-specific detail.", { code: "freight_locked", status: 409 })} />
      </UiTextProvider>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Module-specific detail.");
  });
});
