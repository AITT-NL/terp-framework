import fs from "node:fs";
import path from "node:path";

import postcss from "postcss";

/**
 * The bootstrap's own two stylesheets, read by `terp/no-style-imports` (ADR 0225).
 *
 * The bootstrap imports three global sheets and no others: the framework's tokens,
 * `./house-style.css`, which an organisation's styling tool writes, and `./theme.css`, the app's
 * own. The rule read none of them, so the last two could hold any CSS at all, and an unlayered
 * rule there beats every rule in the framework's layered sheet: a selector on a react-core marker
 * restyled a component with nothing checking it, its contrast measured by nobody, and nothing to
 * say when the marker moved. What the two sheets are for is design tokens, so that is what they
 * may hold: custom properties under `:root`, a palette's `[data-theme='<name>']` (alone or in a
 * list beside its earlier names), and `:root:not([data-theme])` inside a `prefers-color-scheme`
 * group, which is how a palette follows the viewer's platform; plus `@font-face`, for a typeface
 * the app serves itself. A rule a token cannot express goes in a stylesheet of the app's own,
 * imported under the import opt-out, which leaves that file unread: the escape is the one there
 * already was, and it is never quiet.
 */
export const BOOTSTRAP_SHEETS = ["./house-style.css", "./theme.css"];

/**
 * Whether `filename` is the app's bootstrap: `src/main.tsx` or `src/main.ts`, not inside a
 * module and not under a `src/` nested in another, exactly as the config block that admits the
 * three global imports selects it (`BOUNDARY_SPEC.bootstrapFiles` and its ignores). Only there
 * is a bootstrap sheet's import allowed at all, so only there is its content the question.
 */
export function isBootstrapFile(filename, cwd) {
  const parts = path.relative(cwd, filename).split(path.sep);
  if (parts[0] === ".." || path.isAbsolute(parts[0] ?? "")) return false;
  const name = parts.at(-1);
  return (name === "main.tsx" || name === "main.ts")
    && parts.at(-2) === "src"
    && !parts.includes("modules")
    && parts.filter((part) => part === "src").length === 1;
}

const PALETTE = String.raw`[a-z][a-z0-9-]*`;
const PALETTE_SELECTOR = new RegExp(
  String.raw`^(?::root)?\[data-theme=(?:'${PALETTE}'|"${PALETTE}"|${PALETTE})\]$`,
);
const UNPINNED = ":root:not([data-theme])";

/** The @font-face descriptors a typeface needs. Every other name is a property, not a descriptor. */
const FONT_DESCRIPTORS = new Set([
  "font-family", "src", "font-weight", "font-style", "font-stretch", "font-display",
  "unicode-range", "font-feature-settings", "font-variation-settings", "size-adjust",
  "ascent-override", "descent-override", "line-gap-override",
]);

/** Where to put a rule this sheet refuses, said once, in every refusal that needs it. */
const ELSEWHERE =
  "set the token or role that governs it (terp guide theming), or put the rule in a stylesheet " +
  "of the app's own, imported in src/main.tsx under a justified // terp-allow-no-style-imports: " +
  "<reason> marker";

function selectorProblem(part, inPreference) {
  if (part === ":root" || PALETTE_SELECTOR.test(part)) return null;
  if (part === UNPINNED) {
    return inPreference ? null
      : `${UNPINNED} declares the palette that follows the viewer's platform, so it belongs inside an @media (prefers-color-scheme: light|dark) group`;
  }
  return `${part} is not a selector this sheet may use: it declares tokens, under :root, ` +
    `[data-theme='<palette>'] or, inside a prefers-color-scheme group, ${UNPINNED}. To restyle a ` +
    `component, ${ELSEWHERE}`;
}

function tokenProblem(node) {
  const prop = node.prop;
  if (!prop.startsWith("--")) {
    return `${prop} is not a token: this sheet declares custom properties (--name: value) only. To ` +
      `change what ${prop} does, ${ELSEWHERE}`;
  }
  if (node.important) return `drop !important from ${prop}: a token is declared once, where its palette is, and needs no priority`;
  if (/url\(/i.test(node.value)) {
    return `${prop} takes no url(): no token holds a file. A font file is declared in @font-face, with a src on the app's own origin`;
  }
  return null;
}

/** A url() target on another origin: a scheme (https:, data:) or a protocol-relative //host. */
function foreignTarget(value) {
  for (const match of value.matchAll(/url\(\s*(['"]?)(.*?)\1\s*\)/gi)) {
    const target = match[2].trim();
    if (/^[a-z][a-z0-9+.-]*:/i.test(target) || target.startsWith("//")) return target;
  }
  return null;
}

function fontFaceProblems(node, at) {
  const problems = [];
  for (const child of node.nodes ?? []) {
    if (child.type === "comment") continue;
    if (child.type !== "decl") {
      problems.push(`${at(child)}: @font-face holds descriptors only; nest nothing inside it.`);
      continue;
    }
    const prop = child.prop.toLowerCase();
    if (!FONT_DESCRIPTORS.has(prop)) {
      problems.push(`${at(child)}: ${child.prop} is not a @font-face descriptor; a face takes font-family, src, font-weight, font-style, font-display and the like.`);
      continue;
    }
    const foreign = prop === "src" ? foreignTarget(child.value) : null;
    if (foreign) {
      problems.push(
        `${at(child)}: ${foreign} is not on the app's own origin, and the app's policy admits fonts ` +
        `from its own origin only (font-src 'self'): put the file in frontend/public/fonts/ and name ` +
        `it as url("/fonts/<file>").`,
      );
    }
  }
  return problems;
}

function inspectContainer(container, at, problems, inPreference) {
  for (const node of container.nodes ?? []) {
    if (node.type === "comment") continue;
    if (node.type === "atrule" && node.name.toLowerCase() === "media" && node.nodes) {
      inspectContainer(node, at, problems, inPreference || /prefers-color-scheme/i.test(node.params));
      continue;
    }
    if (node.type === "atrule" && node.name.toLowerCase() === "font-face") {
      problems.push(...fontFaceProblems(node, at));
      continue;
    }
    if (node.type === "atrule") {
      problems.push(
        `${at(node)}: @${node.name} is refused here; this sheet holds tokens, @font-face and @media ` +
        `groups of tokens only. For anything else, ${ELSEWHERE}.`,
      );
      continue;
    }
    if (node.type !== "rule") {
      problems.push(`${at(node)}: a declaration belongs inside :root or a palette's [data-theme] rule.`);
      continue;
    }
    const refused = node.selectors.map((part) => selectorProblem(part.trim(), inPreference)).filter(Boolean);
    if (refused.length) {
      for (const problem of refused) problems.push(`${at(node)}: ${problem}.`);
      continue;
    }
    for (const child of node.nodes ?? []) {
      if (child.type === "comment") continue;
      if (child.type !== "decl") {
        problems.push(`${at(child)}: a token rule holds declarations only; nest no rule or at-rule inside it.`);
        continue;
      }
      const problem = tokenProblem(child);
      if (problem) problems.push(`${at(child)}: ${problem}.`);
    }
  }
}

/**
 * What is wrong with one of the bootstrap's own sheets, as messages that each name their line
 * and the remedy. A sheet that is not there is the bundler's to refuse, which it does, so it is
 * not a finding here: the lint reads what there is.
 */
export function inspectBootstrapSheet(file) {
  const problems = [];
  const name = path.basename(file);
  let text;
  try {
    text = fs.readFileSync(file, "utf8");
  } catch {
    return problems;
  }
  let root;
  try {
    root = postcss.parse(text, { from: file });
  } catch (error) {
    problems.push(`${name}:${error.line ?? 1}: ${error.reason ?? "the stylesheet does not parse"}; fix the CSS on that line.`);
    return problems;
  }
  inspectContainer(root, (node) => `${name}:${node.source.start.line}`, problems, false);
  return problems;
}
