import { ApiError } from "../unwrap";

/** What a form should do with a failure: what to put on inputs, and whether anything is left over. */
export interface RoutedFieldErrors {
  /** Reasons naming a field this form actually renders, ready for `Field`'s `error` prop. */
  shown: Record<string, string>;
  /** At least one reason named something this form has no input for. */
  leftover: boolean;
}

/**
 * Split a failure's per-field reasons into the ones a form can show and the ones it cannot.
 *
 * The naive version of this — "if `fields` is non-empty, set them and return" — has a hole that is
 * invisible until it happens: a reason naming a field the form does not render sets state nobody
 * reads and suppresses the toast on the way out, so the user presses Save and *nothing appears*.
 * No field lights up, no message, no navigation. A failed write that reports nothing is worse than
 * the floating toast this replaced.
 *
 * The packaged forms cannot hit it today, because FastAPI's 422 can only name a key of the body
 * they submitted and they render every one of those. That is a fact about these three endpoints,
 * not about the pattern: a `terp.core.AppError` carrying `details` addresses whatever the rule
 * checked, an app's form is free to submit a field it does not display, and this is the shape apps
 * copy. `GroupDetail` already had it right by naming its one key and falling through to the toast
 * when the server named a different one; this is that discipline, for a form with several.
 *
 * Not exported from the package. It becomes public API when something outside `admin/` needs it.
 */
export function routeFieldErrors(
  error: unknown,
  rendered: readonly string[],
): RoutedFieldErrors {
  const shown: Record<string, string> = {};
  let leftover = false;
  if (error instanceof ApiError) {
    for (const [key, message] of Object.entries(error.fields)) {
      if (rendered.includes(key)) {
        shown[key] = message;
      } else {
        leftover = true;
      }
    }
  }
  return { shown, leftover };
}
