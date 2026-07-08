// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider, useToast } from "./toast";
import { UiTextProvider } from "./uiText";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function Trigger() {
  const toast = useToast();
  return (
    <div>
      <button onClick={() => toast.success("Task created.")}>success</button>
      <button onClick={() => toast.error("Save failed.")}>error</button>
      <button onClick={() => toast.warning("Rows skipped.", { durationMs: 1000 })}>
        warning
      </button>
    </div>
  );
}

describe("useToast / ToastProvider", () => {
  it("throws without a provider (fail closed)", () => {
    expect(() => render(<Trigger />)).toThrow(/ToastProvider/);
  });

  it("shows a polite success toast with the default title", () => {
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByText("success"));

    const toast = screen.getByRole("status");
    expect(toast).toHaveTextContent("Success");
    expect(toast).toHaveTextContent("Task created.");
  });

  it("announces error and warning toasts assertively with localisable titles", () => {
    render(
      <UiTextProvider strings={{ errorTitle: "Mislukt", warningTitle: "Waarschuwing" }}>
        <ToastProvider>
          <Trigger />
        </ToastProvider>
      </UiTextProvider>,
    );

    fireEvent.click(screen.getByText("error"));
    fireEvent.click(screen.getByText("warning"));

    const alerts = screen.getAllByRole("alert");
    expect(alerts[0]).toHaveTextContent("Mislukt");
    expect(alerts[0]).toHaveTextContent("Save failed.");
    expect(alerts[1]).toHaveTextContent("Waarschuwing");
    expect(alerts[1]).toHaveTextContent("Rows skipped.");
  });

  it("dismisses via the dismiss button", () => {
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByText("success"));
    fireEvent.click(screen.getByLabelText("Dismiss"));

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("auto-dismisses after the configured duration", () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByText("warning"));
    expect(screen.getByRole("alert")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
