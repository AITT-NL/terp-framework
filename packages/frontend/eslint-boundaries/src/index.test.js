import fs from "node:fs";
import path from "node:path";

import { ESLint } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import terpBoundaries from "./index.js";

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
const OUTSIDE_FILE = path.join(LINT_ROOT, "src/main.tsx");

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

  it("does not apply the module rules outside src/modules/", async () => {
    // A non-module file matches no config block, so the boundary rules never fire on it.
    const rules = await lint("export const W = () => <button>x</button>;", OUTSIDE_FILE);
    expect(rules).not.toContain("no-restricted-syntax");
    expect(rules).not.toContain("terp/no-cross-module-imports");
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
