// Vitest setup: register @testing-library/jest-dom matchers (toBeInTheDocument, …).
// Importing here is harmless for node-environment tests; the matchers are only used by
// the jsdom component tests.
import "@testing-library/jest-dom/vitest";

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
