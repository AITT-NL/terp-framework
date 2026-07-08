import { useEffect, useId, useRef } from "react";
import type { CSSProperties, ReactNode } from "react";

import { Button } from "./ui/Button";
import { injectTerpStyles } from "./styles";
import { useStrings, useUiText } from "./uiText";
import type { UiText } from "./uiText";

injectTerpStyles();

export interface ConfirmDialogProps {
  /** Whether the dialog is shown (controlled). */
  open: boolean;
  /** Called with `false` when the user dismisses (cancel, backdrop click, Escape). */
  onOpenChange: (open: boolean) => void;
  /** Called when the user confirms. The caller closes the dialog when the action settles. */
  onConfirm: () => void;
  /** Short question — what is about to happen. */
  title: UiText;
  /** Optional consequence explanation. */
  description?: ReactNode;
  /** Confirm-button label; defaults to the `confirm` string. */
  confirmLabel?: UiText;
  /** Cancel-button label; defaults to the `cancel` string. */
  cancelLabel?: UiText;
  /** Style the confirm button as destructive (delete / remove / deactivate). */
  destructive?: boolean;
  /** Keep the dialog inert while the confirmed action is in flight: disables both
   * buttons and blocks Escape / backdrop dismissal until the action settles. */
  isPending?: boolean;
}

const dialogStyle: CSSProperties = {
  width: "100%",
  maxWidth: "26rem",
  padding: 0,
  border: "1px solid var(--color-neutral-200)",
  borderRadius: "var(--radius-lg)",
  boxShadow: "var(--shadow-lg)",
  background: "var(--color-neutral-0)",
  color: "var(--color-neutral-900)",
};

const bodyStyle: CSSProperties = {
  display: "grid",
  gap: "var(--space-3)",
  padding: "var(--space-6)",
};

const dialogTitleStyle: CSSProperties = {
  margin: 0,
  fontSize: "var(--font-size-lg)",
  fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"],
  letterSpacing: "-0.01em",
  color: "var(--color-neutral-900)",
};

const descriptionStyle: CSSProperties = {
  color: "var(--color-neutral-600)",
  fontSize: "var(--font-size-sm)",
  lineHeight: 1.5,
};

const footerStyle: CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  gap: "var(--space-2)",
  marginTop: "var(--space-2)",
};

/**
 * The shared confirmation dialog — replaces `window.confirm()` with an accessible,
 * token-styled modal. Use it before any destructive or irreversible action (delete,
 * remove, deactivate), with `destructive` marking the confirm button.
 *
 * Built on the native `<dialog>` element via `showModal()`, so the platform provides
 * the modal contract for free: initial focus, focus trapping, focus restore to the
 * opener, Escape handling, and top-layer rendering (never clipped by ancestor
 * overflow/transform, always above toasts). Dismissal is possible via the cancel
 * button, backdrop click, or Escape — except while `isPending`, which keeps the
 * dialog inert until the confirmed action settles. The element stays mounted while
 * closed (hidden by the UA `dialog:not([open])` rule) so closing goes through
 * `close()` — the step that restores focus to the opener.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  onConfirm,
  title,
  description,
  confirmLabel,
  cancelLabel,
  destructive,
  isPending,
}: ConfirmDialogProps) {
  const strings = useStrings();
  const resolve = useUiText();
  const titleId = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null) {
      return;
    }
    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    // The top layer blocks interaction with the page but not scrolling behind it.
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      data-terp="dialog"
      aria-labelledby={titleId}
      style={dialogStyle}
      onCancel={(event) => {
        // Escape: stay controlled — never let the platform close the element itself.
        event.preventDefault();
        if (isPending !== true) {
          onOpenChange(false);
        }
      }}
      onClick={(event) => {
        // A click on the backdrop targets the <dialog> element itself.
        if (event.target === dialogRef.current && isPending !== true) {
          onOpenChange(false);
        }
      }}
    >
      <div style={bodyStyle}>
        <h2 id={titleId} style={dialogTitleStyle}>
          {resolve(title)}
        </h2>
        {description !== undefined && (
          <div style={descriptionStyle}>{description}</div>
        )}
        <div style={footerStyle}>
          <Button variant="secondary" disabled={isPending} onClick={() => onOpenChange(false)}>
            {resolve(cancelLabel ?? strings.cancel)}
          </Button>
          <Button
            variant={destructive ? "danger" : "primary"}
            disabled={isPending}
            onClick={onConfirm}
          >
            {resolve(confirmLabel ?? strings.confirm)}
          </Button>
        </div>
      </div>
    </dialog>
  );
}
