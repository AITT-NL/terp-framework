/**
 * The ESLint (React stack) adapter that realises {@link BOUNDARY_SPEC}. This is the frontend analog
 * of the backend `terp.arch` harness: it keeps app modules independent and on the centralized
 * contract, so a non-technical user or a coding agent cannot introduce drift or a security gap.
 *
 * There are no modes and no severity dial — every rule is an error, always (exactly like the
 * backend gate). The only pressure valve is the governed escape hatch: a justified
 * `// terp-allow-<rule>: <reason>` marker (see {@link suppressWithMarkers}), whose counts must
 * match the app's checked-in `escape-hatch-budget.json` (see ./budget.js).
 *
 * Loaded by Node (an ESLint flat config), so it is plain ESM JavaScript — not TypeScript.
 */

import fs from "node:fs";
import path from "node:path";

import tseslint from "typescript-eslint";

import { LAYOUT_CONTRACTS, LAYOUT_CONTRACT_FILE, slotViolationMessage } from "./layouts.js";
import { BOUNDARY_SPEC } from "./spec.js";

/** The app-module name a file/import path belongs to (the segment after `modules/`), or null. */
function moduleOf(filePath) {
  const parts = String(filePath).split(/[/\\]/);
  const index = parts.lastIndexOf("modules");
  return index !== -1 && index + 1 < parts.length ? parts[index + 1] : null;
}

/**
 * A module never imports a sibling module (leaf domains stay independent) — the frontend analog of
 * `terp.arch`'s `no_cross_module_imports`. Relative imports are resolved before the check, so
 * `../other/thing` from `modules/a/` is caught as a `modules/other` import, not hidden by its spelling.
 */
const noCrossModuleImports = {
  meta: {
    type: "problem",
    docs: { description: "Disallow imports between sibling app modules (leaf independence)." },
    schema: [],
  },
  create(context) {
    // physicalFilename: the on-disk file (the escape-hatch processor lints a virtual block).
    const filename = context.physicalFilename || context.filename;
    const own = moduleOf(filename);
    if (own === null) {
      return {};
    }
    const check = (node) => {
      const source = node.source && node.source.value;
      if (typeof source !== "string") {
        return;
      }
      const target = source.startsWith(".")
        ? path.resolve(path.dirname(filename), source)
        : source;
      const other = moduleOf(target);
      if (other !== null && other !== own) {
        context.report({
          node,
          message:
            `App module "${own}" must not import sibling module "${other}"; modules stay ` +
            "independent (share through the framework packages, not each other).",
        });
      }
    };
    return {
      ImportDeclaration: check,
      ImportExpression: check,
      ExportNamedDeclaration: (node) => node.source && check(node),
      ExportAllDeclaration: check,
    };
  },
};

const generatedClientMessage =
  "Use the generated typed client (useTerpClient), not a raw request that skips auth and the contract.";

function jsxName(node) {
  if (!node) {
    return null;
  }
  if (node.type === "JSXIdentifier") {
    return node.name;
  }
  if (node.type === "JSXMemberExpression") {
    const object = jsxName(node.object);
    return object ? `${object}.${node.property.name}` : node.property.name;
  }
  return null;
}

function getJsxAttribute(openingElement, name) {
  return openingElement.attributes.find(
    (attribute) => attribute.type === "JSXAttribute" && jsxName(attribute.name) === name,
  );
}

function staticStringFromJsxValue(value) {
  if (!value) {
    return null;
  }
  if (value.type === "Literal" && typeof value.value === "string") {
    return value.value;
  }
  if (value.type === "JSXExpressionContainer") {
    const expression = value.expression;
    if (expression.type === "Literal" && typeof expression.value === "string") {
      return expression.value;
    }
    if (expression.type === "TemplateLiteral" && expression.expressions.length === 0) {
      return expression.quasis.map((quasi) => quasi.value.cooked ?? quasi.value.raw).join("");
    }
  }
  return null;
}

function templateStartsWithJavascript(value) {
  if (value?.type !== "JSXExpressionContainer") {
    return false;
  }
  const expression = value.expression;
  if (expression.type !== "TemplateLiteral") {
    return false;
  }
  const first = expression.quasis[0]?.value.cooked ?? expression.quasis[0]?.value.raw ?? "";
  return /^\s*javascript\s*:/i.test(first);
}

function memberName(node) {
  if (!node || node.type !== "MemberExpression" || node.computed) {
    return null;
  }
  if (node.property.type === "Identifier") {
    return node.property.name;
  }
  return null;
}

function isObjectNamed(node, names) {
  return node?.type === "Identifier" && names.includes(node.name);
}

function isDocumentObject(node) {
  if (isObjectNamed(node, ["document"])) {
    return true;
  }
  return (
    node?.type === "MemberExpression" &&
    !node.computed &&
    memberName(node) === "document" &&
    isObjectNamed(node.object, ["window", "globalThis"])
  );
}

const noUnsafeTargetBlank = {
  meta: {
    type: "problem",
    docs: { description: "Require rel=noopener on static target=_blank links." },
    schema: [],
  },
  create(context) {
    return {
      JSXOpeningElement(node) {
        const target = getJsxAttribute(node, "target");
        if (staticStringFromJsxValue(target?.value) !== "_blank") {
          return;
        }
        const rel = staticStringFromJsxValue(getJsxAttribute(node, "rel")?.value);
        const tokens = new Set(String(rel ?? "").toLowerCase().split(/\s+/).filter(Boolean));
        if (!tokens.has("noopener")) {
          context.report({
            node: target,
            message:
              'target="_blank" must include rel="noopener" to prevent opener access; ' +
              'rel="noopener noreferrer" is recommended.',
          });
        }
      },
    };
  },
};

const noUnsafeHref = {
  meta: {
    type: "problem",
    docs: { description: "Disallow javascript: URLs in static href/src JSX attributes." },
    schema: [],
  },
  create(context) {
    const check = (node) => {
      const name = jsxName(node.name);
      if (name !== "href" && name !== "src") {
        return;
      }
      const literal = staticStringFromJsxValue(node.value);
      if (
        (literal !== null && /^\s*javascript\s*:/i.test(literal)) ||
        templateStartsWithJavascript(node.value)
      ) {
        context.report({
          node,
          message:
            "javascript: URLs are forbidden in href/src attributes; " +
            "route through safe components or typed data.",
        });
      }
    };
    return { JSXAttribute: check };
  },
};

const noDomHtmlInjection = {
  meta: {
    type: "problem",
    docs: { description: "Disallow direct DOM HTML injection sinks." },
    schema: [],
  },
  create(context) {
    const htmlProperties = new Set(["innerHTML", "outerHTML", "insertAdjacentHTML"]);
    return {
      JSXOpeningElement(node) {
        if (jsxName(node.name) === "iframe") {
          const srcDoc = getJsxAttribute(node, "srcDoc");
          if (srcDoc) {
            context.report({
              node: srcDoc,
              message: "iframe srcDoc injects HTML and is forbidden; render trusted components instead.",
            });
          }
        }
      },
      AssignmentExpression(node) {
        const property = memberName(node.left);
        if (htmlProperties.has(property)) {
          context.report({
            node: node.left,
            message: `${property} injects HTML and is forbidden; render text/components or use an allowlisted sanitizer.`,
          });
        }
      },
      CallExpression(node) {
        const callee = node.callee;
        const property = memberName(callee);
        if (
          htmlProperties.has(property) ||
          (isDocumentObject(callee?.object) && ["write", "writeln"].includes(property))
        ) {
          context.report({
            node: callee,
            message: `${property} injects HTML and is forbidden; render text/components or use an allowlisted sanitizer.`,
          });
        }
      },
    };
  },
};

const noEval = {
  meta: {
    type: "problem",
    docs: { description: "Disallow eval and Function constructors." },
    schema: [],
  },
  create(context) {
    return {
      CallExpression(node) {
        if (
          (node.callee.type === "Identifier" && node.callee.name === "eval") ||
          (memberName(node.callee) === "eval" && isObjectNamed(node.callee.object, ["window", "globalThis"]))
        ) {
          context.report({
            node: node.callee,
            message: "eval() is forbidden; execute explicit typed code paths instead.",
          });
        }
      },
      NewExpression(node) {
        if (
          (node.callee.type === "Identifier" && node.callee.name === "Function") ||
          (memberName(node.callee) === "Function" && isObjectNamed(node.callee.object, ["window", "globalThis"]))
        ) {
          context.report({
            node: node.callee,
            message: "new Function() is forbidden; execute explicit typed code paths instead.",
          });
        }
      },
    };
  },
};

/** Find the app's checked-in layout-contract config upward from *dir*; null = no contract. */
export function activeLayoutContract(dir) {
  let current = dir;
  for (;;) {
    const file = path.join(current, LAYOUT_CONTRACT_FILE);
    if (fs.existsSync(file)) {
      try {
        const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
        return typeof parsed.contract === "string" ? parsed.contract : null;
      } catch {
        return null;
      }
    }
    const parent = path.dirname(current);
    if (parent === current) {
      return null;
    }
    current = parent;
  }
}

/**
 * The build-time half of the slot-typed layout contract control (ADR 0079): when the app
 * has opted into a contract (a checked-in `layout-contract.json`, or the rule option in
 * tests), the static JSX children of each governed page archetype must be components the
 * contract allows in that slot. Dynamic children (`{...}` expressions) are deliberately
 * not resolved here — the react-core runtime half verifies the rendered DOM and refuses
 * a non-conforming view, fail closed. Both halves phrase the same directive message.
 */
const layoutContract = {
  meta: {
    type: "problem",
    docs: { description: "Enforce the app's opted-in slot-typed layout contract (ADR 0079)." },
    schema: [
      {
        type: "object",
        properties: { contract: { type: "string" } },
        additionalProperties: false,
      },
    ],
  },
  create(context) {
    const filename = context.physicalFilename || context.filename;
    const contractId =
      context.options[0]?.contract ?? activeLayoutContract(path.dirname(filename));
    if (contractId === null || contractId === undefined) {
      return {};
    }
    const contract = LAYOUT_CONTRACTS[contractId];
    if (contract === undefined) {
      return {
        Program(node) {
          context.report({
            node,
            message:
              `Unknown layout contract "${contractId}" (${LAYOUT_CONTRACT_FILE}); ` +
              `known contracts: ${Object.keys(LAYOUT_CONTRACTS).join(", ")}.`,
          });
        },
      };
    }
    const checkChild = (child, slotOwner, allowed) => {
      if (child.type === "JSXText") {
        if (child.value.trim() !== "") {
          context.report({
            node: child,
            message: slotViolationMessage(contractId, slotOwner, "raw text"),
          });
        }
        return;
      }
      if (child.type === "JSXFragment") {
        child.children.forEach((inner) => checkChild(inner, slotOwner, allowed));
        return;
      }
      if (child.type !== "JSXElement") {
        return; // dynamic content ({...}) is the runtime half's job
      }
      const name = jsxName(child.openingElement.name);
      if (name !== null && allowed[name] === undefined) {
        context.report({
          node: child.openingElement,
          message: slotViolationMessage(contractId, slotOwner, `<${name}>`),
        });
      }
    };
    return {
      JSXElement(node) {
        const owner = jsxName(node.openingElement.name);
        const slot = owner !== null ? contract.slots[owner] : undefined;
        if (slot === undefined) {
          return;
        }
        node.children.forEach((child) => checkChild(child, owner, slot.components));
      },
    };
  },
};

const terpPlugin = {
  rules: {
    "layout-contract": layoutContract,
    "no-cross-module-imports": noCrossModuleImports,
    "no-dom-html-injection": noDomHtmlInjection,
    "no-eval": noEval,
    "no-unsafe-href": noUnsafeHref,
    "no-unsafe-target-blank": noUnsafeTargetBlank,
  },
};

const deepImportMessage =
  "Import from the package root (@terp/react-core, @terp/contract), not its internals.";
const styleImportMessage =
  "Module-authored stylesheets are forbidden; theming flows from the design tokens " +
  "and layout from the react-core components (Stack, the page archetypes).";

/**
 * The `no-restricted-syntax` realisation of the BOUNDARY_SPEC families, each entry tagged
 * with the Terp Standard catalog rule it realises (`spec/catalog/frontend/<rule>.json`) so
 * a reported message stays attributable to its stack-neutral rule id (see
 * {@link catalogRuleId}). {@link restrictedSyntax} strips the tag for the ESLint config.
 */
function restrictedSyntaxWithCatalogIds() {
  const rawElements = Object.entries(BOUNDARY_SPEC.restrictedElements).map(([element, use]) => ({
    catalogId: "frontend/token-styled-elements",
    selector: `JSXOpeningElement[name.name='${element}']`,
    message: `Use ${use} from @terp/react-core, not a raw <${element}>.`,
  }));
  const rawAttributes = BOUNDARY_SPEC.restrictedAttributes.map((attribute) => ({
    catalogId: "frontend/no-inline-styling",
    selector: `JSXAttribute[name.name='${attribute}']`,
    message:
      `The ${attribute} attribute is forbidden in app modules; layout comes from the ` +
      "react-core components (Stack, Page, ...) and styling from the design tokens.",
  }));
  const inAppAnchors = BOUNDARY_SPEC.restrictInAppAnchors
    ? [
        {
          catalogId: "frontend/router-links",
          selector:
            "JSXOpeningElement[name.name='a'] JSXAttribute[name.name='href'][value.value=/^\\u002F/]",
          message:
            'An in-app <a href="/..."> bypasses the router (full reload, no role-aware guard); ' +
            "use the stack's Link.",
        },
        {
          catalogId: "frontend/router-links",
          selector:
            "JSXOpeningElement[name.name='a'] JSXAttribute[name.name='href'][value.expression.value=/^\\u002F/]",
          message:
            'An in-app <a href="/..."> bypasses the router (full reload, no role-aware guard); ' +
            "use the stack's Link.",
        },
        {
          catalogId: "frontend/router-links",
          selector:
            "JSXOpeningElement[name.name='a'] JSXAttribute[name.name='href'] TemplateLiteral[quasis.0.value.raw=/^\\u002F/]",
          message:
            'An in-app <a href="/..."> bypasses the router (full reload, no role-aware guard); ' +
            "use the stack's Link.",
        },
      ]
    : [];
  return [
    ...rawElements,
    ...rawAttributes,
    ...inAppAnchors,
    {
      catalogId: "frontend/no-dom-html-injection",
      selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
      message: "dangerouslySetInnerHTML is forbidden (XSS); render text or use an allowlisted sanitizer.",
    },
    {
      catalogId: "frontend/no-inline-styling",
      selector: "Literal[value=/#[0-9a-fA-F]{3,8}/]",
      message: "Use a design token (var(--color-...)), not a hardcoded colour that bypasses the theme.",
    },
    {
      catalogId: "frontend/generated-client-only",
      selector:
        "CallExpression[callee.type='MemberExpression'][callee.object.name=/^(window|globalThis)$/][callee.property.name='fetch'], CallExpression[callee.type='MemberExpression'][callee.object.name=/^(window|globalThis)$/][callee.computed=true][callee.property.value='fetch']",
      message: generatedClientMessage,
    },
    {
      catalogId: "frontend/generated-client-only",
      selector:
        "NewExpression[callee.name=/^(XMLHttpRequest|WebSocket|EventSource)$/], NewExpression[callee.type='MemberExpression'][callee.object.name=/^(window|globalThis)$/][callee.property.name=/^(XMLHttpRequest|WebSocket|EventSource)$/], NewExpression[callee.type='MemberExpression'][callee.object.name=/^(window|globalThis)$/][callee.computed=true][callee.property.value=/^(XMLHttpRequest|WebSocket|EventSource)$/]",
      message: generatedClientMessage,
    },
    {
      catalogId: "frontend/generated-client-only",
      selector:
        "CallExpression[callee.type='MemberExpression'][callee.object.name='navigator'][callee.property.name='sendBeacon']",
      message: generatedClientMessage,
    },
    {
      catalogId: "frontend/generated-client-only",
      selector:
        "CallExpression[callee.type='MemberExpression'][callee.object.type='MemberExpression'][callee.object.object.name=/^(window|globalThis)$/][callee.object.property.name='navigator'][callee.property.name='sendBeacon'], CallExpression[callee.type='MemberExpression'][callee.object.type='MemberExpression'][callee.object.object.name=/^(window|globalThis)$/][callee.object.property.name='navigator'][callee.computed=true][callee.property.value='sendBeacon'], CallExpression[callee.type='MemberExpression'][callee.object.type='MemberExpression'][callee.object.object.name=/^(window|globalThis)$/][callee.object.computed=true][callee.object.property.value='navigator'][callee.property.name='sendBeacon'], CallExpression[callee.type='MemberExpression'][callee.object.type='MemberExpression'][callee.object.object.name=/^(window|globalThis)$/][callee.object.computed=true][callee.object.property.value='navigator'][callee.computed=true][callee.property.value='sendBeacon']",
      message: generatedClientMessage,
    },
  ];
}

function restrictedSyntax() {
  return restrictedSyntaxWithCatalogIds().map(({ selector, message }) => ({ selector, message }));
}

/** Exact `no-restricted-syntax` message -> Terp Standard catalog id (built from one source). */
const CATALOG_ID_BY_SYNTAX_MESSAGE = new Map(
  restrictedSyntaxWithCatalogIds().map((entry) => [entry.message, entry.catalogId]),
);

/**
 * The Terp Standard catalog rule id (`frontend/<rule>`, per `spec/catalog/frontend/`) a
 * reported ESLint message realises, or null for a message outside the boundary. This is the
 * adapter's published `reported_as -> catalog id` mapping: several catalog rules share a core
 * ESLint rule id (`no-restricted-syntax` / `no-restricted-imports` / `no-restricted-globals`),
 * so the conformance contract — and the corpus harness — attributes findings through this
 * function, never through the raw ESLint rule id.
 */
export function catalogRuleId(message) {
  const ruleId = String(message.ruleId ?? "");
  const text = String(message.message ?? "");
  if (ruleId.startsWith("terp/")) {
    return `frontend/${ruleId.slice("terp/".length)}`;
  }
  if (ruleId === "no-restricted-globals") {
    return "frontend/generated-client-only";
  }
  if (ruleId === "no-restricted-syntax") {
    return CATALOG_ID_BY_SYNTAX_MESSAGE.get(text) ?? null;
  }
  if (ruleId === "no-restricted-imports") {
    // ESLint prefixes the configured pattern message with its own preamble.
    if (text.includes(styleImportMessage)) {
      return "frontend/no-style-imports";
    }
    if (text.includes(deepImportMessage)) {
      return "frontend/no-deep-imports";
    }
    return null;
  }
  return null;
}

/**
 * Every Terp Standard catalog rule id (`frontend/<rule>`) this adapter evaluates, sorted:
 * the named `terp/*` plugin rules, `terp/escape-hatch` (emitted by the suppression
 * processor), the tagged `no-restricted-syntax` families, and the catalog rules realised
 * through `no-restricted-globals` / `no-restricted-imports`. This is the evaluated-rule
 * inventory a boundary lint run publishes in its findings envelope (see ./findings.js):
 * a consumer joining findings to the catalog reads the inventory from the run itself, so
 * a per-rule "pass" can never be claimed for a rule this adapter never ran (fail closed
 * under version skew). Parity with `spec/catalog/frontend/` is locked by findings.test.js.
 */
export function catalogRuleIds() {
  return [
    ...new Set([
      ...Object.keys(terpPlugin.rules).map((rule) => `frontend/${rule}`),
      "frontend/escape-hatch",
      ...restrictedSyntaxWithCatalogIds().map((entry) => entry.catalogId),
      "frontend/generated-client-only",
      "frontend/no-deep-imports",
      "frontend/no-style-imports",
    ]),
  ].sort();
}

/** The marker name a message's ruleId answers to (`terp/x` -> `x`; core ruleIds as-is). */
function markerNameFor(ruleId) {
  return String(ruleId ?? "").replace(/^terp\//, "");
}

const MARKER_RE = () =>
  new RegExp(`${BOUNDARY_SPEC.allowMarkerPrefix}([a-z0-9-]+)(?::[ \\t]*(.*?))?\\s*(?:\\*+\\/\\s*}?)?\\s*$`);

/** Every escape-hatch marker in *text*: `{ line, rule, reason }` (reason null = unjustified). */
export function parseAllowMarkers(text) {
  const markers = [];
  const pattern = MARKER_RE();
  String(text)
    .split(/\r?\n/)
    .forEach((lineText, index) => {
      if (!lineText.includes(BOUNDARY_SPEC.allowMarkerPrefix)) {
        return;
      }
      const match = pattern.exec(lineText);
      if (match) {
        const reason = match[2]?.trim();
        markers.push({ line: index + 1, rule: match[1], reason: reason ? reason : null });
      }
    });
  return markers;
}

/**
 * Apply the governed escape hatch to a lint result (the frontend analog of the backend's
 * justified `# arch-allow-<rule>: <reason>` suppressions): a marker with a reason, on the
 * violating line or the line immediately above, suppresses that rule there. An unjustified
 * marker (no reason) is itself reported — never silently honoured. Marker counts are governed
 * by the budget ratchet (./budget.js), so opt-outs stay visible, greppable, and can only shrink.
 */
export function suppressWithMarkers(messages, text) {
  const markers = parseAllowMarkers(text);
  const justified = markers.filter((marker) => marker.reason !== null);
  const kept = messages.filter((message) => {
    const name = markerNameFor(message.ruleId);
    return !justified.some(
      (marker) =>
        marker.rule === name && (marker.line === message.line || marker.line === message.line - 1),
    );
  });
  const unjustified = markers
    .filter((marker) => marker.reason === null)
    .map((marker) => ({
      ruleId: "terp/escape-hatch",
      severity: 2,
      line: marker.line,
      column: 1,
      message:
        "An escape-hatch marker needs a justification: " +
        `"${BOUNDARY_SPEC.allowMarkerPrefix}${marker.rule}: <reason>". ` +
        "An unjustified marker is reported, never silently honoured.",
    }));
  return [...kept, ...unjustified];
}

/**
 * The escape-hatch processor: lints the file as-is (one virtual block), then filters the
 * messages through {@link suppressWithMarkers} so a justified marker suppresses its violation
 * and an unjustified marker becomes one.
 */
function escapeHatchProcessor() {
  const sources = new Map();
  return {
    meta: { name: "terp-escape-hatch" },
    preprocess(text, filename) {
      sources.set(filename, text);
      return [{ text, filename: `0${path.extname(filename)}` }];
    },
    postprocess(messageLists, filename) {
      const text = sources.get(filename) ?? "";
      sources.delete(filename);
      return suppressWithMarkers(messageLists.flat(), text);
    },
  };
}

/**
 * The Terp frontend boundary config (an ESLint flat-config array), scoped to app modules. Spread it
 * into a repo's `eslint.config.js`:
 *
 *   import terpBoundaries from "@terp/eslint-boundaries";
 *   export default [{ ignores: ["dist/**", "src/api/**"] }, ...terpBoundaries];
 */
export function terpBoundaries() {
  return [
    {
      files: BOUNDARY_SPEC.moduleFiles,
      processor: escapeHatchProcessor(),
    },
    {
      files: BOUNDARY_SPEC.moduleFiles,
      // Inline `eslint-disable` comments are inert in app modules; the justified
      // `terp-allow-*` marker (budget-governed) is the *only* escape hatch (ADR 0059).
      linterOptions: { noInlineConfig: true },
      languageOptions: {
        parser: tseslint.parser,
        parserOptions: { ecmaFeatures: { jsx: true }, sourceType: "module" },
      },
      plugins: { terp: terpPlugin },
      rules: {
        "terp/layout-contract": "error",
        "terp/no-cross-module-imports": "error",
        "terp/no-dom-html-injection": "error",
        "terp/no-eval": "error",
        "terp/no-unsafe-href": "error",
        "terp/no-unsafe-target-blank": "error",
        "no-restricted-syntax": ["error", ...restrictedSyntax()],
        "no-restricted-globals": [
          "error",
          ...BOUNDARY_SPEC.restrictedGlobals.map((name) => ({
            name,
            message: generatedClientMessage,
          })),
        ],
        "no-restricted-imports": [
          "error",
          {
            patterns: [
              {
                group: BOUNDARY_SPEC.internalImportPatterns,
                message: deepImportMessage,
              },
              {
                group: BOUNDARY_SPEC.styleImportPatterns,
                message: styleImportMessage,
              },
            ],
          },
        ],
      },
    },
  ];
}

export { LAYOUT_CONTRACTS, LAYOUT_CONTRACT_FILE, slotViolationMessage } from "./layouts.js";
export { BOUNDARY_SPEC };
export default terpBoundaries();
