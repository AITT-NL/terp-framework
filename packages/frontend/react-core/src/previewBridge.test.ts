// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { installPreviewBridge, PREVIEW_BRIDGE_PROTOCOL } from "./previewBridge";

// The channel a tool showing this app can ask it questions through.
//
// What is asserted here is almost entirely REFUSALS, because a postMessage listener in an app is
// a thing that goes wrong in one direction: it answers someone it should not have, or it answers
// with more than it was asked. The one positive case — a click reports the marker chain — is the
// easy half.

// A tool, not THE tool: this package answers a protocol and does not know who is asking, which
// is also what `test_repo_split_readiness` holds it to — the framework may not name its consumer.
const TOOL = "http://tool.test";
const STRANGER = "http://evil.test";

let posted: { message: unknown; origin: string }[];
let uninstall: () => void;

/** A message arriving from *origin*, the way the browser delivers one. */
function deliver(data: unknown, origin: string) {
  window.dispatchEvent(new MessageEvent("message", { data, origin }));
}

function hello(origin = TOOL) {
  deliver({ protocol: PREVIEW_BRIDGE_PROTOCOL, kind: "hello" }, origin);
}

function selectMode(on: boolean, origin = TOOL) {
  deliver({ protocol: PREVIEW_BRIDGE_PROTOCOL, kind: "select", on }, origin);
}

beforeEach(() => {
  posted = [];
  // `window.parent` is `window` in jsdom, so the app's reply lands on this same window's
  // postMessage — which is exactly the call being asserted about.
  vi.spyOn(window.parent, "postMessage").mockImplementation(((message: unknown, origin: string) => {
    posted.push({ message, origin });
  }) as typeof window.postMessage);
  document.body.innerHTML = `
    <div data-terp="page">
      <div data-terp="card">
        <button data-terp="button" data-variant="primary">Save<span id="label">now</span></button>
      </div>
      <p id="unmarked">plain</p>
    </div>`;
  uninstall = installPreviewBridge();
});

afterEach(() => {
  uninstall();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("the preview bridge", () => {
  it("says nothing until it is spoken to", () => {
    // The app never volunteers. Everything below depends on this: the origin it answers is the
    // origin that asked, so an app that announced itself first would have nowhere to send that
    // announcement but "*".
    selectMode(true);
    document.getElementById("label")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(posted).toEqual([]);
  });

  it("answers the origin that said hello, and only that one", () => {
    hello(TOOL);
    expect(posted).toHaveLength(1);
    expect(posted[0]!.origin).toBe(TOOL);
    expect(posted[0]!.message).toEqual({ protocol: PREVIEW_BRIDGE_PROTOCOL, kind: "ready" });

    // A second party cannot take the conversation over, and cannot drive it either.
    posted = [];
    hello(STRANGER);
    selectMode(true, STRANGER);
    document.getElementById("label")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(posted).toEqual([]);
  });

  it("ignores a message that is not this protocol", () => {
    // The window of an app under development receives messages from all sorts of tooling. A
    // listener that acted on a bare `{kind: "select"}` would be acting on someone else's protocol.
    deliver({ kind: "hello" }, TOOL);
    deliver({ protocol: "terp.preview.0", kind: "hello" }, TOOL);
    deliver("hello", TOOL);
    deliver(null, TOOL);
    expect(posted).toEqual([]);
  });

  it("reports the marker chain of what was clicked, innermost first", () => {
    hello();
    selectMode(true);
    posted = [];
    document.getElementById("label")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(posted).toHaveLength(1);
    // Addressed to the asker, never to "*". A selection posted with a wildcard target is readable
    // by whatever frame happens to be the parent, which is a different thing from answering the
    // tool that asked — and the two are indistinguishable in the message itself.
    expect(posted[0]!.origin).toBe(TOOL);
    const message = posted[0]!.message as { kind: string; selection: { path: unknown[] } };
    expect(message.kind).toBe("selected");
    // The span itself carries no marker, so the button is what was picked — and the chain above it
    // is what tells a tool WHERE in the app that button is.
    expect(message.selection.path).toEqual([
      { marker: "button", tag: "button" },
      { marker: "card", tag: "div" },
      { marker: "page", tag: "div" },
    ]);
  });

  it("carries structure and never content", () => {
    // The honesty boundary. An app under development is an app with real data in it, so a channel
    // that could read the page would be a way out for that data — dev-only or not. Asserted by
    // serialising the whole reply and looking for the words that are on the page.
    hello();
    selectMode(true);
    posted = [];
    document.querySelector("[data-terp='button']")!.dispatchEvent(
      new MouseEvent("click", { bubbles: true }),
    );
    const serialised = JSON.stringify(posted[0]!.message);
    expect(serialised).not.toContain("Save");
    expect(serialised).not.toContain("now");
    expect(serialised).not.toContain("primary");
  });

  it("says nothing when what was clicked is inside no sanctioned component", () => {
    hello();
    selectMode(true);
    posted = [];
    document.body.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(posted).toEqual([]);
  });

  it("stops reporting when select mode is turned off", () => {
    hello();
    selectMode(true);
    selectMode(false);
    posted = [];
    document.getElementById("label")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(posted).toEqual([]);
  });

  it("cancels the click it intercepts, so picking a link does not navigate away", () => {
    hello();
    selectMode(true);
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    document.getElementById("label")!.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("leaves a normal click alone when select mode is off", () => {
    hello();
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    document.getElementById("label")!.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });

  it("outlines what the pointer is over, and only in select mode", () => {
    // The Studio cannot paint over a cross-origin iframe, so pointing at something has to happen
    // on this side or not at all.
    hello();
    const button = document.querySelector("[data-terp='button']")!;
    button.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
    expect(button.hasAttribute("data-terp-preview-pick")).toBe(false);

    selectMode(true);
    button.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
    expect(button.hasAttribute("data-terp-preview-pick")).toBe(true);

    // Moving on unmarks the last one, so two things are never outlined at once.
    document.getElementById("unmarked")!.dispatchEvent(
      new MouseEvent("pointerover", { bubbles: true }),
    );
    expect(button.hasAttribute("data-terp-preview-pick")).toBe(false);
  });

  it("is installed only in a development build", () => {
    // The one claim in this module that no runtime test can check, and the one everything else
    // rests on: `import.meta.env.DEV` is TRUE under vitest, so removing the guard changes nothing
    // any assertion here could see, while changing whether a deployed app carries a postMessage
    // listener at all. A bundler folds that expression textually, so what can be checked is that
    // the expression is still written — the same technique review.test.tsx uses for a forwarding
    // line, and for the same reason.
    //
    // Mutation: drop the `if (import.meta.env.DEV)` around the install and this goes red.
    //
    // Read through the raw glob rather than `readFileSync`: this file runs in jsdom, where
    // `import.meta.url` is an http URL and `new URL(..., import.meta.url)` is not a file path.
    // The sibling source-reading tests run in the node environment and can use fs; this one
    // cannot, because everything else it asserts needs a DOM.
    const sources = import.meta.glob("./**/*.tsx", {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>;
    const bootstrap = sources["./bootstrap.tsx"] ?? "";
    expect(bootstrap, "bootstrap.tsx is not in the scanned sources").not.toBe("");
    expect(bootstrap).toMatch(
      /if \(import\.meta\.env\.DEV\) \{\s*installPreviewBridge\(\);\s*\}/,
    );
    // And nowhere else, because a second unguarded call would ship the listener whatever this
    // one says. Counted over the whole package rather than over one file.
    const calls = Object.values(sources).flatMap(
      (source) => source.match(/installPreviewBridge\(\)/g) ?? [],
    );
    expect(calls).toHaveLength(1);
  });

  it("leaves nothing behind when it is uninstalled", () => {
    hello();
    selectMode(true);
    document.querySelector("[data-terp='button']")!.dispatchEvent(
      new MouseEvent("pointerover", { bubbles: true }),
    );
    uninstall();
    uninstall = () => {};

    expect(document.querySelector("[data-terp-preview-pick]")).toBeNull();
    expect(document.getElementById("terp-preview-bridge")).toBeNull();
    posted = [];
    hello();
    expect(posted).toEqual([]);
  });
});
