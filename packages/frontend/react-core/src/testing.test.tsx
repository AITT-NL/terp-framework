// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "./ConfirmDialog";
import { installDialogPolyfill } from "./testing";
import { Combobox } from "./ui/Combobox";

afterEach(cleanup);

// The setup file has already installed the polyfill here — the same call a generated app's
// setup file makes — so these tests drive it the way an app's test would: with key events.
// ConfirmDialog's own tests (feedback.test.tsx) dispatch `cancel` by hand to reach its
// handler; whether an Escape ever produces that event is the step this file exists to hold.

function OwnedDialog(props: {
  onOpenChange: (open: boolean) => void;
  isPending?: boolean;
  description?: ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(next) => {
        props.onOpenChange(next);
        setOpen(next);
      }}
      onConfirm={() => {}}
      title="Delete this record?"
      description={props.description}
      isPending={props.isPending}
    />
  );
}

/** A bare dialog in the document, removed again by the caller. */
function bareDialog(): HTMLDialogElement {
  return document.body.appendChild(document.createElement("dialog"));
}

describe("installDialogPolyfill", () => {
  it("dismisses a ConfirmDialog on Escape, through the cancel event a browser fires", () => {
    const onOpenChange = vi.fn();
    render(<OwnedDialog onOpenChange={onOpenChange} />);

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps a pending ConfirmDialog open on Escape, because it cancels that event", () => {
    const onOpenChange = vi.fn();
    render(<OwnedDialog onOpenChange={onOpenChange} isPending />);

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });

    // Closing regardless of the cancel would hide the dialog while its owner still holds it
    // open — a test of the pending guard that could not fail.
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("leaves the dialog open when a control inside it takes the Escape", () => {
    // A Combobox cancels its own Escape to close its option list. That is not a close request
    // in a browser (measured in Chromium), so the first Escape closes the list and only the
    // second reaches the dialog.
    const onOpenChange = vi.fn();
    render(
      <OwnedDialog
        onOpenChange={onOpenChange}
        description={
          <Combobox
            aria-label="Group"
            options={[
              { value: "a", label: "Alpha" },
              { value: "b", label: "Beta" },
            ]}
          />
        }
      />,
    );
    const input = screen.getByRole("combobox", { name: /Group/ });
    fireEvent.focus(input);
    expect(input).toHaveAttribute("aria-expanded", "true");

    fireEvent.keyDown(input, { key: "Escape" });
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.keyDown(input, { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("closes a modal nobody handles on Escape, and on no other key", () => {
    const dialog = bareDialog();
    try {
      const closed = vi.fn();
      dialog.addEventListener("close", closed);
      dialog.showModal();

      fireEvent.keyDown(dialog, { key: "Enter" });
      expect(dialog.open).toBe(true);

      fireEvent.keyDown(dialog, { key: "Escape" });
      expect(dialog.open).toBe(false);
      expect(closed).toHaveBeenCalledTimes(1);
    } finally {
      dialog.remove();
    }
  });

  it("asks only the topmost modal, and skips one that has left the document", () => {
    const lower = bareDialog();
    const upper = bareDialog();
    try {
      const asked: string[] = [];
      lower.addEventListener("cancel", () => asked.push("lower"));
      upper.addEventListener("cancel", () => asked.push("upper"));
      lower.showModal();
      upper.showModal();

      fireEvent.keyDown(document.body, { key: "Escape" });
      expect(asked).toEqual(["upper"]);
      expect(lower.open).toBe(true);

      // Opened again and then removed while open. A browser takes it out of the top layer with
      // the removal (measured in Chromium), so the next Escape belongs to the one beneath.
      upper.showModal();
      upper.remove();
      fireEvent.keyDown(document.body, { key: "Escape" });
      expect(asked).toEqual(["upper", "lower"]);
      expect(lower.open).toBe(false);
    } finally {
      lower.remove();
      upper.remove();
    }
  });

  it("stands aside where the environment already implements showModal", () => {
    const proto = HTMLDialogElement.prototype;
    const installed = { showModal: proto.showModal, close: proto.close };
    const native = {
      showModal: function showModal() {},
      close: function close() {},
    };
    proto.showModal = native.showModal;
    proto.close = native.close;
    try {
      installDialogPolyfill();
      expect(proto.showModal).toBe(native.showModal);
      expect(proto.close).toBe(native.close);
    } finally {
      proto.showModal = installed.showModal;
      proto.close = installed.close;
    }
  });
});
