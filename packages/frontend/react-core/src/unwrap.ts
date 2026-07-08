/**
 * Unwrap an `openapi-fetch` result, throwing on any non-2xx.
 *
 * `openapi-fetch` does **not** throw on an HTTP error status — it returns `{ data, error }`
 * (error carrying the parsed response body). A data hook that reads `.data` alone therefore
 * silently swallows 401 / 403 / 409 / 422 / 500: a failed read shows an empty list, a failed
 * write no-ops. Passing the result through {@link unwrap} makes every failure surface — it
 * throws an {@link ApiError} carrying the backend's error-envelope `detail` (falling back to
 * `code`, then the HTTP status), so a module's `useResource` reports it instead of hiding it.
 */
export interface FetchResult<T> {
  /** The parsed 2xx response body (absent on error / 204). */
  data?: T;
  /** The parsed error-response body (absent on success). */
  error?: unknown;
  /** The raw response, used to detect a non-ok status even when the body did not parse. */
  response: Response;
}

/**
 * A failed request, carrying the machine-readable parts of the platform error
 * envelope alongside the human-readable `message`. The stable `code` lets UI code
 * dispatch on the failure kind (and map it to client-owned copy) without
 * pattern-matching prose; `message` is the backend `detail` fallback.
 */
export class ApiError extends Error {
  /** Stable machine code from the envelope (e.g. `stale_data`), if present. */
  readonly code?: string;
  /** HTTP status of the failed response. */
  readonly status: number;
  /** Correlation id from the envelope, for support and log lookup. */
  readonly requestId?: string;

  constructor(message: string, options: { code?: string; status: number; requestId?: string }) {
    super(message);
    this.name = "ApiError";
    this.code = options.code;
    this.status = options.status;
    this.requestId = options.requestId;
  }
}

/** Return the result's `data` on success, or throw an {@link ApiError} describing the failure. */
export function unwrap<T>(result: FetchResult<T>): T {
  if (result.error !== undefined || !result.response.ok) {
    const envelope =
      result.error !== null && typeof result.error === "object"
        ? (result.error as { code?: unknown; request_id?: unknown })
        : {};
    throw new ApiError(errorMessage(result.error, result.response), {
      code: typeof envelope.code === "string" ? envelope.code : undefined,
      status: result.response.status,
      requestId: typeof envelope.request_id === "string" ? envelope.request_id : undefined,
    });
  }
  return result.data as T;
}

/** Human-readable message for a failed request: envelope `detail`, else `code`, else the status. */
function errorMessage(error: unknown, response: Response): string {
  if (error !== null && typeof error === "object") {
    const envelope = error as { detail?: unknown; code?: unknown };
    if (typeof envelope.detail === "string" && envelope.detail.length > 0) {
      return envelope.detail;
    }
    const structured = structuredDetail(envelope.detail);
    if (structured !== null) {
      return structured;
    }
    if (typeof envelope.code === "string" && envelope.code.length > 0) {
      return envelope.code;
    }
  }
  return `Request failed (HTTP ${response.status})`;
}

/** Flatten common FastAPI/Pydantic validation details into an agent/user-actionable message. */
function structuredDetail(detail: unknown): string | null {
  if (!Array.isArray(detail)) {
    return null;
  }
  const messages = detail
    .map((item) => {
      if (item === null || typeof item !== "object") {
        return null;
      }
      const field = item as { loc?: unknown; msg?: unknown };
      if (typeof field.msg !== "string" || field.msg.length === 0) {
        return null;
      }
      const loc = Array.isArray(field.loc)
        ? field.loc.filter((part) => typeof part === "string" || typeof part === "number")
        : [];
      const path = loc
        .filter((part) => part !== "body" && part !== "query" && part !== "path")
        .join(".");
      return path.length > 0 ? `${path}: ${field.msg}` : field.msg;
    })
    .filter((message): message is string => message !== null);
  return messages.length > 0 ? messages.join("; ") : null;
}
