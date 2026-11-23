import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { ESLint } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import { PAINT_ROLES } from "./cssModules.js";
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

  it("flags an arbitrary class name", async () => {
    expect(await lint('export const W = () => <div className="x">y</div>;')).toContain(
      "terp/no-inline-styling",
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

  it("checks class bindings and stylesheet scope independently", async () => {
    fs.mkdirSync(path.dirname(MODULE_FILE), { recursive: true });
    const sheet = path.join(path.dirname(MODULE_FILE), "Board.module.css");
    const prefix = 'import layout from "./Board.module.css"; ';
    fs.writeFileSync(sheet, ".board { display: grid }");
    expect(await lint(prefix + 'export const W = () => <div className={layout.board} />;')).toEqual([]);
    expect(await lint(prefix + 'export const W = (layout) => <div className={layout.board} />;')).toContain("terp/no-inline-styling");
    expect(await lint('import "./Board.module.css";')).toContain("terp/no-style-imports");
    expect(await lint('export * from "./Board.module.css";')).toContain("terp/no-style-imports");
    expect(await lint(prefix + 'export const W = () => <div className={layout.boarrd} />;')).toContain("terp/no-inline-styling");
    expect(await lint(prefix + 'export const W = () => <Button className={layout.board} />;')).toContain("terp/no-inline-styling");
    fs.writeFileSync(sheet, "@media (width < 40rem) { .board:hover, .lane { color: var(--color-fg-default); } }");
    expect(await lint(prefix + 'export const W = () => <div className={layout.lane} />;')).toEqual([]);
    for (const decl of ["color: white", "background: #fff", "background: currentColor", "border: 1px solid red", "color: var(--color-fg-default, white)",
      "--color-fg-default: white", "outline: none", "background-image: linear-gradient(red, red)", "padding: 1px !important"]) {
      fs.writeFileSync(sheet, `.board { ${decl} }`);
      const marked = "// terp-allow-no-style-imports: approved import edge\n" + prefix;
      expect(await lint(marked), decl).toEqual(["terp/no-style-imports"]);
    }
    // Each refusal names its cause and the remedy, not only that a line is unsupported.
    fs.writeFileSync(sheet, [".board { padding: 1px !important; }", ".lane { color: white; }", ".card { outline: none; }"].join("\n"));
    const lines = (await lintMessages(prefix + 'export const W = () => <div className={layout.board} />;'))
      .filter((text) => text.includes("Board.module.css:"));
    expect(lines).toEqual([
      expect.stringContaining("Board.module.css:1: drop !important from padding"),
      expect.stringContaining("Board.module.css:2: color takes an ink token, one of var(--color-fg-default), var(--color-fg-muted), var(--color-fg-subtle), with no fallback, or currentColor or inherit."),
      expect.stringContaining("Board.module.css:3: outline is not among the properties a CSS Module may set"),
    ]);
    // A border longhand, a keyword the property does not take, a string marker (copy no catalog
    // translates) and a class script cannot name: each refusal says what would be admitted.
    fs.writeFileSync(sheet, [".board { border-top-color: var(--color-border-default); }",
      ".lane { background: none; list-style-type: 'Pay now '; }", ".task-card { display: grid }"].join("\n"));
    expect((await lintMessages(prefix + 'export const W = () => <div className={layout.board} />;'))
      .filter((text) => text.includes("Board.module.css:"))).toEqual([
      expect.stringContaining("Board.module.css:1: border-top-color is not among the properties a CSS Module may set (layout, typography, and paint through color, background, background-color, border-color and the border shorthands); what it would style belongs to the react-core component that owns it, or to a token or prop asked of the framework."),
      expect.stringContaining("Board.module.css:2: background takes a surface token, one of var(--color-bg-canvas), var(--color-bg-surface), var(--color-bg-subtle), with no fallback, or transparent."),
      expect.stringContaining("Board.module.css:2: list-style-type takes a counter style keyword, such as disc or decimal; a string or symbols() puts copy on screen that no catalog translates"),
      expect.stringContaining("Board.module.css:3: .task-card cannot be named from script, since className reads a class as styles.<name>; call it .taskCard."),
    ]);
    // Paint takes its role: an ink as a surface, a surface or a brand fill as ink, and a border
    // shorthand outside the border tokens are each refused with the tokens the role takes.
    fs.writeFileSync(sheet, [".board { color: var(--color-brand-primary); }", ".lane { background: var(--color-fg-default); }",
      ".card { border: 1px solid var(--color-fg-accent); }", ".tag { color: var(--color-bg-canvas); }"].join("\n"));
    expect((await lintMessages(prefix + 'export const W = () => <div className={layout.board} />;'))
      .filter((text) => text.includes("Board.module.css:"))).toEqual([
      expect.stringContaining("Board.module.css:1: color takes an ink token"),
      expect.stringContaining("Board.module.css:2: background takes a surface token"),
      expect.stringContaining("Board.module.css:3: border takes none, or a width, a style and a border token, such as 1px solid var(--color-border-default)."),
      expect.stringContaining("Board.module.css:4: color takes an ink token"),
    ]);
    // A selector outside the grammar names the one it may use and the route for a state.
    fs.writeFileSync(sheet, ".board[aria-current] { display: grid }");
    expect(await lintMessages(prefix + 'export const W = () => <div className={layout.board} />;')).toEqual([
      expect.stringContaining("Board.module.css:1: .board[aria-current] is not a selector a CSS Module may use: select one of its own classes, optionally with :hover, :focus, :focus-visible, :focus-within, :active or :disabled. For a state the component knows, give the element another class: className={active ? styles.active : styles.lane}."),
    ]);
    // A missing sheet and one that does not parse are told apart, the second by its line and reason.
    fs.writeFileSync(sheet, ".board { display: grid");
    expect(await lintMessages(prefix + 'export const W = () => <div className={layout.board} />;')).toEqual([
      expect.stringContaining("Board.module.css:1: Unclosed block; fix the CSS on that line."),
    ]);
    expect(await lintMessages('import layout from "./Missing.module.css"; export const W = () => <div className={layout.board} />;')).toEqual([
      expect.stringContaining("Missing.module.css is not beside this component: create it there, or import the sibling module that is."),
    ]);
    fs.writeFileSync(sheet, ".board { display: grid }\n.active { display: grid }");
    expect(await lintMessages('import { board } from "./Board.module.css"; export const W = () => <div className={board} />;')).toContain(
      'Import the sibling CSS Module with one static default binding: import styles from "./Board.module.css".',
    );
    // A state chooses between two of the module's classes; any other expression is refused by name.
    expect(await lint(prefix + 'export const W = ({ on }) => <div className={on ? layout.active : layout.board} />;')).toEqual([]);
    for (const expression of ['on ? layout.active : "x"', "`${layout.board}`", "layout?.board"]) {
      expect(await lintMessages(prefix + `export const W = ({ on }) => <div className={${expression}} />;`), expression).toEqual([
        "className takes one class of a sibling CSS Module: className={styles.board}, after " +
          'import styles from "./Board.module.css". For a style that follows a state, choose between ' +
          "two of its classes: className={active ? styles.active : styles.board}.",
      ]);
    }
    expect(await lintMessages(prefix + 'export const W = () => <Button className={layout.board} />;')).toEqual([
      "A module class goes on a native element, never on <Button>: a framework component takes its props, " +
        "and keeps the styling and focus treatment it ships with.",
    ]);
    // The binding is read in a className and nowhere else: a spread, a call or a variable would
    // carry the class to a framework control past every check above.
    for (const code of [
      "export const W = () => <Button {...{ className: layout.board }} />;",
      "const props = { className: layout.board }; export const W = () => <Input {...props} />;",
      'import { createElement } from "react"; export const W = () => createElement(Button, { className: layout.board });',
      // The conditional's test chooses a class; it must not read the binding, or it could store it
      // or pass it on while the branches stay valid.
      "let stash; export const W = ({ on }) => <><div className={(stash = layout, on) ? layout.active : layout.board} /><Button {...{ className: stash.board }} /></>;",
      'import { createElement } from "react"; export const W = ({ on }) => <div className={createElement(Button, { className: layout.board }) && on ? layout.active : layout.board} />;',
    ]) {
      expect(await lintMessages(prefix + code), code).toContain(
        "layout is read only in a className on a native element: className={layout.board}, or " +
          "className={active ? layout.active : layout.board}. A module class passed on through a spread, " +
          "a call or a variable could reach a framework control.",
      );
    }
    // Ink and type are inherited: set on an element that holds anything but the app's own text,
    // they would restyle text the framework owns, so they go on the element that holds that text.
    fs.writeFileSync(sheet, ".lane { color: var(--color-fg-muted); text-transform: uppercase; }\n.board { display: grid }");
    expect(await lintMessages(prefix + "export const W = ({ t }) => <section className={layout.lane}><Card title={t} /></section>;")).toEqual([
      ".lane sets color, text-transform, which <Card> inside this element would inherit: ink and type go on an " +
        "element that holds only the app's own text (words, expressions, Trans, and native elements around them), " +
        "so keep the component, children or spread outside it.",
    ]);
    for (const [body, holder] of [
      ["{items.map((i) => <li key={i}><Badge>{i}</Badge></li>)}", "<Badge>"],
      ["{children}", "{children}"],
      ["{open && children}", "{children}"],
      ["{children ?? null}", "{children}"],
      ["{props?.children}", "{props?.children}"],
      ['{props["children"]}', '{props["children"]}'],
      ["{Children.map(children, (c) => <li>{c}</li>)}", "{children}"],
      ["{createElement(Card)}", "createElement(...)"],
      ["{React.cloneElement(item)}", "React.cloneElement(...)"],
    ]) {
      const code = `export const W = ({ items, children, open, props, item }) => <ul className={layout.lane}>${body}</ul>;`;
      expect(await lintMessages(prefix + code), body).toEqual([
        expect.stringContaining(`.lane sets color, text-transform, which ${holder} inside this element would inherit`),
      ]);
    }
    // A binding taken from children is children, and a component imported as Fragment or Trans
    // is still a component: only the real Trans and Fragment are read as text.
    for (const [code, holder] of [
      ["export const W = ({ children: body }) => <ul className={layout.lane}>{body}</ul>;", "{body}"],
      ["export const W = ({ children: body = null }) => <ul className={layout.lane}>{body}</ul>;", "{body}"],
      ["export const W = (props) => { const body = props.children; return <ul className={layout.lane}>{body}</ul>; };", "{body}"],
      ['import { Card as Fragment } from "@terpjs/react-core"; export const W = () => <ul className={layout.lane}><Fragment /></ul>;', "<Fragment>"],
      ['import { Card as Trans } from "@terpjs/react-core"; export const W = () => <ul className={layout.lane}><Trans /></ul>;', "<Trans>"],
    ]) {
      // A stand-in Trans also meets the localisation rule, which reads the name; only this one matters here.
      expect(await lintMessages(prefix + code), code).toContainEqual(
        expect.stringContaining(`.lane sets color, text-transform, which ${holder} inside this element would inherit`),
      );
    }
    expect(await lintMessages(prefix + "export const W = (props) => <section className={layout.lane} {...props} />;"))
      .toEqual([expect.stringContaining(".lane sets color, text-transform, which a spread of props inside this element would inherit")]);
    expect(await lintMessages(prefix + "export const W = ({ t }) => <section className={layout.lane} children={<Card title={t} />} />;"))
      .toEqual([expect.stringContaining(".lane sets color, text-transform, which a children attribute inside this element would inherit")]);
    // The app's own text, in each spelling the lint reads as text, takes ink and type.
    const imports = 'import { Fragment } from "react"; import * as React from "react"; import { Trans } from "@terpjs/react-core"; ';
    for (const body of ["{t}", '<Trans id="w.note" message="Nothing yet" />', "<Fragment key={t}><strong>{t}</strong></Fragment>",
      "<React.Fragment key={t}>{t}</React.Fragment>", "{items.map((i) => <li key={i}>{i}</li>)}", "{text(label)}"]) {
      expect(await lint(imports + prefix + `export const W = ({ t, items, text, label }) => <ul className={layout.lane}>${body}</ul>;`), body)
        .toEqual([]);
    }
    expect(await lint(prefix + "export const W = ({ t }) => <div className={layout.board}><p className={layout.lane}>{t}</p><Card /></div>;")).toEqual([]);
    // Each inherited type property is held the same way; a list marker and layout are not inherited text.
    for (const decl of ["font-size: 1rem", "font-weight: 600", "font-family: serif", "line-height: 1.5",
      "letter-spacing: 0.02em", "word-spacing: 1px", "white-space: nowrap", "text-align: center", "text-wrap: balance",
      "overflow-wrap: anywhere", "font-style: italic", "font: inherit"]) {
      fs.writeFileSync(sheet, `.lane { ${decl}; }`);
      expect(await lintMessages(prefix + "export const W = () => <div className={layout.lane}><Card /></div>;"), decl)
        .toEqual([expect.stringContaining(`.lane sets ${decl.split(":")[0]}, which <Card> inside this element would inherit`)]);
    }
    fs.writeFileSync(sheet, ".lane { list-style: none; display: grid; position: sticky; }");
    expect(await lint(prefix + "export const W = ({ t }) => <ul className={layout.lane}><li><Button>{t}</Button></li></ul>;")).toEqual([]);
    // position takes the values that keep an element in its own layout; fixed is the shell's.
    fs.writeFileSync(sheet, ".lane { position: fixed; }");
    expect(await lintMessages(prefix + "export const W = () => <div className={layout.lane} />;")).toEqual([
      "Board.module.css:1: position takes static, relative, absolute or sticky.",
    ]);
    // A declaration outside a rule, an at-rule outside the three groups, and a nested rule each
    // name what the stylesheet may hold instead.
    fs.writeFileSync(sheet, ["color: var(--color-fg-default);", "@layer app { .lane { display: grid } }", ".lane { .inner { display: grid } }"].join("\n"));
    expect(await lintMessages(prefix + "export const W = () => <div className={layout.lane} />;")).toEqual([
      "Board.module.css:1: a declaration belongs inside a rule for one of this module's classes.",
      "Board.module.css:2: @layer is refused; group rules only in @media, @container or @supports.",
      "Board.module.css:3: a rule holds declarations only; nest no rule or at-rule inside it.",
    ]);
    // A sibling module may carry dots in its name, as Vite allows.
    fs.writeFileSync(path.join(path.dirname(MODULE_FILE), "Board.lanes.module.css"), ".lane { display: grid }");
    expect(await lint('import lanes from "./Board.lanes.module.css"; export const W = () => <div className={lanes.lane} />;')).toEqual([]);
    // The allowance is the sibling spelling exactly: a query, another directory or another letter
    // case is a stylesheet import like any other, refused as a path, and its file is never read.
    for (const source of ["./Board.module.css?url", "./Board.module.css?inline", "./Board.module.css?raw",
      "./parts/Board.module.css", "../Board.module.css", "./Board.MODULE.css"]) {
      expect(await lint(`import layout from "${source}"; export const W = () => <div className={layout.board} />;`), source)
        .toContain("no-restricted-imports");
    }
    fs.writeFileSync(sheet, ".board { display: grid }\n.lane { display: grid }");
    expect(await lintMessages(prefix + 'export const W = () => <div className={layout.card} />;')).toEqual([
      expect.stringContaining("./Board.module.css defines no .card class: define it there, or use one it has (board, lane)."),
    ]);
    for (const css of ['@import "./global.css";', ".board, body { display: grid }",
      '.board { composes: external from "./global.css" }', ".board { & ~ * { display: none } }"]) {
      fs.writeFileSync(sheet, css);
      expect(await lint(prefix + 'export const W = () => <div className={layout.board} />;'), css)
        .toEqual(["terp/no-style-imports"]);
    }
  });

  it("admits only inks and surfaces whose every pairing the palette declares and measures", () => {
    // The claim the paint roles rest on: an app that sets any admitted ink over any admitted surface,
    // on one element or across two, forms a text pair the contract's contrast gate already holds to
    // AA in every theme. A token added to a role without its pairs fails here, not in a screen.
    const pairs = JSON.parse(
      fs.readFileSync(new URL("../../contract/token-pairs.json", import.meta.url), "utf8"),
    ).textPairs.map(({ fg, bg }) => `${fg} on ${bg}`);
    for (const ink of PAINT_ROLES.ink) {
      for (const surface of PAINT_ROLES.surface) {
        expect(pairs, `${ink} on ${surface}`).toContain(`${ink} on ${surface}`);
      }
    }
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

  it("refuses a datetime-local type however it is spelled inline", async () => {
    // The catalog says "an expression": a selector read only a string or a plain template as
    // the attribute's direct value, so each of these passed.
    for (const spelling of [
      '"datetime-local"',
      '{"DATETIME-LOCAL"}',
      "{`datetime-local`}",
      '{withTime ? "datetime-local" : "date"}',
      '{"datetime-local" as const}',
      '{"datetime-local" satisfies string}',
      '{kind ?? "datetime-local"}',
      '{withTime && "datetime-local"}',
      '{"datetime-" + "local"}',
      '{`datetime-${"local"}`}',
      '{`${withTime ? "datetime-" : "x"}local`}',
      '{(0, "datetime-local")}',
    ]) {
      const found = await lint(`export const W = ({ withTime, kind }) => <Input type=${spelling} />;`);
      expect(found, spelling).toContain("terp/timestamp-inputs-carry-their-offset");
    }
    for (const spelling of ['"date"', '{withTime ? "date" : "time"}', "{kind}", '{"datetime" + "-local-ish"}']) {
      const found = await lint(`export const W = ({ withTime, kind }) => <Input type=${spelling} />;`);
      expect(found, spelling).not.toContain("terp/timestamp-inputs-carry-their-offset");
    }
  });

  it("follows a concatenation's branches only so far", async () => {
    const branch = '(a ? "x" : "y")';
    const many = Array.from({ length: 8 }, () => branch).join(" + ");
    const found = await lint(`export const W = ({ a }) => <Input type={${many} + "datetime-local"} />;`);
    expect(found).not.toContain("terp/timestamp-inputs-carry-their-offset");
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
        "components (Stack, Page, ...) and styling from the design tokens. A layout a component " +
        'owns goes in its sibling CSS Module: import styles from "./Board.module.css" and ' +
        "className={styles.board} on a native element.",
    );
    expect(messages.some((message) => message.startsWith("className takes one class of a sibling CSS Module"))).toBe(true);
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
    // An app-root alias names the app's own modules as surely as a relative path does.
    expect(await lint('export { secret } from "@/modules/billing/internal/secret";', bridge)).toEqual([
      "terp/no-cross-module-imports",
    ]);
  });

  it("does not take a package's own modules folder for an app module", async () => {
    // A polyfill path has a `modules` segment and is a dependency, from shared code and from a
    // module alike: the rule is about the app's modules, not every path with the word in it.
    const bridge = path.join(LINT_ROOT, "src/shared/polyfills.ts");
    const orders = path.join(LINT_ROOT, "src/modules/orders/Orders.tsx");
    for (const file of [bridge, orders, BOOTSTRAP_FILE]) {
      expect(await lint('import "core-js/modules/es.promise";\nexport {};', file), file).not.toContain(
        "terp/no-cross-module-imports",
      );
    }
    // A module reaching a sibling through the alias is still refused.
    expect(
      await lint('import { secret } from "@/modules/billing/internal/secret";\nexport const s = secret;', orders),
    ).toContain("terp/no-cross-module-imports");
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
      // The refusal names both routes: the module form for a component, the three for the bootstrap.
      expect(messages[0], source).toContain('import styles from "./Board.module.css"');
      expect(messages[0], source).toContain("(@terpjs/contract/tokens.css, ./house-style.css, ./theme.css)");
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
    // Found from this file rather than the cwd: the package's own run starts in the package,
    // and the spec's reference-drift job runs this suite from the repository root.
    const template = fs.readFileSync(
      fileURLToPath(new URL("../../../../template/project/frontend/src/main.tsx.jinja", import.meta.url)),
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
