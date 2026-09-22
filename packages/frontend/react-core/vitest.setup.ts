// Vitest setup: register @testing-library/jest-dom matchers (toBeInTheDocument, …).
// Importing here is harmless for node-environment tests; the matchers are only used by
// the jsdom component tests.
import "@testing-library/jest-dom/vitest";

import { configure } from "@testing-library/dom";

// `findBy*` and `waitFor` default to a 1000ms budget, and the component tests spend it on
// a path that is not a render: a mocked fetch resolving, then the state it sets, then the
// re-render that finally puts the text on screen. One second does not reliably cover that,
// so the budget is raised. `testTimeout` (vite.config.ts) sits above it, so a matcher that
// cannot find its element loses first and says which element; equal budgets report an
// unhelpful "test timed out" instead.
//
// READ THE HISTORY BELOW AS A TOLERANCE, NOT AS A DIAGNOSIS. This lever was raised twice
// (1s to 3s to 4s) against an intermittent "unable to find element" — five failures across
// one day, four different fetch-bound tests, always one file of eighty-one, each passing
// alone and on a re-run. Neither raise stopped it, and the cause is now known and removed:
// four admin tests held a structural race. They clicked a submit control that `UserCreate`
// disables until an ambient access-model fetch has landed AND the effect it feeds has run,
// having waited on nothing but the page heading — which renders before either. jsdom raises
// no submit event for a click on a disabled control, so the click was LOST, not late, and
// the failure surfaced several lines later on whatever was waiting for the POST's result.
// No budget can close that. Those tests now wait on the control being enabled
// (`enabledSubmitControl`, admin/admin.test.tsx), and the window itself is pinned by a
// dedicated test there.
//
// Contention is real and is a different thing: it widens the window such a race needs, and
// a serial run measurably helped (see vite.config.ts). But a test waiting on the wrong
// thing fails on an idle machine too, only more rarely. So before this lever is reached for
// a third time: check what the failing test is waiting on, and whether the thing it clicks
// can even be clicked yet.
//
// The budget has a CEILING, and the first attempt at this walked straight into it. A toast
// auto-dismisses after `DEFAULT_DURATION_MS` (5s, toast.tsx), and several admin tests wait
// for a field error and then assert the toast SYNCHRONOUSLY. Set the budget to 5s and a
// wait that takes long enough outlives the toast the next line is about to look for — one
// flake traded for another, and a worse one, because it looks like a product bug. So the
// budget sits between the two: comfortably past a fetch and a re-render, comfortably short
// of a toast's life. `async-budget.test.ts` holds the lower end, and
// `test_frontend_async_budget.py` the ordering across all three files.
configure({ asyncUtilTimeout: 4_000 });

// jsdom's File / Blob / FormData are structurally incompatible with Node's built-in
// (undici) fetch: a jsdom File inside a FormData body serializes as an empty, nameless
// part, and on Node >= 24 `Request.formData()` brand-checks reject jsdom instances
// outright. The component tests exercise uploads through the real fetch pipeline, so in
// the jsdom environment swap these globals for Node's own classes. The tsconfig compiles
// with `types: []` (browser-only), so `node:buffer` is imported dynamically through a
// variable specifier; Node's FormData class is not exported, so it is recovered from a
// parsed urlencoded Response body.
if (typeof window !== "undefined") {
  const bufferModuleId = "node:buffer";
  const { File: NativeFile, Blob: NativeBlob } = (await import(
    /* @vite-ignore */ bufferModuleId
  )) as { File: typeof File; Blob: typeof Blob };
  globalThis.File = NativeFile;
  globalThis.Blob = NativeBlob;
  window.File = NativeFile;
  window.Blob = NativeBlob;
  const NativeFormData = (
    await new Response("a=b", {
      headers: { "content-type": "application/x-www-form-urlencoded" },
    }).formData()
  ).constructor as typeof FormData;
  globalThis.FormData = NativeFormData;
  window.FormData = NativeFormData;

  // Vitest's jsdom environment installs a `Request` SUBCLASS whose constructor
  // pre-processes `init.body` for jsdom's Blob internals (it reads `_buffer`).
  // With the swap above that body is a Node FormData holding a Node File, so the
  // shim throws on the one thing these tests exist to check — and handed a jsdom
  // FormData instead it does not recognise it as form data at all and serialises
  // the body as a string, so the request goes out as `text/plain` and the
  // multipart assertion fails for a second, quieter reason. Unwrapping to the
  // class it extends restores Node's own constructor, which serialises a Node
  // FormData as multipart with a boundary.
  //
  // Guarded on the shim actually being there: a real `Request` is a base class,
  // so its prototype is `Function.prototype`. If a later Vitest stops wrapping,
  // this becomes a no-op rather than reaching for something that is not a class.
  const RequestBase = Object.getPrototypeOf(globalThis.Request) as typeof Request;
  if (typeof RequestBase === "function" && (RequestBase as unknown) !== Function.prototype) {
    globalThis.Request = RequestBase;
    window.Request = RequestBase;
  }
}

// jsdom does not implement scrollTo, which TanStack Router calls on navigation; stub it so
// the router render tests do not emit a noisy "Not implemented" warning. Guarded so the
// node-environment tests (no window) are unaffected.
if (typeof window !== "undefined") {
  window.scrollTo = (() => {}) as typeof window.scrollTo;
}


// jsdom does not implement the native <dialog> modal API (showModal/close); polyfill just
// enough for the ConfirmDialog tests: toggle the `open` property and fire the `close` event.
if (typeof window !== "undefined" && typeof HTMLDialogElement !== "undefined") {
  const proto = HTMLDialogElement.prototype as HTMLDialogElement & {
    showModal?: () => void;
    close?: () => void;
  };
  if (typeof proto.showModal !== "function") {
    proto.showModal = function showModal(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    };
  }
  if (typeof proto.close !== "function") {
    proto.close = function close(this: HTMLDialogElement) {
      this.removeAttribute("open");
      this.dispatchEvent(new Event("close"));
    };
  }
}
