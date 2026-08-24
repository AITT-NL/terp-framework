/**
 * A channel into a running app, for the tool that is showing it.
 *
 * A development tool that embeds a running app in an iframe cannot see into it — a cross-origin
 * frame is opaque by design, and deliberately so. Which leaves someone looking at a button they
 * want changed with no way to say WHICH button, except in prose.
 *
 * This package does not know or name who is asking. It answers a protocol, not a product.
 *
 * The hook this uses already exists: every sanctioned component stamps `data-terp` on its root,
 * and the marker inventory is a pinned, gated list. So "which component is this?" is a question
 * the DOM can already answer; what was missing is someone to ask it.
 *
 * FOUR DECISIONS, and each is the reason a bridge like this is usually a bad idea.
 *
 * **It exists only in a development build.** The whole module is behind `import.meta.env.DEV`,
 * which a production build folds to `false` and strips — the same mechanism the template uses for
 * its dev sign-in credentials, and for the same reason. A deployed app has no listener, so none of
 * what follows is a production attack surface. It is not a setting that can be left on.
 *
 * **The tool speaks first, and the FIRST one wins.** The app never volunteers anything: it
 * records the origin and the window of the first well-formed handshake and answers that one
 * alone, thereafter — a second party cannot take the conversation over, and cannot start one.
 * First-come rather than validated, because there is nothing to validate against: a tool
 * embedding an app has no way to configure this package, and the two are on different origins by
 * design (an embedded preview sharing its host would carry that host's session cookie into app
 * code). An opaque origin is refused, since `"null"` is what a sandboxed or `file://` document
 * reports and it matches every other one.
 *
 * The window is kept as well as the origin. `window.parent` is the frame's embedder only when
 * there IS an embedder — open the app in a tab and `window.parent` is the app itself, so a reply
 * addressed there talks to nobody while looking like it worked.
 *
 * **Three things leave, and they are named exhaustively.** A reply carries `data-terp` markers,
 * element tag names, and the route path the page is on. Never text, never values, never
 * attributes — nothing an app renders data into. An app under development is an app with real
 * data in it, and a channel that could read the page would be a way out for that data, dev-only
 * or not.
 *
 * The route path is the one of the three that is not purely structural, and it is listed rather
 * than glossed: `/records/42` carries an identifier. It is sent because "which component" is not
 * a useful answer without "on which screen", it is the same string already visible in the address
 * bar of the frame the asker is displaying, and it is bounded below. An earlier version of this
 * docstring said "structure, never content" and sent it anyway, which is the kind of sentence
 * this file exists to not write.
 *
 * A bounding rectangle used to leave too. Nothing consumed it, so it does not.
 *
 * **The app draws its own highlight.** Nothing outside a cross-origin iframe can paint over it,
 * so pointing at something has to happen on this side. One outline, from the token layer, removed
 * with the mode.
 *
 * ADR 0006's quadruple is not fully satisfied and the missing halves are named in ADR 0101 §5:
 * there is a typed protocol with a safe default (off, and absent in production) and a fail-closed
 * runtime check (every message is validated and a stranger is ignored), but no build-time rule and
 * no escape hatch — a lint rule would have nothing to check, since the module is not something an
 * app writes, and there is nothing to opt out of in a build where it does not exist.
 */

/**
 * The protocol name, carried on every message in both directions.
 *
 * Versioned in the name rather than in a field: a tool and an app can be from different releases,
 * and a version mismatch has to be silence rather than a half-understood conversation. An app that
 * does not recognise the name ignores the message, which is exactly what an older app does with a
 * newer tool and the reverse.
 */
export const PREVIEW_BRIDGE_PROTOCOL = "terp.preview.1";

/** One step of the chain from the clicked element up to the page root. */
export interface PreviewBridgeStep {
  /** The sanctioned component's marker, e.g. "button" or "dataview". */
  readonly marker: string;
  /** The element it was stamped on, lowercased. */
  readonly tag: string;
}

/** What the app answers with when something is picked. */
export interface PreviewBridgeSelection {
  /** Innermost first: the marker chain from what was clicked up to the page. */
  readonly path: readonly PreviewBridgeStep[];
  /** The route the preview is on, so a tool can say where the component was found. */
  readonly path_name: string;
}

/**
 * The shape a marker may have: the shape every name in the pinned inventory has.
 *
 * Checked rather than trusted, even though this code runs inside the app it is describing.
 * `getAttribute("data-terp")` returns whatever is on the element, and an app under development
 * is allowed to put anything anywhere — so an unbounded string here is an app writing arbitrary
 * text into whatever the asking tool does with it. Bounded in length for the same reason.
 */
const MARKER_RE = /^[a-z0-9-]{1,64}$/;

/** A tag name, bounded the same way. Custom elements are hyphenated ASCII. */
const TAG_RE = /^[a-z0-9-]{1,64}$/;

/** A route path, bounded. Long enough for any real route, short enough not to be a payload. */
const MAX_PATH_NAME = 512;

/** The attribute the highlight is styled from — an attribute, like every other marker here. */
const HIGHLIGHT_ATTRIBUTE = "data-terp-preview-pick";

const STYLE_ID = "terp-preview-bridge";

const HIGHLIGHT_CSS = `
[${HIGHLIGHT_ATTRIBUTE}] {
  outline: 2px solid var(--color-brand-primary, #2563eb);
  outline-offset: 1px;
  cursor: crosshair;
}
`;

interface Incoming {
  protocol?: unknown;
  kind?: unknown;
  on?: unknown;
}

function isIncoming(data: unknown): data is Incoming & { protocol: string; kind: string } {
  return (
    typeof data === "object" &&
    data !== null &&
    (data as Incoming).protocol === PREVIEW_BRIDGE_PROTOCOL &&
    typeof (data as Incoming).kind === "string"
  );
}

/**
 * The chain of sanctioned components from *element* up to the document.
 *
 * A step whose marker or tag is not the shape a marker has is DROPPED rather than sent. The
 * attribute is whatever is on the element, and this code cannot tell a component's marker from
 * a string an app put there — so the reply carries only what looks like the closed vocabulary the
 * asker is expecting, and never becomes a way to write arbitrary text into that asker's tools.
 */
function markerPath(element: Element | null): PreviewBridgeStep[] {
  const path: PreviewBridgeStep[] = [];
  for (let node: Element | null = element; node !== null; node = node.parentElement) {
    const marker = node.getAttribute("data-terp");
    const tag = node.tagName.toLowerCase();
    if (marker !== null && MARKER_RE.test(marker) && TAG_RE.test(tag)) {
      path.push({ marker, tag });
    }
  }
  return path;
}

/** The nearest ancestor that a sanctioned component stamped, including *element* itself. */
function nearestMarked(element: Element | null): Element | null {
  for (let node: Element | null = element; node !== null; node = node.parentElement) {
    if (node.getAttribute("data-terp")) return node;
  }
  return null;
}

/**
 * Listen for a tool asking about this app, and answer it.
 *
 * Returns a function that removes every listener, the style element and the highlight — so a test
 * can run this twice without leaking, and so a caller that ever wants to stop can.
 *
 * Safe to call with no `window` (server rendering): it does nothing and returns a no-op.
 */
export function installPreviewBridge(): () => void {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return () => {};
  }

  /**
   * Who said hello: the origin to address a reply to, and the window to send it to.
   *
   * Both, because they answer different questions. The origin is what stops another site
   * reading a reply; the window is what makes the reply arrive at all — `window.parent` is the
   * embedder only when the app IS embedded, and is the app itself when it is open in a tab.
   */
  let asker: { origin: string; window: MessageEventSource } | null = null;
  /**
   * Who turned select mode on, or `null` when it is off.
   *
   * The asker rather than a boolean, and that is what removes the last unreachable branch from
   * this module: "select mode is on" and "there is someone to answer" are the same fact, so a
   * click handler holding this holds a destination and `reply` has no null case to guard. Written
   * as a boolean first, which left a `if (asker === null) return` in `reply` that no test could
   * reach — dead defensive code in the one module where dead code is least welcome.
   */
  let selecting: { origin: string; window: MessageEventSource } | null = null;
  let highlighted: Element | null = null;

  const reply = (to: { origin: string; window: MessageEventSource }, message: object) => {
    (to.window as Window).postMessage(
      { protocol: PREVIEW_BRIDGE_PROTOCOL, ...message },
      to.origin,
    );
  };

  const clearHighlight = () => {
    highlighted?.removeAttribute(HIGHLIGHT_ATTRIBUTE);
    highlighted = null;
  };

  const onPointerOver = (event: Event) => {
    if (selecting === null) return;
    const target = nearestMarked(event.target as Element | null);
    if (target === highlighted) return;
    clearHighlight();
    if (target !== null) {
      target.setAttribute(HIGHLIGHT_ATTRIBUTE, "");
      highlighted = target;
    }
  };

  const onClick = (event: MouseEvent) => {
    const to = selecting;
    if (to === null) return;
    // Captured and cancelled: in select mode a click picks a component rather than doing what it
    // normally does. Letting it through would navigate away from the thing being pointed at.
    event.preventDefault();
    event.stopPropagation();
    const target = nearestMarked(event.target as Element | null);
    if (target === null) return;
    reply(to, {
      kind: "selected",
      selection: {
        path: markerPath(target),
        path_name: window.location.pathname.slice(0, MAX_PATH_NAME),
      } satisfies PreviewBridgeSelection,
    });
  };

  const setSelecting = (to: { origin: string; window: MessageEventSource } | null) => {
    selecting = to;
    if (to === null) clearHighlight();
    if (to !== null && document.getElementById(STYLE_ID) === null) {
      const style = document.createElement("style");
      style.id = STYLE_ID;
      // textContent, never innerHTML: no HTML-injection sink is touched, which is the same rule
      // the component stylesheet's own injector follows.
      style.textContent = HIGHLIGHT_CSS;
      document.head.appendChild(style);
    }
  };

  const onMessage = (event: MessageEvent) => {
    if (!isIncoming(event.data)) return;
    if (asker === null && event.data.kind === "hello") {
      // `"null"` is what a sandboxed iframe, a `file://` page and a data: URL all report, so it
      // identifies nobody and matches everybody — adopting it would make the next such document
      // the asker too. A source is required for the same reason: without one there is no window
      // to answer.
      if (event.origin === "null" || event.origin === "" || event.source === null) return;
      asker = { origin: event.origin, window: event.source };
    }
    if (asker === null || event.origin !== asker.origin || event.source !== asker.window) return;
    if (event.data.kind === "hello") {
      reply(asker, { kind: "ready" });
      return;
    }
    if (event.data.kind === "select") {
      setSelecting(event.data.on === true ? asker : null);
      return;
    }
  };

  window.addEventListener("message", onMessage);
  document.addEventListener("pointerover", onPointerOver, true);
  document.addEventListener("click", onClick, true);

  return () => {
    window.removeEventListener("message", onMessage);
    document.removeEventListener("pointerover", onPointerOver, true);
    document.removeEventListener("click", onClick, true);
    selecting = null;
    clearHighlight();
    document.getElementById(STYLE_ID)?.remove();
  };
}
