/**
 * Token build: tokens.json (light, the framework-agnostic source of truth) +
 * tokens.dark.json (the dark colour overrides) -> src/tokens.css (design §7.1, item 2).
 *
 * The output is one stylesheet with three blocks:
 *   1. `:root`                       — the light theme (every token).
 *   2. `[data-theme="dark"]`         — the dark colour overrides (explicit choice).
 *   3. `@media (prefers-color-scheme: dark)` scoped to `:root:not([data-theme="light"])`
 *      — the OS preference applies automatically unless the app pinned a theme.
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

const light = declarations(await buildCss("tokens.json", "tokens.light.css"));
const dark = declarations(await buildCss("tokens.dark.json", "tokens.dark.css"));
rmSync(buildDir, { recursive: true, force: true });

const output = `/**
 * Do not edit directly, this file was auto-generated.
 */

:root {
  /* Opts native chrome (scrollbars, the <select> option popup, form controls,
     text-field carets) into the light palette so it never renders as foreign
     OS-light chrome. The dark blocks below flip it to dark. */
  color-scheme: light;
${light}
}

/* Dark theme: an explicit user/app choice via <html data-theme="dark">. */
[data-theme='dark'] {
  color-scheme: dark;
${dark}
}

/* Dark theme: the OS preference, unless the app pinned light explicitly. */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme='light']) {
    color-scheme: dark;
${dark.replace(/^ {2}/gm, "    ")}
  }
}
`;

writeFileSync(join(packageRoot, "src", "tokens.css"), output);
console.log("wrote src/tokens.css");

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
 * Everything here is derived, never restated: the token set comes from the two sources, the
 * category from the token's own path, `themeable` from whether the dark source overrides it,
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

const lightTokens = new Map(flatten(JSON.parse(readFileSync(join(packageRoot, "tokens.json"), "utf8"))));
const darkTokens = new Map(flatten(JSON.parse(readFileSync(join(packageRoot, "tokens.dark.json"), "utf8"))));
const pairs = JSON.parse(readFileSync(join(packageRoot, "token-pairs.json"), "utf8"));

const manifest = {
  $comment:
    "Generated by scripts/build-tokens.mjs from tokens.json, tokens.dark.json and " +
    "token-pairs.json. Do not edit directly; regenerate with `npm run -w @terpjs/contract " +
    "tokens`. CI fails on drift.",
  tokens: [...lightTokens.entries()].map(([name, token]) => ({
    name,
    category: token.category,
    light: token.value,
    // A token the dark source does not override is theme-invariant by design (space, radius,
    // font, motion, z-index): declared once and inherited. Saying so is what stops an editor
    // from offering a per-theme control that would have no effect.
    dark: darkTokens.get(name)?.value ?? null,
    themeable: darkTokens.has(name),
  })),
  textPairs: pairs.textPairs,
};

writeFileSync(
  join(packageRoot, "src", "tokens.manifest.json"),
  `${JSON.stringify(manifest, null, 2)}\n`,
);
console.log(`wrote src/tokens.manifest.json (${manifest.tokens.length} tokens, ${manifest.textPairs.length} pairs)`);
