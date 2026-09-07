/**
 * Putting text on the clipboard, once, for everyone.
 *
 * `navigator.clipboard` is not the API it looks like. `lib.dom` types it as always
 * present, and it is absent outside a **secure context** — so on a plain-http origin
 * that is not localhost, `navigator.clipboard.writeText(...)` is a property access on
 * `undefined`. That throws a **synchronous** `TypeError`, before any promise exists, so a
 * `.catch` on the call does not run and neither does a `try` written around an `await`
 * that was never reached. TypeScript reports nothing, because as far as its type says the
 * property is there.
 *
 * The observed outcome is a button that does nothing and says nothing, found only by
 * clicking it in a browser served over http — which is to say, found by a person, in a
 * deployment, rather than by any check. Every app reaching for the API directly
 * rediscovers that, and the icon set has shipped a `clipboard` glyph the whole time.
 *
 * Same shape as the download seam (ADR 0096 §3): a browser API with a footgun, wrapped
 * once. Two exports, and they answer different questions -- {@link copyText} is the
 * mechanism and can be called from anywhere, {@link useCopyToClipboard} adds the "Copied"
 * acknowledgement a control needs and is the one a screen usually wants.
 *
 * **A refusal is reported, never swallowed.** `copyText` resolves to `false` when the
 * text did not reach the clipboard, and the whole reason this module exists is that the
 * failure was silent. A caller that ignores the answer has chosen to; a caller that had
 * no answer to ignore had not.
 */

import { useCallback, useEffect, useRef, useState } from "react";

/** How long {@link useCopyToClipboard} keeps saying it worked, in milliseconds. */
export const COPIED_FEEDBACK_MS = 2000;

/**
 * Whether the async Clipboard API is actually usable right now.
 *
 * Three separate ways it is not, and the type says none of them: no `navigator` at all
 * (server-side render, a test environment without a DOM), `navigator.clipboard`
 * undefined (an insecure context), and the object present without the method (older
 * WebViews expose a partial shape). Checked as a property lookup rather than a
 * `typeof navigator.clipboard` guard, because the second is what TypeScript already
 * believes and therefore narrows away.
 */
function clipboardApi(): { writeText: (text: string) => Promise<void> } | null {
  const candidate = (globalThis as { navigator?: { clipboard?: unknown } }).navigator
    ?.clipboard as { writeText?: unknown } | undefined;
  return typeof candidate?.writeText === "function"
    ? (candidate as { writeText: (text: string) => Promise<void> })
    : null;
}

/**
 * The pre-Clipboard-API path, for the insecure contexts where the API is absent.
 *
 * `document.execCommand("copy")` is deprecated and is deliberately still here: it is the
 * only thing that works on an http origin, which is exactly the case that produced the
 * silent failure. The textarea is positioned off-screen rather than hidden, because a
 * `display: none` element cannot be selected and the copy then silently does nothing —
 * the same class of quiet failure one layer down.
 *
 * `readOnly` keeps a mobile keyboard from appearing for the instant the element is
 * focused, and the `finally` removes the node even when the command throws.
 */
function copyByExecCommand(text: string): boolean {
  if (typeof document === "undefined") return false;
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.setAttribute("aria-hidden", "true");
  area.style.position = "fixed";
  area.style.top = "-1000px";
  area.style.opacity = "0";
  document.body.appendChild(area);
  try {
    area.select();
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    area.remove();
  }
}

/**
 * Put *text* on the clipboard. Resolves to whether it got there.
 *
 * Never rejects and never throws, including on the synchronous `TypeError` this module
 * exists for: a copy affordance is not worth an unhandled rejection, and a caller that
 * wants to react to failure has the boolean. Empty text is a successful no-op rather than
 * a failure -- clearing a field and copying it is not an error, and reporting one would
 * put a toast in front of somebody who did nothing wrong.
 */
export async function copyText(text: string): Promise<boolean> {
  if (text === "") return true;
  const api = clipboardApi();
  if (api !== null) {
    try {
      await api.writeText(text);
      return true;
    } catch {
      // Present and refused: a permissions policy, a document without focus, or a
      // browser that asks and was declined. The fallback below sometimes still works,
      // and trying it costs one detached element.
    }
  }
  return copyByExecCommand(text);
}

/** What {@link useCopyToClipboard} hands back. */
export interface CopyToClipboard {
  /** Copy *text*; resolves to whether it worked, and drives {@link copied}. */
  copy: (text: string) => Promise<boolean>;
  /** True for {@link COPIED_FEEDBACK_MS} after a copy that worked. */
  copied: boolean;
  /** True after a copy that did not, until the next attempt. Never both. */
  failed: boolean;
}

/**
 * {@link copyText} plus the acknowledgement a control needs.
 *
 * A copy has no visible result — the clipboard is somewhere else — so a button that does
 * not say "Copied" is indistinguishable from a button that is broken. That is the same
 * confusion the silent failure caused, and it is why the flag is part of the seam instead
 * of being left to each caller's own `setTimeout`.
 *
 * `failed` is separate rather than `copied === false`, because "not copied" is the
 * resting state and "the copy was refused" is an event. Collapsing them would make a
 * button that has never been pressed indistinguishable from one that just failed.
 *
 * Deliberately not a component. A copy affordance is a `Button` with an icon, a label the
 * app writes, and a placement only the app knows — everything except the mechanism, and
 * the mechanism is what was missing.
 */
export function useCopyToClipboard(): CopyToClipboard {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const live = useRef(true);

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
      if (timer.current !== null) clearTimeout(timer.current);
    };
  }, []);

  const copy = useCallback(async (text: string) => {
    const ok = await copyText(text);
    // A screen can navigate away while the write is in flight; setting state on an
    // unmounted hook is a warning in development and a leak of the timer below.
    if (!live.current) return ok;
    setCopied(ok);
    setFailed(!ok);
    if (timer.current !== null) clearTimeout(timer.current);
    if (ok) {
      timer.current = setTimeout(() => {
        if (live.current) setCopied(false);
      }, COPIED_FEEDBACK_MS);
    }
    return ok;
  }, []);

  return { copy, copied, failed };
}
