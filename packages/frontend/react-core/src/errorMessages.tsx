import { createContext, useCallback, useContext, useMemo } from "react";
import type { ReactNode } from "react";

import { useUiText } from "./uiText";
import type { UiText } from "./uiText";

/**
 * Client-owned messages for the platform's stable error codes.
 *
 * The backend serialises every failure into the uniform envelope
 * `{ code, detail, request_id }`: `code` is a stable machine identifier from
 * the typed `AppError` taxonomy (`terp.core.errors`), `detail` the message the
 * backend produced. Mapping codes to copy here lets the UI evolve (and
 * localise) failure wording without a backend deploy; codes without an entry
 * simply fall back to the backend `detail`, so the map never has to be
 * complete. Values are {@link UiText}, resolved through the UiText seam like
 * every other framework string.
 */
export type ErrorMessages = Record<string, UiText>;

/**
 * English defaults for the core `AppError` taxonomy. Apps override or extend
 * per code via {@link ErrorMessagesProvider} — including codes their own
 * backend modules add.
 */
export const DEFAULT_ERROR_MESSAGES: ErrorMessages = {
  bad_request: "The request could not be processed.",
  validation_failed: "Some fields are invalid. Check the form and try again.",
  invalid_token: "Your session is invalid. Sign in again.",
  authentication_required: "Sign in to continue.",
  permission_denied: "You do not have permission to do this.",
  not_found: "This item could not be found.",
  conflict: "This conflicts with the current state. Refresh and try again.",
  stale_data: "This item was changed by someone else. Refresh and try again.",
};

const ErrorMessagesContext = createContext<ErrorMessages>(DEFAULT_ERROR_MESSAGES);

export interface ErrorMessagesProviderProps {
  /** Per-code overrides and additions, merged over any outer provider's map. */
  messages: ErrorMessages;
  children: ReactNode;
}

/**
 * Override or extend the code→message map for a subtree. Wrap the app once to
 * localise the built-in codes and register module-specific ones; nests, so a
 * module can add its own codes without touching the app shell.
 */
export function ErrorMessagesProvider({ messages, children }: ErrorMessagesProviderProps) {
  const parent = useContext(ErrorMessagesContext);
  const value = useMemo(() => ({ ...parent, ...messages }), [parent, messages]);
  return <ErrorMessagesContext.Provider value={value}>{children}</ErrorMessagesContext.Provider>;
}

/**
 * Resolve a caught failure to display copy: the mapped message for the error's
 * stable `code` when one is registered, else `null` (callers fall back to the
 * error's own message — the backend `detail`). Reads the error's `code`
 * property, as carried by `ApiError` thrown from `unwrap`.
 */
export function useErrorMessage(): (error: unknown) => string | null {
  const messages = useContext(ErrorMessagesContext);
  const resolve = useUiText();
  return useCallback(
    (error: unknown) => {
      if (error === null || typeof error !== "object") {
        return null;
      }
      const { code } = error as { code?: unknown };
      if (typeof code !== "string") {
        return null;
      }
      const message = messages[code];
      return message === undefined ? null : resolve(message);
    },
    [messages, resolve],
  );
}
