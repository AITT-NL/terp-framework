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
 * **The tool speaks first, and only it is answered.** The app never volunteers anything: it
 * records the origin of the first well-formed handshake and replies to that origin alone,
 * thereafter. That is also the only way it CAN learn who to answer: a tool embedding an app has
 * no way to configure this package, and the two are on different origins by design — an embedded
 * preview sharing its host would carry that host's session cookie into app code.
 *
 * **Structure, never content.** A reply carries `data-terp` markers, element tag names and a
 * bounding rectangle. It never carries text, values, attributes or anything an app puts data in.
 * An app under development is an app with real data in it, and a channel that could read the page
 * would be a way out for that data — dev-only or not.
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
  /** Where it is, in the preview's own viewport — for a tool that wants to point at it. */
  readonly rect: { readonly x: number; readonly y: number; readonly width: number; readonly height: number };
  /** The route the preview is on, so a tool can say where the component was found. */
  readonly path_name: string;
}

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

/** The chain of sanctioned components from *element* up to the document. */
function markerPath(element: Element | null): PreviewBridgeStep[] {
  const path: PreviewBridgeStep[] = [];
  for (let node: Element | null = element; node !== null; node = node.parentElement) {
    const marker = node.getAttribute("data-terp");
    if (marker !== null && marker !== "") {
      path.push({ marker, tag: node.tagName.toLowerCase() });
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

  /** The origin that said hello. Everything from anywhere else is ignored, silently. */
  let asker: string | null = null;
  /**
   * The origin that turned select mode on, or `null` when it is off.
   *
   * The origin rather than a boolean, and that is what removes the last unreachable branch from
   * this module: "select mode is on" and "there is someone to answer" are the same fact, so a
   * click handler holding this holds a string and `reply` has no null case to guard. Written as a
   * boolean first, which left a `if (asker === null) return` in `reply` that no test could reach
   * — dead defensive code in the one module where dead code is least welcome.
   */
  let selecting: string | null = null;
  let highlighted: Element | null = null;

  const reply = (to: string, message: object) => {
    window.parent.postMessage({ protocol: PREVIEW_BRIDGE_PROTOCOL, ...message }, to);
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
    const box = target.getBoundingClientRect();
    reply(to, {
      kind: "selected",
      selection: {
        path: markerPath(target),
        rect: { x: box.x, y: box.y, width: box.width, height: box.height },
        path_name: window.location.pathname,
      } satisfies PreviewBridgeSelection,
    });
  };

  const setSelecting = (to: string | null) => {
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
      asker = event.origin;
    }
    if (event.origin !== asker) return;
    if (event.data.kind === "hello") {
      reply(event.origin, { kind: "ready" });
      return;
    }
    if (event.data.kind === "select") {
      setSelecting(event.data.on === true ? event.origin : null);
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
