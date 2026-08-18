import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { Icon } from "./icons";
import { injectTerpStyles } from "./styles";
import { useStrings, useUiText } from "./uiText";
import type { UiText } from "./uiText";

injectTerpStyles();

export type ToastVariant = "success" | "error" | "warning";

export interface ToastOptions {
  /** Override the variant's default title string. */
  title?: UiText;
  /** Auto-dismiss delay in milliseconds; default 5000. */
  durationMs?: number;
}

/** Imperative toast API returned by {@link useToast}. */
export interface ToastApi {
  /** Confirmation after a mutation settles ("Task created."). */
  success: (description: ReactNode, options?: ToastOptions) => void;
  /** Failure of a background or submitted action. */
  error: (description: ReactNode, options?: ToastOptions) => void;
  /** Non-blocking caution ("Some rows were skipped."). */
  warning: (description: ReactNode, options?: ToastOptions) => void;
}

interface ToastItem {
  id: number;
  variant: ToastVariant;
  title: UiText | undefined;
  description: ReactNode;
  durationMs: number;
}

const ToastContext = createContext<ToastApi | null>(null);

const DEFAULT_DURATION_MS = 5000;

const iconName: Record<ToastVariant, string> = {
  success: "check",
  error: "x",
  warning: "bell",
};

/**
 * The `data-tone` value each variant paints as.
 *
 * `data-tone` rather than `data-variant`, because a toast's success/error/warning IS a status
 * tone and `Badge` and `Alert` already key theirs that way — an app restyling one tone should
 * not have to learn two attribute names for the same idea. The one translation is `error` to
 * `danger`: the shared tone vocabulary is {neutral, info, success, warning, danger}, and
 * admitting a fourth synonym to it would mean `[data-terp="toast"][data-tone="danger"]`
 * silently matching nothing for someone who reasoned by analogy from the alert. The mapping is
 * not new indirection either — the component already resolved `error` to
 * `--color-status-danger` for its colours; this states it once instead.
 *
 * `toast.error()` is unchanged: the method name is the API, and this is the DOM.
 */
const toneOf: Record<ToastVariant, string> = {
  success: "success",
  error: "danger",
  warning: "warning",
};

function ToastCard({ toast, onDismiss }: { toast: ToastItem; onDismiss: () => void }) {
  const strings = useStrings();
  const resolve = useUiText();
  const defaultTitle: Record<ToastVariant, string> = {
    success: strings.successTitle,
    error: strings.errorTitle,
    warning: strings.warningTitle,
  };
  return (
    <div
      role={toast.variant === "success" ? "status" : "alert"}
      data-terp="toast"
      data-tone={toneOf[toast.variant]}
    >
      <span aria-hidden="true" data-terp="toast-icon">
        <Icon name={iconName[toast.variant]} size="1.1rem" />
      </span>
      <div data-terp="toast-body">
        <strong data-terp="toast-title">
          {resolve(toast.title ?? defaultTitle[toast.variant])}
        </strong>
        {toast.description !== null && toast.description !== undefined && (
          <div>{toast.description}</div>
        )}
      </div>
      {/* Keeps the shared iconbutton marker and is addressed structurally, the way the
          combobox's clear button and the calendar's month arrows are: it is an icon button,
          and the only thing distinguishing it is where it sits. */}
      <button type="button" data-terp="iconbutton" aria-label={strings.dismiss} onClick={onDismiss}>
        ×
      </button>
    </div>
  );
}

export interface ToastProviderProps {
  children: ReactNode;
}

/**
 * Hosts the toast queue and renders the fixed viewport. `renderTerpApp` mounts
 * one automatically; wrap your tree yourself when composing providers manually.
 * Toasts auto-dismiss (default 5s) and can always be dismissed by hand; success
 * announces politely (`status`), error and warning assertively (`alert`).
 */
export function ToastProvider({ children }: ToastProviderProps) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(0);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (timer !== undefined) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (variant: ToastVariant, description: ReactNode, options?: ToastOptions) => {
      const id = nextId.current++;
      const durationMs = options?.durationMs ?? DEFAULT_DURATION_MS;
      setToasts((current) => [
        ...current,
        { id, variant, title: options?.title, description, durationMs },
      ]);
      timers.current.set(
        id,
        setTimeout(() => dismiss(id), durationMs),
      );
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      success: (description, options) => push("success", description, options),
      error: (description, options) => push("error", description, options),
      warning: (description, options) => push("warning", description, options),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      {toasts.length > 0 && (
        <div data-terp="toast-viewport">
          {toasts.map((toast) => (
            <ToastCard key={toast.id} toast={toast} onDismiss={() => dismiss(toast.id)} />
          ))}
        </div>
      )}
    </ToastContext.Provider>
  );
}

/**
 * The standard transient-feedback channel: call after mutations settle instead
 * of ad-hoc banners or `alert()`. Titles default to the framework strings
 * (`successTitle` / `errorTitle` / `warningTitle`) so feedback reads the same
 * platform-wide. Throws when no {@link ToastProvider} is mounted (fail closed).
 */
export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (api === null) {
    throw new Error("useToast must be used within a <ToastProvider>.");
  }
  return api;
}
