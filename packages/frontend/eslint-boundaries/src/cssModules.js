import fs from "node:fs";
import path from "node:path";

import postcss from "postcss";

// A sibling file keeps the stylesheet in the component's module boundary.
export const localModuleSource = String.raw`\./[A-Za-z0-9_-]+\.module\.css`;
const localModule = new RegExp(`^${localModuleSource}$`);

// CSS Modules scope class names, but also accept global selectors, cross-file composition
// and imports. Accept a small stylesheet grammar whose rules target local classes only.
const selector = /^\.[A-Za-z_][\w-]*(?::(?:focus|focus-visible|focus-within|hover|active|disabled))*$/;

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
  if (prop === "color" || prop === "background" || prop === "background-color" || prop === "border-color") {
    if (themeColor.test(value)) return null;
    if (prop === "color" && (value === "currentColor" || value === "inherit")) return null;
    if (prop !== "color" && (value === "transparent" || (prop === "border-color" && value === "currentColor"))) return null;
    return `${prop} takes a theme token, var(--color-...), with no fallback`;
  }
  if (border.test(prop)) {
    return borderValue.test(value) ? null : `${prop} takes none, or a width, a style and a var(--color-...) token`;
  }
  return layoutProperties.has(prop) ? null
    : `${prop} is not a layout or typography property; paint comes from var(--color-...) tokens and framework controls own focus styling`;
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
  root.walk((node) => {
    if (node.type === "comment") return;
    if (node.type === "atrule" && node.parent.type !== "rule"
        && ["media", "container", "supports"].includes(node.name) && node.nodes) return;
    if (node.type === "rule" && node.parent.type !== "rule" && node.selectors.every((part) => selector.test(part))) {
      for (const part of node.selectors) classes.add(part.slice(1).split(":")[0]);
      return;
    }
    const location = `${path.basename(file)}:${node.source.start.line}`;
    if (node.type === "decl" && node.parent.type === "rule") {
      const problem = declarationProblem(node);
      if (problem) problems.push(`${location}: ${problem}.`);
      return;
    }
    problems.push(`${location}: use local class selectors and responsive groups (@media, @container or @supports).`);
    return false;
  });
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
