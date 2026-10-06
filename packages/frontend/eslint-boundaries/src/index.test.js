import fs from "node:fs";
import path from "node:path";

import { ESLint } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import terpBoundaries, { catalogRuleId } from "./index.js";

// The frontend analog of the arch harness's meta-tests: prove each boundary rule actually fires on
// a violating fixture (and stays quiet on clean, out-of-module code), so "enforced" is real.
// File paths are resolved under the cwd so ESLint's `files` globs match (the parser then applies).

const LINT_ROOT = path.resolve("node_modules/.cache/terp-index-tests");
fs.rmSync(LINT_ROOT, { recursive: true, force: true });
fs.mkdirSync(LINT_ROOT, { recursive: true });
fs.writeFileSync(
  path.join(LINT_ROOT, "i18n.json"),
  JSON.stringify({ sourceLocale: "en", locales: { en: {} } }),
);
const MODULE_FILE = path.join(LINT_ROOT, "src/modules/widgets/Widget.tsx");
const BOOTSTRAP_FILE = path.join(LINT_ROOT, "src/main.tsx");
const HELPER_FILE = path.join(LINT_ROOT, "src/diagram/Canvas.tsx");

afterAll(() => fs.rmSync(LINT_ROOT, { recursive: true, force: true }));

async function lint(code, filePath = MODULE_FILE) {
  const eslint = new ESLint({ cwd: LINT_ROOT, overrideConfigFile: true, overrideConfig: terpBoundaries });
  const [result] = await eslint.lintText(code, { filePath });
  return result.messages.map((message) => message.ruleId);
}

async function lintMessages(code, filePath = MODULE_FILE) {
  const eslint = new ESLint({ cwd: LINT_ROOT, overrideConfigFile: true, overrideConfig: terpBoundaries });
  const [result] = await eslint.lintText(code, { filePath });
  return result.messages.map((message) => message.message);
}

describe("terpBoundaries", () => {
  it("passes clean module code (react-core components + generated client)", async () => {
    const code = [
      'import { Button, Select, Textarea, Trans, useTerpClient } from "@terpjs/react-core";',
      "export function Widget() {",
      "  const client = useTerpClient();",
      "  void client;",
      '  return <><Button><Trans id="widget.ok" message="OK" /></Button><Select /><Textarea /></>;',
      "}",
    ].join("\n");
    expect(await lint(code)).toEqual([]);
  });

  it("flags an import of a sibling module", async () => {
    const code = 'import { x } from "../other/thing";\nexport const W = () => null;';
    expect(await lint(code)).toContain("terp/no-cross-module-imports");
  });

  it("flags static JSX copy, UI attributes, and UI-bearing object properties", async () => {
    expect(await lint("export const W = () => <Text>Save changes</Text>;"))
      .toContain("terp/no-untranslated-ui");
    expect(await lint('export const W = () => <Page title="Widgets" />;'))
      .toContain("terp/no-untranslated-ui");
    expect(await lint('export const columns = [{ header: "Created at" }];'))
      .toContain("terp/no-untranslated-ui");
  });

  it("accepts descriptors and Trans as authored localization seams", async () => {
    const code = [
      'import { Page, Trans } from "@terpjs/react-core";',
      'const title = { id: "widgets.title", message: "Widgets" };',
      'export const W = () => <Page title={title}><Trans id="widgets.empty" message="Nothing here yet." /></Page>;',
    ].join("\n");
    expect(await lint(code)).toEqual([]);
  });

  it("flags a dynamic import() of a sibling module (no spelling escape)", async () => {
    const code = 'export const load = () => import("../other/thing");';
    expect(await lint(code)).toContain("terp/no-cross-module-imports");
  });

  it("flags a raw <button> (use the token-styled component)", async () => {
    expect(await lint("export const W = () => <button>x</button>;")).toContain("no-restricted-syntax");
  });

  it("flags raw form controls that have react-core primitives", async () => {
    expect(await lint("export const W = () => <select />;")).toContain("no-restricted-syntax");
    expect(await lint("export const W = () => <textarea />;")).toContain("no-restricted-syntax");
  });

  it("flags raw layout-bearing elements that have react-core components", async () => {
    expect(await lint("export const W = () => <table />;")).toContain("no-restricted-syntax");
    expect(await lint("export const W = () => <dialog />;")).toContain("no-restricted-syntax");
    expect(await lint("export const W = () => <form />;")).toContain("no-restricted-syntax");
  });

  it("flags an in-app anchor (router Link, not a full-reload <a>)", async () => {
    expect(await lint('export const W = () => <a href="/notes">go</a>;')).toContain(
      "no-restricted-syntax",
    );
    expect(await lint('export const W = () => <a href={"/notes"}>go</a>;')).toContain(
      "no-restricted-syntax",
    );
    expect(await lint("export const W = () => <a href={`/notes`}>go</a>;")).toContain(
      "no-restricted-syntax",
    );
  });

  it("allows an external anchor", async () => {
    expect(await lint('export const W = ({ label }) => <a href="https://example.com">{label}</a>;')).toEqual([]);
  });

  it("flags className (no side channel into hand-authored CSS)", async () => {
    expect(await lint('export const W = () => <div className="x">y</div>;')).toContain(
      "no-restricted-syntax",
    );
  });

  it("flags a module-authored stylesheet import (theming flows from the tokens)", async () => {
    const code = 'import "./widget.css";\nexport const W = () => null;';
    expect(await lint(code)).toContain("no-restricted-imports");
    expect(await lint('import "./widget.css?inline";\nexport const W = () => null;')).toContain(
      "no-restricted-imports",
    );
    expect(await lint('import "./widget.less";\nexport const W = () => null;')).toContain(
      "no-restricted-imports",
    );
  });

  it("flags a hardcoded colour (design tokens only)", async () => {
    expect(await lint('export const s = { color: "#ff0000" };')).toContain("no-restricted-syntax");
  });

  it("flags an inline style attribute (layout via react-core, styling via tokens)", async () => {
    expect(await lint("export const W = () => <div style={{ margin: 0 }}>x</div>;")).toContain(
      "no-restricted-syntax",
    );
  });

  it("flags raw fetch (generated client only)", async () => {
    expect(await lint('export const load = () => fetch("/api/x");')).toContain("no-restricted-globals");
    expect(await lint('export const load = () => window.fetch("/api/x");')).toContain(
      "no-restricted-syntax",
    );
    expect(await lint('export const load = () => globalThis.fetch("/api/x");')).toContain(
      "no-restricted-syntax",
    );
    expect(await lint('export const load = () => window["fetch"]("/api/x");')).toContain(
      "no-restricted-syntax",
    );
    expect(await lint("export const load = () => new XMLHttpRequest();")).toContain(
      "no-restricted-syntax",
    );
    expect(await lint('export const load = () => new globalThis["XMLHttpRequest"]();')).toContain(
      "no-restricted-syntax",
    );
  });

  it("flags raw navigator.clipboard (the seam feature-detects; the API does not)", async () => {
    // Every spelling reaches the same undefined on an http origin. The direct call is
    // the one that gets written; the others are what it becomes when someone "tidies"
    // it, and a rule that missed them would push the defect around rather than out.
    expect(await lint('export const c = () => navigator.clipboard.writeText("x");')).toContain(
      "no-restricted-syntax",
    );
    expect(await lint("export const c = () => navigator.clipboard.readText();")).toContain(
      "no-restricted-syntax",
    );
    expect(await lint('export const c = () => navigator["clipboard"].writeText("x");')).toContain(
      "no-restricted-syntax",
    );
    expect(
      await lint('export const c = () => window.navigator.clipboard.writeText("x");'),
    ).toContain("no-restricted-syntax");
    expect(
      await lint('export const c = () => globalThis["navigator"].clipboard.writeText("x");'),
    ).toContain("no-restricted-syntax");
    // Bound to a name rather than called: the throw already happened on the lookup.
    expect(await lint("export const c = navigator.clipboard;")).toContain(
      "no-restricted-syntax",
    );
    expect(await lint("export const { clipboard } = navigator;")).toContain(
      "no-restricted-syntax",
    );
  });

  it("accepts the react-core clipboard seam", async () => {
    // The other half of the rule: it must be satisfiable. A rule whose only compliant
    // program is one that does not copy anything would be obeyed by dropping the
    // feature -- so this asserts the sanctioned import is clean, not merely unflagged
    // by the clipboard selector.
    expect(
      await lint(
        'import { useCopyToClipboard } from "@terpjs/react-core";\n' +
          "export const useCopy = () => useCopyToClipboard();",
      ),
    ).toEqual([]);
    // A property named `clipboard` on something that is not `navigator` is not this
    // defect, and flagging it would make the rule a word filter.
    expect(await lint("export const pick = (o) => o.clipboard;")).toEqual([]);
  });

  it("refuses crypto.randomUUID in every spelling that binds the same undefined", async () => {
    // Secure-context-only, declared unconditionally by lib.dom: on an http origin each of
    // these is a synchronous TypeError that type-checks cleanly and never fires on
    // localhost, so neither tsc nor CI ever sees it.
    expect(await lint("export const id = () => crypto.randomUUID();")).toContain(
      "no-restricted-syntax",
    );
    expect(await lint('export const id = () => crypto["randomUUID"]();')).toContain(
      "no-restricted-syntax",
    );
    expect(await lint("export const id = () => window.crypto.randomUUID();")).toContain(
      "no-restricted-syntax",
    );
    expect(await lint("export const id = () => globalThis.crypto.randomUUID();")).toContain(
      "no-restricted-syntax",
    );
    expect(await lint("export const id = () => self.crypto.randomUUID();")).toContain(
      "no-restricted-syntax",
    );
    expect(
      await lint('export const id = () => globalThis["crypto"].randomUUID();'),
    ).toContain("no-restricted-syntax");
    // Bound rather than called: the reference is already the broken one.
    expect(await lint("export const gen = crypto.randomUUID;")).toContain(
      "no-restricted-syntax",
    );
    expect(await lint("export const { randomUUID } = crypto;")).toContain(
      "no-restricted-syntax",
    );
  });

  it("accepts the react-core uuid seam, and the API that is not gated", async () => {
    expect(
      await lint(
        'import { randomUuid } from "@terpjs/react-core";\nexport const id = () => randomUuid();',
      ),
    ).toEqual([]);
    // getRandomValues is NOT secure-context-gated, so it is not this defect and the seam
    // itself is built on it. Flagging it would make the rule a word filter on "crypto".
    expect(
      await lint("export const bytes = () => crypto.getRandomValues(new Uint8Array(16));"),
    ).toEqual([]);
    // And a `randomUUID` on something that is not `crypto` is somebody else's function.
    expect(await lint("export const id = (lib) => lib.randomUUID();")).toEqual([]);
  });

  it("honours the uuid rule's declared escape hatch, and only its own name", async () => {
    const call = "export const id = () => crypto.randomUUID();";
    expect(
      await lint(`// terp-allow-no-raw-random-uuid: https-only admin origin\n${call}`),
    ).toEqual([]);
    const wrong = await lint(`// terp-allow-no-random-uuid: typo\n${call}`);
    expect(wrong).toContain("no-restricted-syntax");
  });

  it("honours the clipboard rule's declared escape hatch, and only its own name", async () => {
    // The catalog entry declares `// terp-allow-no-raw-clipboard: <reason>`, and a
    // declared opt-out that does not actually suppress is a false promise in the
    // Standard. Asserted here rather than trusted: the marker resolves through the
    // catalog rule name, not the ESLint rule id, and several catalog rules share
    // `no-restricted-syntax` — so this could have silently waived a sibling or nothing.
    const call = 'export const c = () => navigator.clipboard.writeText("x");';
    expect(await lint(`// terp-allow-no-raw-clipboard: legacy embed target\n${call}`)).toEqual(
      [],
    );
    // A near-miss name must not waive it, and is itself reported as an unjustified
    // marker — otherwise a typo would read as compliance.
    const wrong = await lint(`// terp-allow-no-clipboard: typo\n${call}`);
    expect(wrong).toContain("no-restricted-syntax");
    expect(wrong).toContain("terp/escape-hatch");
  });

  it("flags raw browser streaming/beacon request primitives (generated client only)", async () => {
    expect(await lint('export const open = () => new WebSocket("wss://example.com");')).toContain(
      "no-restricted-globals",
    );
    expect(await lint('export const open = () => new window.EventSource("/events");')).toContain(
      "no-restricted-syntax",
    );
    expect(await lint('export const send = () => navigator.sendBeacon("/api/x", "x");')).toContain(
      "no-restricted-syntax",
    );
    expect(
      await lint('export const send = () => window.navigator.sendBeacon("/api/x", "x");'),
    ).toContain("no-restricted-syntax");
    expect(
      await lint('export const send = () => globalThis["navigator"]["sendBeacon"]("/api/x", "x");'),
    ).toContain("no-restricted-syntax");
  });

  it("flags target=_blank without rel=noopener", async () => {
    expect(
      await lint('export const W = () => <a href="https://example.com" target="_blank">docs</a>;'),
    ).toContain("terp/no-unsafe-target-blank");
    expect(
      await lint(
        'export const W = () => <a href="https://example.com" target={"_blank"} rel="noreferrer">docs</a>;',
      ),
    ).toContain("terp/no-unsafe-target-blank");
    expect(
      await lint(
        'export const W = ({ label }) => <a href="https://example.com" target={`_blank`} rel="noopener noreferrer">{label}</a>;',
      ),
    ).toEqual([]);
  });

  it("flags static javascript href/src values without rejecting dynamic URLs", async () => {
    expect(await lint('export const W = () => <a href=" javascript:alert(1)">bad</a>;')).toContain(
      "terp/no-unsafe-href",
    );
    expect(await lint('export const W = () => <img src={"JaVaScRiPt:alert(1)"} />;')).toContain(
      "terp/no-unsafe-href",
    );
    expect(await lint('export const W = () => <a href={`javascript:${danger}`}>bad</a>;')).toContain(
      "terp/no-unsafe-href",
    );
    expect(await lint('export const W = ({ href, label }) => <a href={href}>{label}</a>;')).toEqual([]);
  });

  it("flags DOM HTML injection sinks", async () => {
    expect(await lint('export const write = (el, html) => { el.innerHTML = html; };')).toContain(
      "terp/no-dom-html-injection",
    );
    expect(
      await lint('export const write = (el, html) => el.insertAdjacentHTML("beforeend", html);'),
    ).toContain("terp/no-dom-html-injection");
    expect(await lint('export const write = (html) => document.write(html);')).toContain(
      "terp/no-dom-html-injection",
    );
    expect(await lint('export const W = ({ html }) => <iframe srcDoc={html} />;')).toContain(
      "terp/no-dom-html-injection",
    );
  });

  it("flags eval and Function constructors", async () => {
    expect(await lint('export const run = (code) => eval(code);')).toContain("terp/no-eval");
    expect(await lint('export const run = (code) => new Function(code);')).toContain("terp/no-eval");
    expect(await lint('export const run = (code) => window.eval(code);')).toContain("terp/no-eval");
  });

  it("flags a deep import into a package's internals", async () => {
    const code = 'import x from "@terpjs/react-core/src/secret";\nexport const W = () => null;';
    expect(await lint(code)).toContain("no-restricted-imports");
  });

  it("holds app source outside modules/ to the same boundary (ADR 0175)", async () => {
    // The hole this closes: a component beside the modules, imported by one, carried a
    // stylesheet, style, className, a raw element and the security sinks with no finding.
    const code = [
      'import "some-diagram-lib/dist/style.css";',
      'import "./canvas.css";',
      "export const load = () => fetch(\"/api/nodes\");",
      "export const run = (code) => eval(code);",
      "export const paint = (el, html) => { el.innerHTML = html; };",
      "export const Canvas = ({ html }) => (",
      '  <div style={{ height: 600 }} className="canvas">',
      "    <button>x</button>",
      "    <div dangerouslySetInnerHTML={{ __html: html }} />",
      "  </div>",
      ");",
    ].join("\n");
    const messages = await lintMessages(code, HELPER_FILE);
    const rules = await lint(code, HELPER_FILE);
    expect(rules.filter((rule) => rule === "no-restricted-imports")).toHaveLength(2);
    expect(rules).toContain("no-restricted-globals");
    expect(rules).toContain("terp/no-eval");
    expect(rules).toContain("terp/no-dom-html-injection");
    expect(messages.some((message) => message.startsWith("dangerouslySetInnerHTML"))).toBe(true);
    expect(messages).toContain(
      "The style attribute is forbidden in app source; layout comes from the react-core " +
        "components (Stack, Page, ...) and styling from the design tokens.",
    );
    expect(messages.some((message) => message.startsWith("The className attribute"))).toBe(true);
    expect(messages.some((message) => message.includes("Button"))).toBe(true);
  });

  it("holds every script extension under src, not only .ts and .tsx", async () => {
    // Renaming a helper to .mts or .jsx must not take it out of the boundary.
    const script = 'import "./canvas.css";\nexport const run = (code) => eval(code);';
    for (const extension of ["mts", "cts", "js", "mjs", "cjs"]) {
      const file = path.join(LINT_ROOT, `src/diagram/helper.${extension}`);
      const rules = await lint(script, file);
      expect(rules, extension).toContain("no-restricted-imports");
      expect(rules, extension).toContain("terp/no-eval");
    }
    for (const extension of ["jsx", "tsx"]) {
      const file = path.join(LINT_ROOT, `src/diagram/Canvas.${extension}`);
      const rules = await lint(`${script}\nexport const W = () => <button>x</button>;`, file);
      expect(rules, extension).toContain("no-restricted-imports");
      expect(rules, extension).toContain("terp/no-eval");
      expect(rules, extension).toContain("no-restricted-syntax");
    }
  });

  it("refuses code outside every module importing into one (no laundering through shared code)", async () => {
    // The route the module-to-module check never sees: a shared file re-exports a module's
    // internals, and a sibling module imports the shared file instead of the module.
    const bridge = path.join(LINT_ROOT, "src/shared/bridge.ts");
    for (const code of [
      'export { secret } from "../modules/billing/internal/secret";',
      'export * from "../modules/billing/internal/secret";',
      'import { secret } from "../modules/billing/internal/secret";\nexport const s = secret;',
      'export const load = () => import("../modules/billing/internal/secret");',
    ]) {
      expect(await lint(code, bridge), code).toEqual(["terp/no-cross-module-imports"]);
    }
    expect(
      await lintMessages('export { secret } from "../modules/billing/internal/secret";', bridge),
    ).toEqual([
      'Code outside every module must not import from module "billing"; modules depend on ' +
        "shared code, never the other way round. Move what both need out of the module (or " +
        "into the framework packages), or keep it inside the module.",
    ]);
    // A helper beside the modules is still shared code, whatever its folder is called.
    expect(await lint('import { W } from "./modules/widgets/Widget";\nexport const X = W;', HELPER_FILE))
      .toEqual(["terp/no-cross-module-imports"]);
  });

  it("lets a module import shared code beside the modules", async () => {
    const orders = path.join(LINT_ROOT, "src/modules/orders/Orders.tsx");
    const code = 'import { secret } from "../../shared/bridge";\nexport const s = secret;';
    expect(await lint(code, orders)).toEqual([]);
  });

  it("still refuses a module importing a sibling module", async () => {
    const orders = path.join(LINT_ROOT, "src/modules/orders/Orders.tsx");
    const code = 'import { secret } from "../billing/internal/secret";\nexport const s = secret;';
    expect(await lintMessages(code, orders)).toEqual([
      'App module "orders" must not import sibling module "billing"; modules stay independent ' +
        "(share through the framework packages, not each other).",
    ]);
  });

  it("leaves the bootstrap's module discovery alone (import.meta.glob is not an import)", async () => {
    const code = [
      'import { renderTerpApp } from "@terpjs/react-core";',
      'renderTerpApp({ modules: import.meta.glob("./modules/*/module.tsx", { eager: true }) });',
    ].join("\n");
    expect(await lint(code, BOOTSTRAP_FILE)).toEqual([]);
  });

  it("lets the bootstrap import exactly the token pipeline's stylesheets", async () => {
    const code = [
      'import "@terpjs/contract/tokens.css";',
      'import "./house-style.css";',
      'import "./theme.css";',
      "export {};",
    ].join("\n");
    expect(await lint(code, BOOTSTRAP_FILE)).toEqual([]);
  });

  it("refuses any other stylesheet in the bootstrap, a library's included", async () => {
    for (const source of ["some-diagram-lib/dist/style.css", "./app.css", "./theme.scss"]) {
      expect(await lint(`import "${source}";\nexport {};`, BOOTSTRAP_FILE)).toEqual([
        "no-restricted-imports",
      ]);
    }
  });

  it("allows the three by exact specifier, never by shape, query or letter case", async () => {
    // Each of these is one edit away from an allowed specifier. An allowance written as a
    // shape (`**/theme.css`), as a prefix, or matched case-insensitively would pass one.
    for (const source of [
      "./theme.css?inline",
      "./theme.css?raw",
      "./theme.css?url",
      "../src/theme.css",
      "./sub/theme.css",
      "@terpjs/contract/tokens.css?url",
      "some-lib/theme.css",
      "some-lib/house-style.css",
      "./THEME.css",
      "./theme.CSS",
      "./House-Style.css",
      "@TERPJS/contract/tokens.css",
    ]) {
      const messages = await lintMessages(`import "${source}";\nexport {};`, BOOTSTRAP_FILE);
      expect(messages, source).toHaveLength(1);
      expect(messages[0], source).toContain(
        "App-authored stylesheets are forbidden, a library's included",
      );
    }
  });

  it("gives the allowance to the bootstrap only, not to a file that imports the same sheet", async () => {
    const helper = path.join(LINT_ROOT, "src/diagram/x.tsx");
    expect(await lint('import "./theme.css";\nexport {};', helper)).toEqual([
      "no-restricted-imports",
    ]);
  });

  it("gives the allowance to the app's own src/main.tsx, not a nested one", async () => {
    // `**/src/main.tsx` alone matches a main.tsx a module nests under a src/ of its own.
    for (const nested of ["src/modules/w/src/main.tsx", "src/modules/src/main.tsx", "src/lib/src/main.tsx"]) {
      expect(
        await lint('import "./theme.css";\nexport {};', path.join(LINT_ROOT, nested)),
        nested,
      ).toEqual(["no-restricted-imports"]);
    }
  });

  it("keeps refusing deep imports in the bootstrap", async () => {
    // The bootstrap block replaces no-restricted-imports wholesale, so it must carry the
    // deep-import group as well as its own stylesheet allowance.
    const code = 'import "./theme.css";\nimport x from "@terpjs/react-core/src/x";\nexport { x };';
    expect(await lintMessages(code, BOOTSTRAP_FILE)).toEqual([
      expect.stringContaining(
        "Import from the package root (@terpjs/react-core, @terpjs/contract), not its internals.",
      ),
    ]);
  });

  it("refuses a stylesheet in any letter case outside the bootstrap", async () => {
    for (const source of ["./canvas.CSS", "./Canvas.Scss", "lib/STYLE.LESS?inline"]) {
      expect(await lint(`import "${source}";\nexport {};`, HELPER_FILE), source).toEqual([
        "no-restricted-imports",
      ]);
    }
  });

  it("refuses a stylesheet loaded through import() or import.meta.glob", async () => {
    // Not an import declaration, so no-restricted-imports never sees it; the bundler loads
    // the sheet all the same. Attributed to the same catalog rule as a static import.
    for (const filePath of [HELPER_FILE, MODULE_FILE, BOOTSTRAP_FILE]) {
      for (const code of [
        'export const load = () => import("lib/style.css");',
        'export const load = () => import("./theme.css");',
        'export const load = () => import("./canvas.SCSS?inline");',
        "export const load = (name) => import(`./themes/${name}.css`);",
        'export const sheets = import.meta.glob("/x/*.css", { eager: true });',
        'export const sheets = import.meta.glob("./styles/**/*.{css,scss}");',
        'export const sheets = import.meta.glob(["./a/*.ts", "./b/*.less"]);',
      ]) {
        const messages = await lintMessages(code, filePath);
        expect(messages, `${filePath}: ${code}`).toEqual([
          expect.stringContaining("is a stylesheet import like any other"),
        ]);
        const eslint = new ESLint({ cwd: LINT_ROOT, overrideConfigFile: true, overrideConfig: terpBoundaries });
        const [result] = await eslint.lintText(code, { filePath });
        expect(result.messages.map(catalogRuleId), code).toEqual(["frontend/no-style-imports"]);
      }
    }
  });

  it("leaves import() and import.meta.glob of anything but a stylesheet alone", async () => {
    for (const code of [
      'export const load = () => import("./Widget");',
      'export const load = (name) => import(`./widgets/${name}.tsx`);',
      'export const all = import.meta.glob("./modules/*/module.tsx", { eager: true });',
      'export const all = import.meta.glob(["./a/*.ts", "!**/*.css"]);',
      'export const all = import.meta.glob("./docs/*.md", { query: "?raw" });',
    ]) {
      expect(await lint(code, HELPER_FILE), code).toEqual([]);
    }
  });

  it("waives a dynamic stylesheet import with the same catalog marker as a static one", async () => {
    const code = [
      "// terp-allow-no-style-imports: print-only sheet loaded on demand",
      'export const load = () => import("./print.css");',
    ].join("\n");
    expect(await lint(code, HELPER_FILE)).toEqual([]);
  });

  it("holds the bootstrap to every other rule", async () => {
    const code = [
      'import "./theme.css";',
      "export const run = (code) => eval(code);",
      "export const W = () => <button>x</button>;",
    ].join("\n");
    const rules = await lint(code, BOOTSTRAP_FILE);
    expect(rules).toContain("terp/no-eval");
    expect(rules).toContain("no-restricted-syntax");
  });

  it("lints the template's own bootstrap clean", async () => {
    // The allowance is exactly as wide as the bootstrap a generated app starts from: a
    // stylesheet the template adds is refused here before an app ever meets it.
    const template = fs.readFileSync(
      path.resolve("../../../template/project/frontend/src/main.tsx.jinja"),
      "utf-8",
    );
    // Strip the Jinja tags and keep what they wrap, so every optional line is linted too;
    // a tag left behind, or a placeholder this does not fill, fails here rather than parsing
    // as something else.
    const rendered = template
      .replaceAll("{{ project_name }}", "Demo")
      .replace(/\{%-?[\s\S]*?-?%\}/g, "");
    expect(rendered).not.toContain("{{");
    expect(rendered).not.toContain("{%");
    expect(await lintMessages(rendered, BOOTSTRAP_FILE)).toEqual([]);
  });

  it("suppresses a violation with a justified terp-allow marker on the line above", async () => {
    const code = [
      'import { Trans } from "@terpjs/react-core";',
      "// terp-allow-token-styled-elements: native button needed for a browser extension host",
      'export const W = () => <button><Trans id="widget.action" message="Action" /></button>;',
    ].join("\n");
    expect(await lint(code)).toEqual([]);
  });

  it("suppresses a violation with a justified terp-allow marker on the same line", async () => {
    const code =
      "export const W = () => <textarea />; // terp-allow-token-styled-elements: measured host quirk";
    expect(await lint(code)).toEqual([]);
  });

  it("suppresses a custom terp rule with the reported rule id suffix", async () => {
    const code = [
      'import { Trans } from "@terpjs/react-core";',
      "// terp-allow-no-unsafe-target-blank: external vendor requires opener for a handshake",
      'export const W = () => <a href="https://example.com" target="_blank"><Trans id="widget.docs" message="Docs" /></a>;',
    ].join("\n");
    expect(await lint(code)).toEqual([]);
  });

  it("refuses the retired pre-0.6.0 core-id spelling", async () => {
    // The one-release transitional aliases (LEGACY_MARKER_ALIASES) are gone with the
    // 0.6.0 pin: a core-id spelling names no catalog rule, so it waives nothing and
    // is itself reported as an ungoverned marker.
    const code = [
      "// terp-allow-no-restricted-syntax: pre-0.6.0 spelling (migrate to the catalog rule)",
      "export const W = () => <button>x</button>;",
    ].join("\n");
    const rules = await lint(code);
    expect(rules).toContain("no-restricted-syntax"); // not suppressed
    expect(rules).toContain("terp/escape-hatch"); // the stale spelling is itself reported
  });

  it("reports a marker that names no governed rule instead of honouring it", async () => {
    const code = [
      "// terp-allow-made-up-rule: stale name",
      "export const W = () => <button>x</button>;",
    ].join("\n");
    const rules = await lint(code);
    expect(rules).toContain("no-restricted-syntax"); // not suppressed
    expect(rules).toContain("terp/escape-hatch"); // the unknown name is itself reported
  });

  it("ignores marker-shaped text inside a string or template literal", async () => {
    // Markers live in real comments only — a marker-shaped string neither
    // suppresses the next line nor its own line.
    const viaString = [
      'const doc = "// terp-allow-no-eval: not a comment";',
      "export const run = (code) => eval(code); export { doc };",
    ].join("\n");
    expect(await lint(viaString)).toContain("terp/no-eval");
    const viaTemplate = [
      "const doc = `// terp-allow-no-eval: not a comment`;",
      "export const run = (code) => eval(code); export { doc };",
    ].join("\n");
    expect(await lint(viaTemplate)).toContain("terp/no-eval");
  });

  it("one catalog marker covers every detection path of its rule (egress family)", async () => {
    // Bare fetch reports via no-restricted-globals; window.fetch via no-restricted-syntax.
    // Both are frontend/generated-client-only, so ONE marker name waives either path.
    const viaGlobals = [
      "// terp-allow-generated-client-only: sanctioned health probe",
      'export const ping = () => fetch("/healthz");',
    ].join("\n");
    expect(await lint(viaGlobals)).toEqual([]);
    const viaSyntax = [
      "// terp-allow-generated-client-only: sanctioned health probe",
      'export const ping = () => window.fetch("/healthz");',
    ].join("\n");
    expect(await lint(viaSyntax)).toEqual([]);
  });

  it("reports an unjustified terp-allow marker instead of honouring it", async () => {
    const code = [
      "// terp-allow-token-styled-elements",
      "export const W = () => <button>x</button>;",
    ].join("\n");
    const rules = await lint(code);
    expect(rules).toContain("no-restricted-syntax"); // not suppressed
    expect(rules).toContain("terp/escape-hatch"); // the bare marker is itself reported
  });

  it("does not let a marker for one rule suppress another rule", async () => {
    const code = [
      "// terp-allow-no-cross-module-imports: wrong rule name",
      "export const W = () => <button>x</button>;",
    ].join("\n");
    expect(await lint(code)).toContain("no-restricted-syntax");
  });

  it("does not let a sibling catalog rule's marker cross a shared core rule id", async () => {
    // token-styled-elements and no-inline-styling both report as no-restricted-syntax;
    // a marker for one must never waive the other.
    const code = [
      "// terp-allow-token-styled-elements: wrong sibling",
      'export const W = () => <div style={{ color: "red" }}>x</div>;',
    ].join("\n");
    expect(await lint(code)).toContain("no-restricted-syntax");
  });

  it("ignores inline eslint-disable directives (the budgeted marker is the only opt-out)", async () => {
    // Without noInlineConfig, a plain `eslint-disable` would skip the gate with zero budget
    // accounting — the exact drift ADR 0059 refuses. The directive must be inert.
    const code = [
      "// eslint-disable-next-line no-restricted-syntax",
      "export const W = () => <button>x</button>;",
    ].join("\n");
    expect(await lint(code)).toContain("no-restricted-syntax");
  });

  it("ignores a file-wide eslint-disable block comment", async () => {
    const code = ["/* eslint-disable */", "export const W = () => <button>x</button>;"].join("\n");
    expect(await lint(code)).toContain("no-restricted-syntax");
  });

  it("the dialog refusal says what to do instead of naming only ConfirmDialog", async () => {
    // "Use ConfirmDialog" is right for a confirmation and wrong advice for an edit form,
    // and an author who reads it for one concludes the rule cannot be obeyed. The reported
    // evidence was an app that built the editor in an expanded row instead and recorded
    // that as the better outcome — so the refusal carries that guidance, rather than the
    // framework shipping a general modal whose absence produced the better UI.
    const messages = await lintMessages("export const W = () => <dialog>x</dialog>;");
    const refusal = messages.find((message) => message.includes("<dialog>"));
    expect(refusal).toContain("ConfirmDialog");
    expect(refusal).toContain("routed page");
    expect(refusal).toContain("expanded row");
  });

  it("an element with no extra guidance keeps the plain one-line refusal", async () => {
    const messages = await lintMessages("export const W = () => <button>x</button>;");
    expect(messages).toContain("Use Button from @terpjs/react-core, not a raw <button>.");
  });
});
