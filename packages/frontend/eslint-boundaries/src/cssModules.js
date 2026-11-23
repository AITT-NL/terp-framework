import fs from "node:fs";
import path from "node:path";

import postcss from "postcss";

// A sibling file keeps the stylesheet in the component's module boundary.
export const localModuleSource = String.raw`\./[A-Za-z0-9_-]+\.module\.css`;
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
const themeColor = /^var\(\s*--color-[a-z0-9-]+\s*\)$/;
const border = /^border(?:-(?:top|right|bottom|left|(?:block|inline)(?:-start|-end)?))?$/;
const borderValue = /^(?:0|none|(?:0|(?:\d*\.)?\d+(?:px|em|rem))\s+(?:solid|dashed|dotted|double)\s+(?:var\(\s*--color-[a-z0-9-]+\s*\)|currentColor|transparent))$/i;

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
  if (prop === "color" || prop === "background" || prop === "background-color" || prop === "border-color") {
    if (themeColor.test(value)) return null;
    const keywords = { color: ["currentColor", "inherit"], "border-color": ["transparent", "currentColor"] }[prop] ?? ["transparent"];
    if (keywords.includes(value)) return null;
    return `${prop} takes a theme token, var(--color-...), with no fallback, or ${keywords.join(" or ")}`;
  }
  if (border.test(prop)) {
    return borderValue.test(value) ? null : `${prop} takes none, or a width, a style and a var(--color-...) token`;
  }
  return layoutProperties.has(prop) ? null
    : `${prop} is not admitted: a stylesheet sets layout and typography properties, and paints only through ` +
      "color, background, background-color, border-color and the border shorthands " +
      "(border-top: 1px solid var(--color-...)); framework controls own focus styling";
}

/**
 * Read one level of the stylesheet: the file itself, or a responsive group inside it. Every
 * problem is reported, each with the line it is on, so one run names all of them.
 */
function inspectContainer(container, file, classes, problems) {
  const at = (node) => `${path.basename(file)}:${node.source.start.line}`;
  for (const node of container.nodes ?? []) {
    if (node.type === "comment") continue;
    if (node.type === "atrule" && ["media", "container", "supports"].includes(node.name) && node.nodes) {
      inspectContainer(node, file, classes, problems);
      continue;
    }
    if (node.type === "atrule") {
      problems.push(`${at(node)}: @${node.name} is refused; group rules only in @media, @container or @supports.`);
      continue;
    }
    if (node.type !== "rule") {
      problems.push(`${at(node)}: a declaration belongs inside a rule for one of this module's classes.`);
      continue;
    }
    const outside = node.selectors.filter((part) => !selector.test(part));
    if (outside.length) {
      for (const part of outside) {
        const name = hyphenated.exec(part)?.[1];
        problems.push(name
          ? `${at(node)}: .${name} cannot be named from script, since className reads a class as styles.<name>; call it .${camel(name)}.`
          : `${at(node)}: ${part} selects outside this module; select its own classes only, such as .board or .board:hover.`);
      }
      continue;
    }
    for (const part of node.selectors) classes.add(part.slice(1).split(":")[0]);
    for (const child of node.nodes) {
      if (child.type === "comment") continue;
      if (child.type !== "decl") {
        problems.push(`${at(child)}: a rule holds declarations only; nest no rule or at-rule inside it.`);
        continue;
      }
      const problem = declarationProblem(child);
      if (problem) problems.push(`${at(child)}: ${problem}.`);
    }
  }
}

function inspectStylesheet(file) {
  const classes = new Set();
  const problems = [];
  let root;
  try {
    root = postcss.parse(fs.readFileSync(file, "utf8"), { from: file });
  } catch {
    return { classes, problems: [`${path.basename(file)} must exist beside this component and parse as CSS.`] };
  }
  inspectContainer(root, file, classes, problems);
  return { classes, problems };
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
          context.report({ node, message: "Import the sibling CSS Module statically with a single default binding." });
        }
        for (const detail of sheetFor(context, source).problems) {
          context.report({ node, messageId: "stylesheetContent", data: { detail } });
        }
      },
    };
  },
};

export const moduleClassNames = {
  meta: { type: "problem", schema: [] },
  create(context) {
    return {
      "JSXAttribute[name.name='className']"(node) {
        const member = node.value?.expression;
        if (member?.type === "MemberExpression" && !member.computed && member.object.type === "Identifier") {
          const name = member.object.name;
          let scope = context.sourceCode.getScope(node);
          while (scope && !scope.set.has(name)) scope = scope.upper;
          const def = scope?.set.get(name)?.defs[0];
          if (def?.type === "ImportBinding" && def.node.type === "ImportDefaultSpecifier"
              && localModule.test(def.parent.source.value)) {
            const tag = node.parent.name;
            if (tag.type !== "JSXIdentifier" || !/^[a-z]/.test(tag.name)) {
              context.report({ node, message: "Apply local classes to native layout elements. Style framework components through their supported props." });
              return;
            }
            const source = def.parent.source.value;
            const sheet = sheetFor(context, source);
            if (sheet.problems.length || sheet.classes.has(member.property.name)) return;
            const known = [...sheet.classes].sort().join(", ") || "none yet";
            context.report({
              node,
              message: `${source} defines no .${member.property.name} class: define it there, or use one it has (${known}).`,
            });
            return;
          }
        }
        context.report({ node, message: "The className attribute takes a class of a sibling CSS Module, for example styles.board from import styles from \"./Board.module.css\"." });
      },
    };
  },
};
