/**
 * The Terp frontend boundary rules, declared **as data** (design §7.1.5). The ESLint adapter in
 * ./index.js realises them for the React stack; a future stack (e.g. Svelte) can realise the same
 * spec with its own adapter. The *rules* are shared; only the *enforcement adapter* is per-stack.
 *
 * Every rule applies to all app-authored `src/**` (ADR 0175): a rule's scope follows what it is
 * about, and none of them is about a directory. The one rule that *is* about a module's shape,
 * `no-cross-module-imports`, reads the module tree for itself: a module never imports a
 * sibling, and code outside every module never imports into one. The bootstrap is the one file
 * that may import stylesheets, and only the token pipeline's own. Framework packages
 * legitimately define the primitives these rules point back to and are outside an app's
 * boundary config.
 */
/**
 * The Terp Standard version this adapter is certified against — the `spec_version` a
 * check report (`app-check-report.schema.json`) carries. A constant rather than a runtime
 * `@terpjs/spec` read: the spec data package is a dev/certification dependency of the platform
 * repo, not of a generated app, and the version is a property of the toolchain build. Held
 * equal to the pinned spec release by the framework gate (test_check_json.py — deliberately
 * NOT by this package's own suite, which certification runs against candidate spec releases
 * whose version is allowed to be newer).
 */
export const SPEC_VERSION = "0.39.0";

/** Every script extension the bundler loads as app source (see `appFiles`). */
const SOURCE_EXTENSIONS = ["ts", "tsx", "mts", "cts", "js", "jsx", "mjs", "cjs"];

export const BOUNDARY_SPEC = {
  /**
   * Every app-authored source file, and so every file the boundary applies to. A module, a
   * helper beside the modules and the bootstrap are held alike (ADR 0175), and so is every
   * script extension the bundler loads: a `.jsx` or `.mts` file is app source too, and leaving
   * one out would make renaming a file an escape hatch.
   */
  appFiles: [`**/src/**/*.{${SOURCE_EXTENSIONS.join(",")}}`],
  /**
   * The extensions `appFiles` names, for the tools that walk `src/` themselves rather than
   * through the ESLint config (the escape-hatch budget, the corpus harness), so the files they
   * count are the files the lint holds.
   */
  sourceExtensions: SOURCE_EXTENSIONS,
  /**
   * The app's bootstrap: the file that mounts the app and loads the token pipeline. TypeScript
   * only, as the template ships it: this names an allowance, so it stays as narrow as the file
   * it was written for, and a bootstrap in another extension meets the stricter rule.
   */
  bootstrapFiles: ["**/src/main.{ts,tsx}"],
  /**
   * The stylesheets the bootstrap may import, and the only ones any app file may: the framework's
   * tokens, the house style a tool manages and the app's own token overlay. Each is a layer of
   * the token pipeline, so a stylesheet outside this list is a side channel around it, a
   * library's included.
   */
  bootstrapStylesheets: ["@terpjs/contract/tokens.css", "./house-style.css", "./theme.css"],
  /**
   * Raw HTML elements app source must not author directly, mapped to the token-styled
   * `@terpjs/react-core` replacement (accessible + theme-consistent by construction).
   */
  restrictedElements: {
    button: "Button",
    input: "Input",
    select: "Select",
    textarea: "Textarea",
    table: "DataView",
    dialog: "ConfirmDialog",
    form: 'Stack as="form"',
    meter: "Meter",
  },
  /**
   * JSX attributes app source must not author — styling lives in the design tokens and the
   * react-core components (`Stack` for layout), never ad-hoc per screen. `className` would be
   * a side channel into hand-authored CSS, so it is refused alongside `style`.
   */
  /**
   * Extra guidance for an element whose named replacement does not fit every case, so the
   * refusal states what to do instead of implying something is missing.
   *
   * The criterion: a restricted element earns a sentence here when its named replacement is
   * right for some cases and actively misleading for others, so that an author who reads the
   * bare rule concludes the framework ships nothing for their case. Two elements meet it.
   *
   * `dialog` was the first. The replacement is `ConfirmDialog`, which is right for a
   * confirmation and wrong advice for anything else — an author who reads "use ConfirmDialog"
   * for an edit form concludes the framework ships no dialog and the rule cannot be obeyed.
   * The guidance below is what a reporting app arrived at on its own, and recorded as the
   * better outcome: the editor moved into an expanded row, so the finding that sent the author
   * there stayed on screen while they fixed it.
   *
   * `table` is the second (ADR 0099 §4). "Use DataView" reads as disproportionate for five
   * static rows unless the sentence names the two-line recipe, so it does.
   */
  restrictedElementGuidance: {
    dialog:
      "A modal is for a confirmation (ConfirmDialog) or an explicit post-action moment. " +
      "An edit form or a detail view belongs in a routed page, or in an expanded row " +
      "beside the thing it edits — which keeps the context that sent the author there on " +
      "screen. If you have a case neither covers, say so rather than reaching for a raw " +
      "<dialog>: the modal contract (focus trap, focus restore, Escape, top layer) is " +
      "what ConfirmDialog exists to provide and a hand-rolled one silently drops.",
    table:
      "Use DataView, and if it looks like too much for five static rows, the recipe is " +
      "two lines: variant=\"embedded\" drops the view toggle, the page-size selector and " +
      "the footer, and InMemoryDataViewRepository needs two functions: getRowId and " +
      "getValue. That is worth " +
      "saying because \"use DataView\" on its own reads as wrong advice here, and an " +
      "author who believes it reaches for a raw <table> — which silently gives up " +
      "sorting, column resizing and settings, the mobile card reflow and the row-level " +
      "activation the rest of the app has.",
  },
  restrictedAttributes: ["style", "className"],
  /**
   * Raw in-app anchors (`<a href="/...">`) bypass the router (full reload, no role-aware
   * guard); modules use the stack's `Link`. External `https://...` anchors stay allowed.
   */
  restrictInAppAnchors: true,
  /** Package internals app source must not deep-import (import from the package root). */
  internalImportPatterns: ["@terpjs/*/src/*", "@terpjs/*/dist/*"],
  /** App-authored stylesheets are refused — theming flows from the app's token source. */
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
   * Refuse `navigator.clipboard` in app code, in every spelling.
   *
   * A flag rather than a list because it is one API with one defect, the way
   * `restrictInAppAnchors` is: the DOM lib types the property as always present and it is
   * absent outside a secure context, so an access on a plain-http origin is a property
   * lookup on `undefined` -- a synchronous throw the type checker cannot see. The stack's
   * `copyText` / `useCopyToClipboard` feature-detect and report a refusal instead.
   */
  restrictRawClipboard: true,
  restrictRawRandomUuid: true,
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
