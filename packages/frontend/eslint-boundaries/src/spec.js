/**
 * The Terp frontend boundary rules, declared **as data** (design §7.1.5). The ESLint adapter in
 * ./index.js realises them for the React stack; a future stack (e.g. Svelte) can realise the same
 * spec with its own adapter. The *rules* are shared; only the *enforcement adapter* is per-stack.
 *
 * They apply to the **app-authored surface** (`src/modules/**`) — the code agents and users write —
 * not the framework packages, which legitimately define the very primitives the rules point back to.
 */
/**
 * The Terp Standard version this adapter is certified against — the `spec_version` a
 * check report (`app-check-report.schema.json`) carries. A constant rather than a runtime
 * `@terp/spec` read: the spec data package is a dev/certification dependency of the platform
 * repo, not of a generated app, and the version is a property of the toolchain build. Held
 * equal to the pinned spec release by the framework gate (test_check_json.py — deliberately
 * NOT by this package's own suite, which certification runs against candidate spec releases
 * whose version is allowed to be newer).
 */
export const SPEC_VERSION = "0.10.0";

export const BOUNDARY_SPEC = {
  /** App module files the boundary + frontend security defaults apply to. */
  moduleFiles: ["**/modules/**/*.{ts,tsx}"],
  /**
   * Raw HTML elements an app module must not author directly, mapped to the token-styled
   * `@terp/react-core` replacement (accessible + theme-consistent by construction).
   */
  restrictedElements: {
    button: "Button",
    input: "Input",
    select: "Select",
    textarea: "Textarea",
    table: "DataView",
    dialog: "ConfirmDialog",
    form: 'Stack as="form"',
  },
  /**
   * JSX attributes an app module must not author — styling lives in the design tokens and the
   * react-core components (`Stack` for layout), never ad-hoc per screen. `className` would be
   * a side channel into hand-authored CSS, so it is refused alongside `style`.
   */
  restrictedAttributes: ["style", "className"],
  /**
   * Raw in-app anchors (`<a href="/...">`) bypass the router (full reload, no role-aware
   * guard); modules use the stack's `Link`. External `https://...` anchors stay allowed.
   */
  restrictInAppAnchors: true,
  /** Package internals an app module must not deep-import (import from the package root). */
  internalImportPatterns: ["@terp/*/src/*", "@terp/*/dist/*"],
  /** Module-authored stylesheets are refused — theming flows from the app's token source. */
  styleImportPatterns: [
    "*.css",
    "**/*.css",
    "*.css?*",
    "**/*.css?*",
    "*.scss",
    "**/*.scss",
    "*.scss?*",
    "**/*.scss?*",
    "*.sass",
    "**/*.sass",
    "*.sass?*",
    "**/*.sass?*",
    "*.less",
    "**/*.less",
    "*.less?*",
    "**/*.less?*",
    "*.styl",
    "**/*.styl",
    "*.styl?*",
    "**/*.styl?*",
  ],
  /** Browser request/stream globals that would skip the audited, typed client. */
  restrictedGlobals: ["fetch", "XMLHttpRequest", "WebSocket", "EventSource"],
  /**
   * The governed escape hatch (the frontend analog of the backend's `# arch-allow-*`): a
   * justified `// terp-allow-<rule>: <reason>` comment on (or immediately above) a violating
   * line suppresses that rule there. `<rule>` is the Terp Standard CATALOG rule name (the
   * `opt_out` spelling in `spec/catalog/frontend/<rule>.json`), never a tool-internal ESLint
   * id — one marker covers every detection path of its rule and can never waive a sibling
   * rule sharing a core lint id. An unjustified marker is itself reported. Marker counts
   * must exactly match the app's checked-in `escape-hatch-budget.json` (the ratchet).
   */
  allowMarkerPrefix: "terp-allow-",
};
