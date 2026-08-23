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
  /**
   * Per-field reasons, keyed by dotted field path (`loc` with FastAPI's `body` / `query` /
   * `path` prefix removed). Empty for every failure that names no field, so
   * `Object.keys(error.fields).length > 0` is the test for "this belongs on the form".
   *
   * What a caller does with it is hand it to `Field`'s `error` prop, which is the whole
   * reason it exists: the framework shipped the rendering half of field-level validation —
   * the marker, the `aria-describedby`, the `aria-invalid`, the styling — and nothing that
   * produces the value. The path was already being computed one function below and joined
   * into a sentence, so the information reached the client and was discarded on arrival.
   */
  readonly fields: Readonly<Record<string, string>>;

  constructor(
    message: string,
    options: {
      code?: string;
      status: number;
      requestId?: string;
      fields?: Readonly<Record<string, string>>;
    },
  ) {
    super(message);
    this.name = "ApiError";
    this.code = options.code;
    this.status = options.status;
    this.requestId = options.requestId;
    // Defaulted and frozen: every caller reads `.fields` without a presence check, and an
    // error's reasons cannot be edited into something the server never said.
    this.fields = Object.freeze({ ...options.fields });
  }
}

/**
 * {@link unwrap} for a resource whose absence is a normal state, not a failure: returns
 * the data on success, `null` on a 404, and throws the same {@link ApiError} for every
 * other failure. The client-side analog of the backend's `BaseService.find` beside
 * `get` — reach for `unwrap` when a missing record ends the request, `unwrapOptional`
 * when "not there yet" is an answer (a `/latest` snapshot that has not been published,
 * an optional singleton). Without it, expressing that state means exception control
 * flow around `unwrap` at every call site.
 */
export function unwrapOptional<T>(result: FetchResult<T>): T | null {
  if (result.response.status === 404) {
    return null;
  }
  return unwrap(result);
}

/** Return the result's `data` on success, or throw an {@link ApiError} describing the failure. */
export function unwrap<T>(result: FetchResult<T>): T {
  if (result.error !== undefined || !result.response.ok) {
    const envelope =
      result.error !== null && typeof result.error === "object"
        ? (result.error as { code?: unknown; request_id?: unknown })
        : {};
    const failure = describeFailure(result.error, result.response);
    throw new ApiError(failure.message, {
      code: typeof envelope.code === "string" ? envelope.code : undefined,
      status: result.response.status,
      requestId: typeof envelope.request_id === "string" ? envelope.request_id : undefined,
      fields: failure.fields,
    });
  }
  return result.data as T;
}

/** A failure's message and its per-field reasons — one value, because one walk produces both. */
interface Failure {
  message: string;
  fields: Record<string, string>;
}

/**
 * Human-readable message for a failed request — envelope `detail`, else `code`, else the
 * status — paired with whatever per-field reasons came with it.
 *
 * The envelope keeps its reasons in two different places depending on who raised the error,
 * and both are read here. A Terp `AppError` puts a sentence in `detail` and its structured
 * reasons in `details` beside it, so the sentence still wins the message. FastAPI's own 422
 * handler makes `detail` *itself* the list — the app registers no `RequestValidationError`
 * override, so that is the shape a schema rejection actually arrives in.
 */
function describeFailure(error: unknown, response: Response): Failure {
  if (error !== null && typeof error === "object") {
    const envelope = error as { detail?: unknown; details?: unknown; code?: unknown };
    // `details` sits beside `detail` rather than replacing it, so its reasons attach to
    // whichever message wins below instead of competing for the slot.
    const reasons = structuredDetail(envelope.details);
    const fields = reasons?.fields ?? {};
    if (typeof envelope.detail === "string" && envelope.detail.length > 0) {
      return { message: envelope.detail, fields };
    }
    const validation = structuredDetail(envelope.detail);
    if (validation !== null) {
      return validation;
    }
    if (typeof envelope.code === "string" && envelope.code.length > 0) {
      return { message: envelope.code, fields };
    }
  }
  return { message: `Request failed (HTTP ${response.status})`, fields: {} };
}

/**
 * The dotted field path a reason addresses, or `""` when it is about the request as a whole.
 *
 * Two spellings arrive and reading only one is how the client stayed half-deaf to its own
 * contract: FastAPI emits `loc` as an array (`["body", "owner", "email"]`), while
 * `terp.core.ErrorDetail` emits it already dotted — a shape whose docstring says it
 * "deliberately mirrors FastAPI's own 422 detail entries ... so a frontend handles both with
 * one branch". Nothing had written that branch. This is it.
 */
function fieldPath(loc: unknown): string {
  if (Array.isArray(loc)) {
    return loc
      .filter((part) => typeof part === "string" || typeof part === "number")
      .filter((part) => part !== "body" && part !== "query" && part !== "path")
      .join(".");
  }
  return typeof loc === "string" ? loc : "";
}

/**
 * Flatten common FastAPI/Pydantic validation details into an agent/user-actionable message,
 * keeping each reason's field alongside it.
 *
 * The message is assembled exactly as before, deliberately: it is what every existing caller
 * shows, and `fields` is additive beside it rather than a replacement for it. A reason with
 * no `loc` therefore still reaches the user through the message, which is the only place it
 * can go — a record keyed by field has no slot for a reason about the request as a whole.
 */
function structuredDetail(detail: unknown): Failure | null {
  if (!Array.isArray(detail)) {
    return null;
  }
  const messages: string[] = [];
  const fields: Record<string, string> = {};
  for (const item of detail) {
    if (item === null || typeof item !== "object") {
      continue;
    }
    const reason = item as { loc?: unknown; msg?: unknown };
    if (typeof reason.msg !== "string" || reason.msg.length === 0) {
      continue;
    }
    const path = fieldPath(reason.loc);
    messages.push(path.length > 0 ? `${path}: ${reason.msg}` : reason.msg);
    // First reason wins per path. A field that fails two checks shows the one the server
    // reported first and keeps the rest in the message; overwriting would show the last,
    // which is no more correct and reads as arbitrary.
    if (path.length > 0 && fields[path] === undefined) {
      fields[path] = reason.msg;
    }
  }
  return messages.length > 0 ? { message: messages.join("; "), fields } : null;
}
