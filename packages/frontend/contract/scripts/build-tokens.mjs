/**
 * Token build: the theme registry in `themes.json` plus one source per theme -> the compiled
 * stylesheet `src/tokens.css` and the published `src/tokens.manifest.json` (design §7.1, item 2).
 *
 * The output is one stylesheet with a block per theme:
 *   1. `:root`                       — the base theme, and the only block carrying geometry.
 *   2. `[data-theme='<name>']`       — one per non-base theme, colours only, an explicit choice.
 *   3. `@media (prefers-color-scheme: dark)` scoped to `:root:not([data-theme])`
 *      — the OS preference selects the registry's `systemDark` theme when nothing is pinned.
 *
 * The media selector matches only an *unpinned* root. It used to be
 * `:root:not([data-theme='light'])`, which was equivalent while `light` and `dark` were the
 * only themes and became a defect the moment a third existed: it matches
 * `[data-theme='contrast']`, outranks it on specificity (two compound parts against one), and
 * so laid the dark colours over a theme the app had explicitly pinned whenever the OS
 * preferred dark.
 *
 * Apps opt in/out per user via the `data-theme` attribute on <html> (react-core's
 * `ThemeProvider` manages it); with no attribute the OS preference wins. Regenerate with
 * `npm run -w @terpjs/contract tokens`; the frontend CI gate fails on drift.
 */
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import StyleDictionary from "style-dictionary";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const buildDir = mkdtempSync(join(tmpdir(), "terp-tokens-"));

const read = (name) => JSON.parse(readFileSync(join(packageRoot, name), "utf8"));

const registry = read("themes.json");
const themes = registry.themes;
const base = themes.find((theme) => theme.name === registry.base);
const overlays = themes.filter((theme) => theme.name !== registry.base);

// The generator is the first thing to read the registry, so it is the right place to refuse a
// registry that cannot produce a coherent sheet. Each of these would otherwise emit something
// that looks fine and behaves wrongly in the browser.
if (!base) throw new Error(`themes.json: base theme "${registry.base}" is not in the list`);
if (!themes.some((theme) => theme.name === registry.systemDark)) {
  throw new Error(`themes.json: systemDark "${registry.systemDark}" is not in the list`);
}
if (registry.systemDark === registry.base) {
  throw new Error("themes.json: systemDark must not be the base theme");
}
for (const theme of themes) {
  if (!/^[a-z][a-z0-9-]*$/.test(theme.name)) {
    throw new Error(`themes.json: "${theme.name}" is not usable as a data-theme value`);
  }
  if (theme.appearance !== "light" && theme.appearance !== "dark") {
    throw new Error(`themes.json: ${theme.name} appearance must be "light" or "dark"`);
  }
}

async function buildCss(sourceFile, outputFile) {
  const sd = new StyleDictionary({
    source: [join(packageRoot, sourceFile)],
    platforms: {
      css: {
        transformGroup: "css",
        buildPath: buildDir + "/",
        files: [
          {
            destination: outputFile,
            format: "css/variables",
            options: { outputReferences: true },
          },
        ],
      },
    },
  });
  await sd.buildAllPlatforms();
  return readFileSync(join(buildDir, outputFile), "utf8");
}

/** The bare `--x: y;` declaration lines of a generated `:root { ... }` block. */
function declarations(css) {
  return css
    .split("\n")
    .filter((line) => line.trimStart().startsWith("--"))
    .join("\n");
}

/** Every theme's compiled declaration lines, keyed by theme name, in registry order. */
const compiled = new Map();
for (const theme of themes) {
  compiled.set(
    theme.name,
    declarations(await buildCss(theme.source, `tokens.${theme.name}.css`)),
  );
}
rmSync(buildDir, { recursive: true, force: true });

const themeBlocks = overlays
  .map(
    (theme) => `
/* ${theme.label}: an explicit choice via <html data-theme="${theme.name}">.
   ${theme.description} */
[data-theme='${theme.name}'] {
  color-scheme: ${theme.appearance};
${compiled.get(theme.name)}
}
`,
  )
  .join("");

const systemDark = themes.find((theme) => theme.name === registry.systemDark);

const output = `/**
 * Do not edit directly, this file was auto-generated.
 */

:root {
  /* Opts native chrome (scrollbars, the <select> option popup, form controls,
     text-field carets) into the ${base.appearance} palette so it never renders as foreign
     OS-${base.appearance === "light" ? "dark" : "light"} chrome. Each theme block below sets its own. */
  color-scheme: ${base.appearance};
${compiled.get(base.name)}
}
${themeBlocks}
/* ${systemDark.label}: the OS preference, unless the app pinned any theme explicitly. */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme]) {
    color-scheme: ${systemDark.appearance};
${compiled.get(systemDark.name).replace(/^ {2}/gm, "    ")}
  }
}
`;

writeFileSync(join(packageRoot, "src", "tokens.css"), output);
console.log(`wrote src/tokens.css (${themes.length} themes)`);

/**
 * The manifest: the same tokens as machine-readable data, so a consumer does not have to
 * parse a stylesheet to find out what exists.
 *
 * Three consumers need it and none of them could get it before. A theme editor had to
 * hard-code its own token list, because `tokens.json` is Style-Dictionary-shaped and is not
 * exported from the package — only the compiled CSS is. An agent editing a theme by hand had
 * to infer names from whatever it found in `node_modules`, with no way to tell which tokens
 * are safe to theme or which must stay legible against which. And a human had no list at all.
 *
 * Everything here is derived, never restated: the token set comes from the theme sources, the
 * category from the token's own path, `themeable` from whether any non-base theme overrides it,
 * and the pairings from `token-pairs.json` — the same file the contrast gate reads. Nothing in
 * this file can disagree with the stylesheet beside it, because both are generated from the
 * same input in the same run.
 */
function cssName(path) {
  return `--${path.join("-")}`.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();
}

/**
 * Every leaf `{ value }` in a token tree, as `[cssName, { value, category }]`.
 *
 * The category is the source tree's own top-level family, not a re-split of the CSS name:
 * `zIndex.base` is in the `zIndex` family even though it flattens to `--z-index-base`, and
 * splitting the CSS name would have called that family `z`.
 */
function flatten(node, path = []) {
  if (node && typeof node === "object" && "value" in node) {
    return [[cssName(path), { value: String(node.value), category: path[0] }]];
  }
  if (!node || typeof node !== "object") return [];
  return Object.entries(node).flatMap(([key, child]) => flatten(child, [...path, key]));
}

const sources = new Map(
  themes.map((theme) => [theme.name, new Map(flatten(read(theme.source)))]),
);
const baseTokens = sources.get(base.name);
const pairs = read("token-pairs.json");

const manifest = {
  $comment:
    "Generated by scripts/build-tokens.mjs from themes.json, the per-theme token sources and " +
    "token-pairs.json. Do not edit directly; regenerate with `npm run -w @terpjs/contract " +
    "tokens`. CI fails on drift.",
  // The themes a `values` key can name, so a consumer can build a theme picker from this file
  // alone rather than hard-coding the list it happens to know about.
  base: registry.base,
  systemDark: registry.systemDark,
  themes: themes.map(({ name, label, appearance, description }) => ({
    name,
    label,
    appearance,
    description,
  })),
  tokens: [...baseTokens.entries()].map(([name, token]) => ({
    name,
    category: token.category,
    // Only the themes that actually declare the token, base always included. A theme absent
    // here inherits the base value — the cascade the sheet performs, stated as data. A token
    // present under the base alone is theme-invariant by design (space, radius, font, motion,
    // z-index): declared once and inherited. Saying so is what stops an editor from offering a
    // per-theme control that would have no effect.
    values: Object.fromEntries(
      themes
        .map((theme) => [theme.name, sources.get(theme.name).get(name)?.value])
        .filter(([, value]) => value !== undefined),
    ),
    themeable: overlays.some((theme) => sources.get(theme.name).has(name)),
  })),
  textPairs: pairs.textPairs,
};

writeFileSync(
  join(packageRoot, "src", "tokens.manifest.json"),
  `${JSON.stringify(manifest, null, 2)}\n`,
);
console.log(
  `wrote src/tokens.manifest.json (${manifest.tokens.length} tokens, ` +
    `${manifest.themes.length} themes, ${manifest.textPairs.length} pairs)`,
);
