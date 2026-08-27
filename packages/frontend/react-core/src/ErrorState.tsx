import type { ReactNode } from "react";

import { useErrorMessage } from "./errorMessages";
import { Icon } from "./icons";
import { injectTerpStyles } from "./styles";
import { resolveUiTextNode, useStrings, useUiText } from "./uiText";
import type { UiText, UiTextNode } from "./uiText";

injectTerpStyles();

/**
 * Best-effort human-readable message for a caught failure. `unwrap` already throws
 * `Error`s carrying the backend envelope's `detail`, so most callers just surface
 * `error.message`; raw envelope objects (`detail` / `code`) and plain strings are
 * also understood. Returns `null` when nothing useful can be derived.
 */
export function describeError(error: unknown): string | null {
  if (typeof error === "string" && error.length > 0) {
    return error;
  }
  if (error instanceof Error && error.message.length > 0) {
    return error.message;
  }
  if (error !== null && typeof error === "object") {
    const envelope = error as { detail?: unknown; code?: unknown };
    if (typeof envelope.detail === "string" && envelope.detail.length > 0) {
      return envelope.detail;
    }
    if (typeof envelope.code === "string" && envelope.code.length > 0) {
      return envelope.code;
    }
  }
  return null;
}

export interface ErrorStateProps {
  /** Optional leading visual (any rendered node — react-core takes no icon dependency). */
  icon?: ReactNode;
  /** Short title — what failed. Defaults to the `errorTitle` string. */
  title?: UiText;
  /**
   * Explanation. When omitted and `error` is set, the message is the registered
   * copy for the error's stable `code` (see `useErrorMessage`), falling back to
   * {@link describeError}, so the platform error envelope surfaces consistently.
   */
  description?: UiTextNode;
  /** The caught failure — used to derive `description` when none is given. */
  error?: unknown;
  /** Optional call to action (typically a retry `Button`). */
  action?: ReactNode;
}

/**
 * The standard "something went wrong" block: use whenever a query fails (404 / 403 /
 * network) and the page frame is already rendered. Announced as an `alert` so assistive
 * tech hears the failure; the message comes from the platform error envelope by default,
 * so failures read the same platform-wide. Pairs with `Page`'s `errorState` slot.
 */
export function ErrorState({ icon, title, description, error, action }: ErrorStateProps) {
  const strings = useStrings();
  const resolve = useUiText();
  const messageForCode = useErrorMessage();
  const message =
    description ??
    (error !== undefined ? (messageForCode(error) ?? describeError(error)) : null);
  const leading =
    icon ?? (
      <span data-terp="error-state-icon">
        <Icon name="x" size="1.75rem" />
      </span>
    );
  return (
    <div role="alert" data-terp="error-state">
      {leading}
      <p data-terp="error-state-title">{resolve(title ?? strings.errorTitle)}</p>
      {message !== null && message !== undefined && (
        <div data-terp="error-state-description">
          {resolveUiTextNode(message, resolve)}
        </div>
      )}
      {action}
    </div>
  );
}
