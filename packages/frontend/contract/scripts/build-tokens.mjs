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
${light}
}

/* Dark theme: an explicit user/app choice via <html data-theme="dark">. */
[data-theme='dark'] {
${dark}
}

/* Dark theme: the OS preference, unless the app pinned light explicitly. */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme='light']) {
${dark.replace(/^ {2}/gm, "    ")}
  }
}
`;

writeFileSync(join(packageRoot, "src", "tokens.css"), output);
console.log("wrote src/tokens.css");
