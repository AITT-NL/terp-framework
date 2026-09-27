/**
 * Unit-test support for the components in this package, published at the
 * `@terpjs/react-core/testing` subpath rather than the package root, so none of it arrives in
 * an app's production code through the import every screen already has (ADR 0155). Its two
 * callers are the vitest setup files: this package's own, and the one every generated app
 * ships.
 */

/**
 * Give jsdom enough of the native `<dialog>` modal API for `ConfirmDialog` to open, confirm
 * and dismiss under a unit test the way it does in a browser.
 *
 * jsdom implements the element and its `open` attribute but not `showModal()` or `close()`,
 * and `ConfirmDialog` — the one dialog an app may render — calls both, so without this any
 * test that opens one throws `showModal is not a function`.
 *
 * What it reproduces, each measured against Chromium's own implementation:
 *
 * - `showModal()` sets `open`; `close()` clears it and fires `close`.
 * - **Escape fires a cancelable `cancel` at the topmost open modal, and closes it unless that
 *   event is cancelled.** This is the one that matters: `ConfirmDialog`'s Escape handling
 *   lives in its `cancel` handler, which cancels the event and asks its owner to close —
 *   or, while `isPending`, cancels it and does nothing. Without this, a test pressing
 *   Escape would see nothing happen, and a test of the pending state would pass whether
 *   or not the guard worked.
 * - An Escape `keydown` whose default was prevented is not a close request — so a
 *   `Combobox` inside the dialog, which cancels its own Escape to close its option list,
 *   closes that list and leaves the dialog open, as it does in a browser.
 * - Only the topmost modal is asked, and a modal removed from the document while open has
 *   left the top layer, so it is skipped rather than handed an Escape meant for the one
 *   beneath it.
 *
 * What it does NOT reproduce, so a test must not rely on it: focus (a browser moves focus
 * into the dialog on open and back to the opener on close), inertness of the page behind a
 * modal, the backdrop, and the event timing (`close` fires synchronously here, a task later
 * in a browser). An Escape whose propagation is stopped before it reaches `window` is also
 * missed here, where a browser would still close, and `close()` on a dialog that is not open
 * still fires `close` here, where a browser does nothing. Those belong to the Playwright
 * suite, which runs a real browser.
 *
 * A no-op wherever `HTMLDialogElement` is absent (a node-environment test file sharing the
 * setup file) or already has `showModal` — an environment with a real one owns the whole
 * modal contract, Escape included, and a second implementation beside it would hand every
 * Escape to the dialog twice. Calling it again is therefore harmless.
 */
export function installDialogPolyfill(): void {
  if (typeof HTMLDialogElement === "undefined") {
    return;
  }
  const proto = HTMLDialogElement.prototype as {
    showModal?: (this: HTMLDialogElement) => void;
    close?: (this: HTMLDialogElement) => void;
  };
  if (typeof proto.showModal === "function") {
    return;
  }

  // The top layer, in the order its modals were opened: the last one still in the document
  // is the one Escape reaches. A Set keeps insertion order, and forgetting a dialog that was
  // never shown is a no-op rather than a case to guard.
  const topLayer = new Set<HTMLDialogElement>();

  proto.showModal = function showModal() {
    this.setAttribute("open", "");
    topLayer.add(this);
  };
  proto.close = function close() {
    this.removeAttribute("open");
    topLayer.delete(this);
    this.dispatchEvent(new Event("close"));
  };

  // Bubble phase on `window`, the last stop before a browser's own default handling, so a
  // component inside the dialog that cancels its Escape has already had the chance to.
  window.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.defaultPrevented) {
      return;
    }
    const topmost = [...topLayer].filter((dialog) => dialog.isConnected).at(-1);
    if (topmost?.dispatchEvent(new Event("cancel", { cancelable: true }))) {
      topmost.close();
    }
  });
}
