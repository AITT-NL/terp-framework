import { createContext, useCallback, useContext, useMemo } from "react";
import type { ReactNode } from "react";

import { useStrings, useUiText } from "./uiText";
import type { TerpStrings, UiText } from "./uiText";

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
 * The wording for the core `AppError` taxonomy, read from the active locale.
 *
 * These were an exported map of English strings, the context's default value, so a plain
 * string resolved as-is and a `permission_denied` read "You do not have permission to do this."
 * under every locale — while the Dutch catalog was reported complete, because the check walks
 * `TerpStrings` and these were not in it. They are `errorCode*` keys of that table now, so a
 * locale catalog translates them and a non-English one that leaves one out is refused.
 */
function builtInErrorMessages(strings: TerpStrings): ErrorMessages {
  return {
    bad_request: strings.errorCodeBadRequest,
    validation_failed: strings.errorCodeValidationFailed,
    invalid_token: strings.errorCodeInvalidToken,
    authentication_required: strings.errorCodeAuthenticationRequired,
    permission_denied: strings.errorCodePermissionDenied,
    not_found: strings.errorCodeNotFound,
    conflict: strings.errorCodeConflict,
    stale_data: strings.errorCodeStaleData,
  };
}

/** The app's own map only; the built-in wording is read from the locale at every use. */
const ErrorMessagesContext = createContext<ErrorMessages>({});

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
  const appMessages = useContext(ErrorMessagesContext);
  const strings = useStrings();
  const resolve = useUiText();
  // The app's map over the built-in wording, so an app still overrides a platform code.
  const messages = useMemo(
    () => ({ ...builtInErrorMessages(strings), ...appMessages }),
    [strings, appMessages],
  );
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
