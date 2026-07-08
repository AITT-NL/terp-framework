// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "./ConfirmDialog";
import { EmptyState } from "./EmptyState";
import { describeError, ErrorState } from "./ErrorState";
import { UiTextProvider } from "./uiText";
import { Button } from "./ui/Button";

afterEach(cleanup);

describe("EmptyState", () => {
  it("renders title, description, and the action slot", () => {
    render(
      <EmptyState
        title="No tasks yet"
        description="Create your first task to get going."
        action={<Button>New task</Button>}
      />,
    );

    expect(screen.getByText("No tasks yet")).toBeInTheDocument();
    expect(screen.getByText("Create your first task to get going.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New task" })).toBeInTheDocument();
  });
});

describe("describeError", () => {
  it("derives a message from Errors, envelope objects, and strings", () => {
    expect(describeError(new Error("task not found"))).toBe("task not found");
    expect(describeError({ detail: "task not found", code: "not_found" })).toBe(
      "task not found",
    );
    expect(describeError({ code: "not_found" })).toBe("not_found");
    expect(describeError("boom")).toBe("boom");
    expect(describeError(42)).toBeNull();
    expect(describeError(null)).toBeNull();
  });
});

describe("ErrorState", () => {
  it("is an alert with a default title and the derived error message", () => {
    render(<ErrorState error={new Error("task not found")} />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong.");
    expect(alert).toHaveTextContent("task not found");
  });

  it("prefers an explicit description and localises the title", () => {
    render(
      <UiTextProvider strings={{ errorTitle: "Er ging iets mis." }}>
        <ErrorState description="Try again later." error={new Error("ignored")} />
      </UiTextProvider>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Er ging iets mis.");
    expect(screen.getByText("Try again later.")).toBeInTheDocument();
    expect(screen.queryByText("ignored")).not.toBeInTheDocument();
  });
});

describe("ConfirmDialog", () => {
  it("is closed (not modal) while open is false", () => {
    render(
      <ConfirmDialog open={false} onOpenChange={() => {}} onConfirm={() => {}} title="Delete?" />,
    );
    // The element stays mounted (so closing runs close(), which restores opener focus)
    // but is not shown: no `open` attribute means the UA hides it.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes via close() when open flips back to false", () => {
    const { rerender } = render(
      <ConfirmDialog open onOpenChange={() => {}} onConfirm={() => {}} title="Delete?" />,
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    rerender(
      <ConfirmDialog open={false} onOpenChange={() => {}} onConfirm={() => {}} title="Delete?" />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("confirms and cancels through the labelled buttons", () => {
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        onConfirm={onConfirm}
        title="Delete this task?"
        description="This cannot be undone."
        destructive
      />,
    );

    expect(screen.getByRole("dialog", { name: "Delete this task?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("dismisses on Escape (native cancel) while idle", () => {
    const onOpenChange = vi.fn();
    render(
      <ConfirmDialog open onOpenChange={onOpenChange} onConfirm={() => {}} title="Delete?" />,
    );

    const dialog = screen.getByRole("dialog");
    const cancelEvent = new Event("cancel", { cancelable: true });
    fireEvent(dialog, cancelEvent);
    expect(cancelEvent.defaultPrevented).toBe(true);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("blocks Escape and backdrop dismissal and disables buttons while pending", () => {
    const onOpenChange = vi.fn();
    render(
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        onConfirm={() => {}}
        title="Delete?"
        isPending
      />,
    );

    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    const dialog = screen.getByRole("dialog");
    fireEvent(dialog, new Event("cancel", { cancelable: true }));
    fireEvent.click(dialog);
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("dismisses on backdrop click while idle, but not on clicks inside the panel", () => {
    const onOpenChange = vi.fn();
    render(
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        onConfirm={() => {}}
        title="Delete?"
        description="Body copy"
      />,
    );

    fireEvent.click(screen.getByText("Body copy"));
    expect(onOpenChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("dialog"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("locks body scroll while open and restores it on close", () => {
    const { rerender } = render(
      <ConfirmDialog open onOpenChange={() => {}} onConfirm={() => {}} title="Delete?" />,
    );
    expect(document.body.style.overflow).toBe("hidden");
    rerender(
      <ConfirmDialog open={false} onOpenChange={() => {}} onConfirm={() => {}} title="Delete?" />,
    );
    expect(document.body.style.overflow).toBe("");
  });
});
