import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

import { Icon } from "./icons";
import { useStrings, useUiText } from "./uiText";
import type { UiText } from "./uiText";

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

const viewportStyle: CSSProperties = {
  position: "fixed",
  bottom: "var(--space-4)",
  right: "var(--space-4)",
  display: "grid",
  gap: "var(--space-2)",
  zIndex: 100,
  maxWidth: "min(22.5rem, calc(100vw - 2 * var(--space-4)))",
};

const toastStyle = (variant: ToastVariant): CSSProperties => ({
  display: "grid",
  gridTemplateColumns: "auto 1fr auto",
  alignItems: "start",
  gap: "var(--space-2)",
  padding: "var(--space-3) var(--space-4)",
  borderRadius: "var(--radius-md)",
  border: `1px solid ${borderColor[variant]}`,
  borderInlineStart: `3px solid ${titleColor[variant]}`,
  background: "var(--color-neutral-0)",
  color: "var(--color-neutral-900)",
  fontSize: "var(--font-size-sm)",
  boxShadow: "var(--shadow-md)",
});

const titleColor: Record<ToastVariant, string> = {
  success: "var(--color-status-success)",
  error: "var(--color-status-danger)",
  warning: "var(--color-status-warning)",
};

const borderColor: Record<ToastVariant, string> = {
  success: "var(--color-status-success-soft)",
  error: "var(--color-status-danger-soft)",
  warning: "var(--color-status-warning-soft)",
};

const iconName: Record<ToastVariant, string> = {
  success: "check",
  error: "x",
  warning: "bell",
};

const iconWrapStyle = (variant: ToastVariant): CSSProperties => ({
  color: titleColor[variant],
  display: "inline-flex",
  alignItems: "center",
  paddingTop: "2px",
});

const dismissStyle: CSSProperties = {
  border: "none",
  background: "none",
  padding: "var(--space-1)",
  cursor: "pointer",
  color: "var(--color-neutral-500)",
  fontSize: "var(--font-size-base)",
  lineHeight: 1,
  borderRadius: "var(--radius-sm)",
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
    <div role={toast.variant === "success" ? "status" : "alert"} style={toastStyle(toast.variant)}>
      <span aria-hidden="true" style={iconWrapStyle(toast.variant)}>
        <Icon name={iconName[toast.variant]} size="1.1rem" />
      </span>
      <div style={{ display: "grid", gap: "var(--space-1)" }}>
        <strong
          style={{
            color: titleColor[toast.variant],
            fontWeight: "var(--font-weight-semibold)" as never,
          }}
        >
          {resolve(toast.title ?? defaultTitle[toast.variant])}
        </strong>
        {toast.description !== null && toast.description !== undefined && (
          <div>{toast.description}</div>
        )}
      </div>
      <button
        type="button"
        data-terp="iconbutton"
        aria-label={strings.dismiss}
        style={dismissStyle}
        onClick={onDismiss}
      >
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
        <div style={viewportStyle}>
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
