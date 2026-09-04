// @vitest-environment jsdom
//
// The defect this module exists for is not "copying is hard" — it is that the failure was
// SILENT and unreachable by any check. `navigator.clipboard` is typed as always present and
// is absent outside a secure context, so the call throws synchronously, before a promise
// exists, and neither a `.catch` nor a `try` around an `await` sees it.
//
// So the tests that matter are the negative ones: the insecure context must not throw, must
// not resolve as success, and must reach the fallback that still works there.

import { afterEach, describe, expect, it, vi } from "vitest";

import { COPIED_FEEDBACK_MS, copyText, useCopyToClipboard } from "./clipboard";

const original = Object.getOwnPropertyDescriptor(globalThis.navigator, "clipboard");

function setClipboard(value: unknown): void {
  Object.defineProperty(globalThis.navigator, "clipboard", {
    value,
    configurable: true,
    writable: true,
  });
}

afterEach(() => {
  if (original) Object.defineProperty(globalThis.navigator, "clipboard", original);
  else setClipboard(undefined);
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("copyText", () => {
  it("uses the async API when it is there", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });

    await expect(copyText("hello")).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith("hello");
  });

  it("does not throw when navigator.clipboard is undefined", async () => {
    // The whole reason for this module. On a plain-http origin the property is absent, so
    // `navigator.clipboard.writeText(...)` is a property read on undefined — a synchronous
    // TypeError that escapes every handler a caller would think to write. lib.dom types the
    // property as present, so nothing warns first.
    setClipboard(undefined);
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, "execCommand", { value: execCommand, configurable: true });

    await expect(copyText("hello")).resolves.toBe(true);
    expect(execCommand).toHaveBeenCalledWith("copy");
  });

  it("reports a refusal instead of resolving as success", async () => {
    // The other half of "silent": a copy that did not happen must be distinguishable from
    // one that did, or a caller has nothing to react to and the button lies again.
    setClipboard(undefined);
    Object.defineProperty(document, "execCommand", {
      value: vi.fn().mockReturnValue(false),
      configurable: true,
    });

    await expect(copyText("hello")).resolves.toBe(false);
  });

  it("falls back when the API is present and rejects", async () => {
    // A permissions policy, a document without focus, a declined prompt: the object is
    // there and the write is refused. The fallback sometimes still works, and finding out
    // costs one detached element.
    setClipboard({ writeText: vi.fn().mockRejectedValue(new Error("denied")) });
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, "execCommand", { value: execCommand, configurable: true });

    await expect(copyText("hello")).resolves.toBe(true);
    expect(execCommand).toHaveBeenCalled();
  });

  it("treats a partial clipboard object as absent", async () => {
    // Older WebViews expose `navigator.clipboard` without `writeText`. A `!= null` guard
    // passes that and then throws on the call — which is the original bug wearing a
    // slightly different hat.
    setClipboard({});
    Object.defineProperty(document, "execCommand", {
      value: vi.fn().mockReturnValue(true),
      configurable: true,
    });

    await expect(copyText("hello")).resolves.toBe(true);
  });

  it("copies nothing successfully", async () => {
    const writeText = vi.fn();
    setClipboard({ writeText });

    await expect(copyText("")).resolves.toBe(true);
    // Clearing a field and copying it is not an error, and a toast saying otherwise would
    // be shown to somebody who did nothing wrong.
    expect(writeText).not.toHaveBeenCalled();
  });

  it("leaves no textarea behind when the fallback throws", async () => {
    setClipboard(undefined);
    Object.defineProperty(document, "execCommand", {
      value: vi.fn().mockImplementation(() => {
        throw new Error("not allowed");
      }),
      configurable: true,
    });

    await expect(copyText("hello")).resolves.toBe(false);
    expect(document.querySelectorAll("textarea")).toHaveLength(0);
  });
});

describe("useCopyToClipboard", () => {
  it("says it worked, then stops saying so", async () => {
    // A copy has no visible result — the clipboard is somewhere else — so a control that
    // does not acknowledge is indistinguishable from a broken one.
    vi.useFakeTimers();
    setClipboard({ writeText: vi.fn().mockResolvedValue(undefined) });
    const { renderHook, act } = await import("@testing-library/react");

    const { result } = renderHook(() => useCopyToClipboard());
    expect(result.current.copied).toBe(false);

    await act(async () => {
      await result.current.copy("hello");
    });
    expect(result.current.copied).toBe(true);
    expect(result.current.failed).toBe(false);

    act(() => {
      vi.advanceTimersByTime(COPIED_FEEDBACK_MS + 1);
    });
    expect(result.current.copied).toBe(false);
  });

  it("keeps a refusal separate from the resting state", async () => {
    // `failed` is not `copied === false`: a control that has never been pressed and one
    // that has just been refused would otherwise look identical.
    setClipboard(undefined);
    Object.defineProperty(document, "execCommand", {
      value: vi.fn().mockReturnValue(false),
      configurable: true,
    });
    const { renderHook, act } = await import("@testing-library/react");

    const { result } = renderHook(() => useCopyToClipboard());
    expect(result.current.failed).toBe(false);

    await act(async () => {
      await result.current.copy("hello");
    });

    expect(result.current.failed).toBe(true);
    expect(result.current.copied).toBe(false);
  });
});
