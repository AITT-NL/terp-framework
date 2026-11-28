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
 * group, which is how a palette follows the viewer's platform; `@font-face`, for a typeface the
 * app serves itself; and `@media` and `@supports` groups of those. A rule a token cannot express
 * goes in a stylesheet of the app's own, imported under the import opt-out, which leaves that file
 * unread: the escape is the one there already was, and it is never quiet.
 *
 * Every refusal names its line, its cause and the remedy for that cause, and the remedy depends on
 * who owns the file: the app edits `theme.css`, and nobody edits `house-style.css`, which the
 * styling tool overwrites each time the style is applied.
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

// A palette's name as a styling tool writes it: quoted, letters, digits and hyphens. Unquoted, an
// attribute value must be an identifier, which a name starting with a digit is not.
const PALETTE_SELECTOR = new RegExp(
  String.raw`^(?::root)?\[data-theme=(?:'[a-z0-9-]+'|"[a-z0-9-]+"|[a-z][a-z0-9-]*)\]$`,
);
const UNPINNED = ":root:not([data-theme])";
const GROUPS = new Set(["media", "supports"]);

/** The @font-face descriptors a typeface needs. Every other name is a property, not a descriptor. */
const FONT_DESCRIPTORS = new Set([
  "font-family", "src", "font-weight", "font-style", "font-stretch", "font-display",
  "unicode-range", "font-feature-settings", "font-variation-settings", "size-adjust",
  "ascent-override", "descent-override", "line-gap-override",
]);

/** The functions that make a stylesheet fetch something. No token holds a file. */
const FETCHING = /(?:^|[^a-z0-9_-])(url|src|image-set|-webkit-image-set|image|cross-fade)\s*\(/i;

const MARKED =
  "a stylesheet of the app's own, imported in src/main.tsx under a justified " +
  "// terp-allow-no-style-imports: <reason> marker";
const RESTYLE = `set the token or role that governs it (terp guide theming), or put the rule in ${MARKED}`;
const TOOL =
  "house-style.css is written by the organisation's styling tool and overwritten each time the " +
  "style is applied: fix the house style in that tool and apply it again, and never edit this " +
  "file. To depart from the house style in this app, declare the token in theme.css";

/**
 * A CSS value with its escapes resolved, so a check reads what the browser reads: `\75 rl(` is a
 * `url(` to a browser, and to a check that matched the text it was not.
 */
function unescapeCss(value) {
  return value.replace(/\\(?:([0-9a-f]{1,6})[ \t\n\r\f]?|([\s\S]))/gi, (_, hex, char) => {
    if (hex === undefined) return char;
    const code = Number.parseInt(hex, 16);
    return code === 0 || code > 0x10ffff ? "�" : String.fromCodePoint(code);
  });
}

// An app's own origin, as a stand-in: a target that resolves anywhere else leaves it.
const ORIGIN = "https://app.invalid";

/** Each url() target in a value that does not stay on the app's own origin, as written. */
function foreignTargets(value) {
  const foreign = [];
  for (const match of value.matchAll(/url\(\s*(?:"([^"]*)"|'([^']*)'|([^)]*?))\s*\)/gi)) {
    const target = (match[1] ?? match[2] ?? match[3] ?? "").trim();
    let resolved;
    try {
      resolved = new URL(target, `${ORIGIN}/fonts/`);
    } catch {
      foreign.push(target);
      continue;
    }
    if (resolved.origin !== ORIGIN) foreign.push(target);
  }
  return foreign;
}

/** The ways a sheet's lines are refused, each with its remedy for the file's owner. */
function refusals(owner) {
  const fix = (forApp) => (owner === "tool" ? TOOL : forApp);
  return {
    selector: (part) =>
      `${part} is not a selector this sheet may use: it declares tokens, under :root, ` +
      `[data-theme='<palette>'] or, inside a prefers-color-scheme group, ${UNPINNED}. ` +
      fix(`To restyle a component, ${RESTYLE}`),
    unpinned: () =>
      `${UNPINNED} declares the palette that follows the viewer's platform, so it belongs inside ` +
      `an @media (prefers-color-scheme: light|dark) group. ` +
      fix("Wrap the rule in that group"),
    property: (prop) =>
      `${prop} is not a token: this sheet declares custom properties (--name: value) only. ` +
      fix(`To change what ${prop} does, ${RESTYLE}`),
    important: (prop) =>
      `${prop} carries !important, and a token is declared once, where its palette is, and needs ` +
      `no priority. ` + fix("Drop the !important"),
    fetching: (prop, fn) =>
      `${prop} holds ${fn}(), and no token holds a file. ` +
      fix(
        "A brand mark is shell.brand in frontend/layout-contract.json, a typeface is an " +
        "@font-face whose src is on the app's own origin, and any other image is a rule for " +
        MARKED,
      ),
    nested: () =>
      `a token rule holds declarations only, and this one nests a rule or an at-rule. ` +
      fix(`Move it out: tokens go in the token rule itself, and anything else in ${MARKED}`),
    loose: () =>
      `a declaration outside any rule sets nothing. ` +
      fix("Put it inside :root or a palette's [data-theme] rule"),
    charset: () =>
      `@charset is refused here. ` + fix("Delete it: the sheet is read as UTF-8 without it"),
    atRule: (name) =>
      `@${name} is refused here; this sheet holds tokens, @font-face, and @media and @supports ` +
      `groups of those. ` + fix(`For anything else, use ${MARKED}`),
    faceNested: () =>
      `@font-face holds descriptors only, and this one nests a rule. ` +
      fix("Move it out of the @font-face"),
    faceDescriptor: (prop) =>
      `${prop} is not a @font-face descriptor; a face takes font-family, src, font-weight, ` +
      `font-style, font-display and the like. ` + fix(`Drop it, or move the rule to ${MARKED}`),
    faceForeign: (target) =>
      `${target} is not on the app's own origin, and the app's policy admits fonts from its own ` +
      `origin only (font-src 'self'). ` +
      fix('Put the file in frontend/public/fonts/ and name it as url("/fonts/<file>")'),
    faceFunction: (fn) =>
      `a @font-face src names its files with url() and local() only, and this one uses ${fn}(). ` +
      fix('Name the file as url("/fonts/<file>")'),
    parse: (reason) => `${reason}. ` + fix("Fix the CSS on that line"),
  };
}

function fontFaceProblems(node, sheet) {
  for (const child of node.nodes ?? []) {
    if (child.type === "comment") continue;
    if (child.type !== "decl") {
      sheet.report(child, sheet.says.faceNested());
      continue;
    }
    const prop = child.prop.toLowerCase();
    if (!FONT_DESCRIPTORS.has(prop)) {
      sheet.report(child, sheet.says.faceDescriptor(child.prop));
      continue;
    }
    if (prop !== "src") continue;
    const value = unescapeCss(child.value);
    for (const target of foreignTargets(value)) sheet.report(child, sheet.says.faceForeign(target));
    for (const match of value.matchAll(/([a-z-]+)\s*\(/gi)) {
      const fn = match[1].toLowerCase();
      if (!["url", "local", "format", "tech"].includes(fn)) sheet.report(child, sheet.says.faceFunction(fn));
    }
  }
}

function tokenProblems(rule, sheet) {
  for (const child of rule.nodes ?? []) {
    if (child.type === "comment") continue;
    if (child.type !== "decl") {
      sheet.report(child, sheet.says.nested());
      continue;
    }
    if (!child.prop.startsWith("--")) {
      sheet.report(child, sheet.says.property(child.prop));
      continue;
    }
    if (child.important) {
      sheet.report(child, sheet.says.important(child.prop));
      continue;
    }
    const fetching = FETCHING.exec(unescapeCss(child.value));
    if (fetching) sheet.report(child, sheet.says.fetching(child.prop, fetching[1].toLowerCase()));
  }
}

function inspectContainer(container, sheet, inPreference) {
  for (const node of container.nodes ?? []) {
    if (node.type === "comment") continue;
    if (node.type === "atrule") {
      const name = node.name.toLowerCase();
      if (GROUPS.has(name) && node.nodes) {
        inspectContainer(node, sheet, inPreference || (name === "media" && /prefers-color-scheme/i.test(node.params)));
      } else if (name === "font-face") {
        fontFaceProblems(node, sheet);
      } else if (name === "charset") {
        sheet.report(node, sheet.says.charset());
      } else {
        sheet.report(node, sheet.says.atRule(node.name));
      }
      continue;
    }
    if (node.type !== "rule") {
      sheet.report(node, sheet.says.loose());
      continue;
    }
    let refused = false;
    for (const part of node.selectors.map((selector) => selector.trim())) {
      if (part === ":root" || PALETTE_SELECTOR.test(part) || (part === UNPINNED && inPreference)) continue;
      sheet.report(node, part === UNPINNED ? sheet.says.unpinned() : sheet.says.selector(part));
      refused = true;
    }
    if (!refused) tokenProblems(node, sheet);
  }
}

/**
 * What is wrong with one of the bootstrap's own sheets, as messages that each name their line,
 * the cause and the remedy for whoever owns the file. A sheet that is not there is the bundler's
 * to refuse, which it does, so it is not a finding here: the lint reads what there is.
 */
export function inspectBootstrapSheet(file) {
  const name = path.basename(file);
  const problems = [];
  const sheet = {
    says: refusals(name === "house-style.css" ? "tool" : "app"),
    report: (node, message) => problems.push(`${name}:${node.source.start.line}: ${message}.`),
  };
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
    problems.push(`${name}:${error.line ?? 1}: ${sheet.says.parse(error.reason ?? "the stylesheet does not parse")}.`);
    return problems;
  }
  inspectContainer(root, sheet, false);
  return problems;
}
