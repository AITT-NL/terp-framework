import { ApiError } from "./unwrap";

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
 * Public since 0.22.0, on the condition its previous note set: it becomes package surface when
 * something outside `admin/` needs it, and an app wiring `ApiError.fields` into its own forms is
 * that. Copying it is what produces the hole above, because the leftover branch is the half a
 * reader does not know to write.
 *
 * @example
 * ```ts
 * const RENDERED = ["name", "description"];
 * try {
 *   await unwrap(client.POST("/api/v1/groups/", { body }));
 * } catch (error) {
 *   const { shown, leftover } = routeFieldErrors(error, RENDERED);
 *   setFieldErrors(shown);
 *   if (leftover || Object.keys(shown).length === 0) {
 *     toast.error(message(error));  // never leave the user with nothing
 *   }
 * }
 * ```
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
