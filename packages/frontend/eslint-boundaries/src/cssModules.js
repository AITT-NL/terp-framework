import fs from "node:fs";
import path from "node:path";

import postcss from "postcss";

// A sibling file keeps the stylesheet in the component's module boundary. The name holds no
// slash, so the file sits beside the component; dots are allowed (`Board.lanes.module.css`).
export const localModuleSource = String.raw`\./[A-Za-z0-9_][A-Za-z0-9_.-]*\.module\.css`;
const localModule = new RegExp(`^${localModuleSource}$`);

// CSS Modules scope class names, but also accept global selectors, cross-file composition
// and imports. Accept a small stylesheet grammar whose rules target local classes only.
// A class is named as a script identifier: Vite exports `.task-card` as "task-card", which
// `className={styles.x}` cannot name, so a hyphenated class would be one no element can use.
const states = String.raw`(?::(?:focus|focus-visible|focus-within|hover|active|disabled))*`;
const selector = new RegExp(String.raw`^\.[A-Za-z_][A-Za-z0-9_]*` + states + "$");
const hyphenated = new RegExp(String.raw`^\.([A-Za-z_][\w-]*)` + states + "$");
const camel = (name) => name.replace(/-+([A-Za-z0-9])/g, (_, letter) => letter.toUpperCase()).replace(/-/g, "");

// Keep composition expressive while leaving paint, focus indicators and theme ownership
// with the framework. Shorthands that can paint need the same checks as longhands.
const layoutProperties = new Set(`
  display box-sizing inset inset-inline inset-inline-start inset-inline-end inset-block inset-block-start inset-block-end
  top right bottom left aspect-ratio width height min-width min-height max-width max-height
  block-size inline-size min-block-size min-inline-size max-block-size max-inline-size
  margin margin-top margin-right margin-bottom margin-left margin-inline margin-inline-start margin-inline-end
  margin-block margin-block-start margin-block-end padding padding-top padding-right padding-bottom padding-left
  padding-inline padding-inline-start padding-inline-end padding-block padding-block-start padding-block-end
  gap row-gap column-gap grid grid-area grid-auto-columns grid-auto-flow grid-auto-rows grid-column grid-column-start
  grid-column-end grid-row grid-row-start grid-row-end grid-template grid-template-areas grid-template-columns
  grid-template-rows flex flex-basis flex-direction flex-flow flex-grow flex-shrink flex-wrap order align-content
  align-items align-self justify-content justify-items justify-self place-content place-items place-self
  overflow overflow-x overflow-y overflow-wrap font font-family font-size font-style font-weight line-height
  letter-spacing word-spacing white-space text-align text-transform text-wrap list-style-type border-radius
  border-top-left-radius border-top-right-radius border-bottom-left-radius border-bottom-right-radius container-name container-type
`.trim().split(/\s+/));

/**
 * Paint takes a palette role, not merely a `--color-*` token. Every ink here over every surface
 * here is a text pair the palette declares and holds to AA in every theme (index.test.js checks
 * that against @terpjs/contract's token-pairs.json), so a pairing an app forms from them, on one
 * element or across two, is one the palette already measures. The surfaces are the three the
 * framework sets its own components on (the canvas, a surface, a subtle container), so a
 * framework control an app places on one meets no background it does not meet in the
 * framework's own pages. A brand fill, a status ink, the accent, the summary band and the
 * primitive ramp stay with the framework controls that carry their partners.
 */
export const PAINT_ROLES = {
  ink: ["--color-fg-default", "--color-fg-muted", "--color-fg-subtle"],
  surface: ["--color-bg-canvas", "--color-bg-surface", "--color-bg-subtle"],
  border: ["--color-border-default", "--color-border-strong", "--color-border-subtle"],
};
const roleToken = (role) => new RegExp(String.raw`^var\(\s*(?:${PAINT_ROLES[role].join("|")})\s*\)$`);
const listed = (role) => PAINT_ROLES[role].map((token) => `var(${token})`).join(", ");
const PAINT = {
  color: { role: "ink", keywords: ["currentColor", "inherit"] },
  background: { role: "surface", keywords: ["transparent"] },
  "background-color": { role: "surface", keywords: ["transparent"] },
  "border-color": { role: "border", keywords: ["transparent", "currentColor"] },
};
const border = /^border(?:-(?:top|right|bottom|left|(?:block|inline)(?:-start|-end)?))?$/;
const borderValue = new RegExp(
  String.raw`^(?:0|none|(?:0|(?:\d*\.)?\d+(?:px|em|rem))\s+(?:solid|dashed|dotted|double)\s+` +
  String.raw`(?:var\(\s*(?:${PAINT_ROLES.border.join("|")})\s*\)|currentColor|transparent))$`, "i");

/**
 * The ink and type properties a descendant inherits. On an element that holds a component they
 * would reach into it and restyle text the framework owns, so they belong on an element whose
 * content is the app's own text. A list marker is left out: it paints only a list item, and a
 * list of the app's own tiles has to be able to drop its bullets whatever the tiles hold.
 */
const INHERITED = new Set(`
  color font font-family font-size font-style font-weight line-height letter-spacing word-spacing
  text-align text-transform white-space text-wrap overflow-wrap
`.trim().split(/\s+/));

/** Why a declaration is refused, as the remedy to apply, or null when it is admitted. */
function declarationProblem(node) {
  const prop = node.prop.toLowerCase();
  const value = node.value.trim();
  if (node.important) return `drop !important from ${prop}: the stylesheet orders app and framework rules itself`;
  if (prop === "position") {
    return ["static", "relative", "absolute", "sticky"].includes(value)
      ? null : "position takes static, relative, absolute or sticky";
  }
  if (prop === "list-style") return value === "none" ? null : "list-style takes none; list-style-type sets a marker";
  // A string or symbols() marker renders as text, which no catalog translates.
  if (prop === "list-style-type") {
    return /^[a-z][a-z-]*$/i.test(value) ? null
      : "list-style-type takes a counter style keyword, such as disc or decimal; a string or symbols() puts copy on screen that no catalog translates, so write it in the markup with Trans";
  }
  const paint = PAINT[prop];
  if (paint) {
    if (roleToken(paint.role).test(value) || paint.keywords.includes(value)) return null;
    return `${prop} takes ${paint.role === "ink" ? "an" : "a"} ${paint.role} token, one of ${listed(paint.role)}, with no fallback, or ${paint.keywords.join(" or ")}`;
  }
  if (border.test(prop)) {
    return borderValue.test(value) ? null
      : `${prop} takes none, or a width, a style and a border token, such as 1px solid var(--color-border-default)`;
  }
  return layoutProperties.has(prop) ? null
    : `${prop} is not among the properties a CSS Module may set (layout, typography, and paint through color, ` +
      "background, background-color, border-color and the border shorthands); what it would style belongs to " +
      "the react-core component that owns it, or to a token or prop asked of the framework";
}

/**
 * Read one level of the stylesheet: the file itself, or a responsive group inside it. Every
 * problem is reported, each with the line it is on, so one run names all of them.
 */
function inspectContainer(container, file, sheet) {
  const at = (node) => `${path.basename(file)}:${node.source.start.line}`;
  for (const node of container.nodes ?? []) {
    if (node.type === "comment") continue;
    if (node.type === "atrule" && ["media", "container", "supports"].includes(node.name) && node.nodes) {
      inspectContainer(node, file, sheet);
      continue;
    }
    if (node.type === "atrule") {
      sheet.problems.push(`${at(node)}: @${node.name} is refused; group rules only in @media, @container or @supports.`);
      continue;
    }
    if (node.type !== "rule") {
      sheet.problems.push(`${at(node)}: a declaration belongs inside a rule for one of this module's classes.`);
      continue;
    }
    const outside = node.selectors.filter((part) => !selector.test(part));
    if (outside.length) {
      for (const part of outside) {
        const name = hyphenated.exec(part)?.[1];
        sheet.problems.push(name
          ? `${at(node)}: .${name} cannot be named from script, since className reads a class as styles.<name>; call it .${camel(name)}.`
          : `${at(node)}: ${part} is not a selector a CSS Module may use: select one of its own classes, optionally with ` +
            ":hover, :focus, :focus-visible, :focus-within, :active or :disabled. For a state the component knows, " +
            "give the element another class: className={active ? styles.active : styles.lane}.");
      }
      continue;
    }
    const names = node.selectors.map((part) => part.slice(1).split(":")[0]);
    for (const name of names) sheet.classes.add(name);
    for (const child of node.nodes) {
      if (child.type === "comment") continue;
      if (child.type !== "decl") {
        sheet.problems.push(`${at(child)}: a rule holds declarations only; nest no rule or at-rule inside it.`);
        continue;
      }
      const problem = declarationProblem(child);
      if (problem) sheet.problems.push(`${at(child)}: ${problem}.`);
      if (INHERITED.has(child.prop.toLowerCase())) {
        for (const name of names) {
          if (!sheet.inherited.has(name)) sheet.inherited.set(name, new Set());
          sheet.inherited.get(name).add(child.prop.toLowerCase());
        }
      }
    }
  }
}

function inspectStylesheet(file) {
  const sheet = { classes: new Set(), inherited: new Map(), problems: [] };
  const name = path.basename(file);
  let text;
  try {
    text = fs.readFileSync(file, "utf8");
  } catch {
    sheet.problems.push(`${name} is not beside this component: create it there, or import the sibling module that is.`);
    return sheet;
  }
  let root;
  try {
    root = postcss.parse(text, { from: file });
  } catch (error) {
    sheet.problems.push(`${name}:${error.line ?? 1}: ${error.reason ?? "the stylesheet does not parse"}; fix the CSS on that line.`);
    return sheet;
  }
  inspectContainer(root, file, sheet);
  return sheet;
}

// Both ESLint rules see the same SourceCode for one lint pass. A new pass reads
// the stylesheet again, even if the importing source text did not change.
const sheetsBySource = new WeakMap();
function sheetFor(context, source) {
  let sheets = sheetsBySource.get(context.sourceCode);
  if (!sheets) {
    sheets = new Map();
    sheetsBySource.set(context.sourceCode, sheets);
  }
  if (!sheets.has(source)) {
    sheets.set(source, inspectStylesheet(path.resolve(path.dirname(context.physicalFilename), source)));
  }
  return sheets.get(source);
}

export const moduleImports = {
  meta: { type: "problem", schema: [], messages: { stylesheetContent: "{{detail}}" } },
  create(context) {
    return {
      "ImportDeclaration, ExportNamedDeclaration, ExportAllDeclaration"(node) {
        const source = node.source?.value;
        if (!localModule.test(source)) return;
        const binding = node.specifiers?.[0];
        if (node.type !== "ImportDeclaration" || node.specifiers.length !== 1
            || binding.type !== "ImportDefaultSpecifier" || node.importKind === "type") {
          context.report({ node, message: `Import the sibling CSS Module with one static default binding: import styles from "${source}".` });
        }
        for (const detail of sheetFor(context, source).problems) {
          context.report({ node, messageId: "stylesheetContent", data: { detail } });
        }
      },
    };
  },
};

/** `styles.board` where `styles` is the default binding of a sibling CSS Module, as `{ source, name }`. */
function moduleMember(context, node, expression) {
  if (expression?.type !== "MemberExpression" || expression.computed || expression.optional
      || expression.object.type !== "Identifier") return null;
  let scope = context.sourceCode.getScope(node);
  while (scope && !scope.set.has(expression.object.name)) scope = scope.upper;
  const def = scope?.set.get(expression.object.name)?.defs[0];
  if (def?.type !== "ImportBinding" || def.node.type !== "ImportDefaultSpecifier"
      || !localModule.test(def.parent.source.value)) return null;
  return { source: def.parent.source.value, name: expression.property.name };
}

// Read as the app's own text: words, an expression that renders no element and reads no
// `children`, a Trans, a fragment, and native elements holding the same.
const TRANSPARENT = new Set(["Trans", "Fragment", "React.Fragment"]);

/**
 * The first thing inside *element* the lint cannot read as the app's own text: a component, a
 * `children` read in any spelling, a spread or a `children` attribute. Null when there is none.
 */
function notAppText(element, sourceCode) {
  const attributesHold = (opening) => {
    for (const attribute of opening.attributes) {
      if (attribute.type === "JSXSpreadAttribute") return `a spread of ${sourceCode.getText(attribute.argument)}`;
      if (attribute.name.name === "children") return "a children attribute";
    }
    return null;
  };
  const own = attributesHold(element.openingElement);
  if (own) return own;
  const stack = [...element.children];
  while (stack.length) {
    const node = stack.pop();
    if (!node || typeof node.type !== "string") continue;
    if (node.type === "JSXElement") {
      const tag = node.openingElement.name;
      const name = sourceCode.getText(tag);
      if (!(tag.type === "JSXIdentifier" && /^[a-z]/.test(name)) && !TRANSPARENT.has(name)) return `<${name}>`;
      const held = attributesHold(node.openingElement);
      if (held) return held;
      stack.push(...node.children);
      continue;
    }
    if (node.type === "Identifier" && node.name === "children") return "{children}";
    if (node.type === "MemberExpression" && !node.computed && node.property.name === "children") {
      return `{${sourceCode.getText(node)}}`;
    }
    for (const key of sourceCode.visitorKeys[node.type] ?? []) {
      const value = node[key];
      if (Array.isArray(value)) stack.push(...value);
      else if (value) stack.push(value);
    }
  }
  return null;
}

/** Whether *identifier* sits inside a `className` attribute, whatever the expression's shape. */
function insideClassName(identifier) {
  for (let node = identifier.parent; node; node = node.parent) {
    if (node.type === "JSXAttribute") return node.name.name === "className";
    if (node.type === "JSXElement" || node.type === "JSXFragment" || node.type === "Program") return false;
  }
  return false;
}

export const moduleClassNames = {
  meta: { type: "problem", schema: [] },
  create(context) {
    const report = (node, message) => context.report({ node, message });
    return {
      // A module's binding is read nowhere but in a className: passed on through a spread, a call
      // or a variable, its class could land on a framework control, where no check could see it.
      ImportDeclaration(node) {
        if (!localModule.test(node.source.value)) return;
        for (const variable of context.sourceCode.getDeclaredVariables(node)) {
          for (const { identifier } of variable.references) {
            if (insideClassName(identifier)) continue;
            report(identifier,
              `${variable.name} is read only in a className on a native element: className={${variable.name}.board}, or ` +
              `className={active ? ${variable.name}.active : ${variable.name}.board}. A module class passed on through a ` +
              "spread, a call or a variable could reach a framework control.");
          }
        }
      },
      "JSXAttribute[name.name='className']"(node) {
        const expression = node.value?.type === "JSXExpressionContainer" ? node.value.expression : null;
        const branches = expression?.type === "ConditionalExpression"
          ? [expression.consequent, expression.alternate] : [expression];
        const members = branches.map((branch) => moduleMember(context, node, branch));
        if (members.some((member) => member === null)) {
          report(node,
            "className takes one class of a sibling CSS Module: className={styles.board}, after " +
            'import styles from "./Board.module.css". For a style that follows a state, choose between ' +
            "two of its classes: className={active ? styles.active : styles.board}.");
          return;
        }
        const tag = node.parent.name;
        if (tag.type !== "JSXIdentifier" || !/^[a-z]/.test(tag.name)) {
          report(node,
            `A module class goes on a native element, never on <${context.sourceCode.getText(tag)}>: a framework ` +
            "component takes its props, and keeps the styling and focus treatment it ships with.");
          return;
        }
        for (const { source, name } of members) {
          const sheet = sheetFor(context, source);
          if (sheet.problems.length) continue; // Reported at the import, by line.
          if (!sheet.classes.has(name)) {
            const known = [...sheet.classes].sort().join(", ") || "none yet";
            report(node, `${source} defines no .${name} class: define it there, or use one it has (${known}).`);
            continue;
          }
          const inherited = [...(sheet.inherited.get(name) ?? [])].sort();
          const holder = inherited.length ? notAppText(node.parent.parent, context.sourceCode) : null;
          if (holder) {
            report(node,
              `.${name} sets ${inherited.join(", ")}, which ${holder} inside this element would inherit: ink and ` +
              "type go on an element that holds only the app's own text (words, expressions, Trans, and native " +
              "elements around them), so keep the component, children or spread outside it.");
          }
        }
      },
    };
  },
};
