import fs from "node:fs";
import path from "node:path";

import { ESLint } from "eslint";
import { afterEach, describe, expect, it } from "vitest";

import terpBoundaries from "./index.js";

const roots = [];

afterEach(() => {
  for (const root of roots.splice(0)) fs.rmSync(root, { recursive: true, force: true });
});

async function lintAt(root, source, relative = "src/modules/widgets/Widget.tsx") {
  const filePath = path.join(root, relative);
  const eslint = new ESLint({ cwd: root, overrideConfigFile: true, overrideConfig: terpBoundaries });
  const [result] = await eslint.lintText(source, { filePath });
  return result.messages;
}

async function lintWithCatalog(catalog, source, relative) {
  const root = fs.mkdtempSync(path.join(process.cwd(), ".terp-i18n-test-"));
  roots.push(root);
  fs.writeFileSync(path.join(root, "i18n.json"), JSON.stringify(catalog));
  return lintAt(root, source, relative);
}

async function lintWithoutCatalog(source, relative) {
  const root = fs.mkdtempSync(path.join(process.cwd(), ".terp-i18n-test-"));
  roots.push(root);
  return lintAt(root, source, relative);
}

function publicUiTextPropertyNames() {
  const rootsToScan = [
    path.resolve(import.meta.dirname, "../../react-core/src"),
    path.resolve(import.meta.dirname, "../../contract/src"),
  ];
  const names = new Set();
  const walk = (dir) => {
    for (const item of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, item.name);
      if (item.isDirectory()) {
        walk(full);
      } else if (/\.(?:ts|tsx)$/.test(item.name) && !/\.test\.tsx?$/.test(item.name)) {
        const sourceText = fs.readFileSync(full, "utf8");
        for (const match of sourceText.matchAll(/^\s*(\w+)\??:\s*UiText\b/gm)) {
          names.add(match[1]);
        }
      }
    }
  };
  rootsToScan.forEach(walk);
  return [...names].sort();
}

const source = 'export const title = { id: "widgets.title", message: "Widgets" };';

describe("locale catalog completeness", () => {
  it("fails closed when authored descriptors have no i18n declaration", async () => {
    const messages = await lintWithoutCatalog(source);
    expect(messages.map((message) => message.ruleId)).toContain("terp/locale-catalogs-complete");
    expect(messages.find((message) => message.ruleId === "terp/locale-catalogs-complete")?.message)
      .toContain("has no frontend/i18n.json declaration");
  });

  it("does not let a nested i18n.json shadow the authoritative app catalog", async () => {
    const root = fs.mkdtempSync(path.join(process.cwd(), ".terp-i18n-test-"));
    roots.push(root);
    const nested = path.join(root, "src", "modules", "widgets");
    fs.mkdirSync(nested, { recursive: true });
    fs.writeFileSync(
      path.join(nested, "i18n.json"),
      JSON.stringify({
        sourceLocale: "en",
        locales: { en: {}, nl: { messages: { "widgets.title": "Onderdelen" } } },
      }),
    );
    const messages = await lintAt(root, source);
    expect(messages.find((message) => message.ruleId === "terp/locale-catalogs-complete")?.message)
      .toContain("has no frontend/i18n.json declaration");
  });

  it("reports every target locale missing an authored id", async () => {
    const messages = await lintWithCatalog(
      { sourceLocale: "en", locales: { en: {}, nl: { messages: {} }, de: {} } },
      source,
    );
    expect(messages.map((message) => message.ruleId)).toContain("terp/locale-catalogs-complete");
    expect(messages[0].message).toContain("nl: missing");
    expect(messages[0].message).toContain("de: missing");
  });

  it("refuses copied source text unless the id is explicitly allowlisted", async () => {
    const messages = await lintWithCatalog(
      { sourceLocale: "en", locales: { en: {}, nl: { messages: { "widgets.title": "Widgets" } } } },
      source,
    );
    expect(messages[0].message).toContain("copied source");
  });

  it("accepts complete translations and documented identical proper nouns", async () => {
    const messages = await lintWithCatalog(
      {
        sourceLocale: "en",
        locales: {
          en: {},
          nl: { messages: { "widgets.title": "Widgets" }, allowIdentical: ["widgets.title"] },
        },
      },
      source,
    );
    expect(messages).toEqual([]);
  });

  it("refuses malformed declarations, descriptors, and stale allowlist entries", async () => {
    const malformed = await lintWithCatalog(
      { sourceLocale: "en", locales: { en: {}, nl: { messages: { stale: "" } } } },
      source,
    );
    expect(malformed[0].message).toContain("empty or invalid message entry");

    const blank = await lintWithCatalog(
      { sourceLocale: "en", locales: { en: {}, nl: {} } },
      'export const title = { id: "", message: "Widgets" };',
    );
    expect(blank.map((message) => message.ruleId)).toContain("terp/locale-catalogs-complete");
    expect(blank.find((message) => message.ruleId === "terp/locale-catalogs-complete")?.message)
      .toContain("non-empty static id and message");

    const dynamicDescriptor = await lintWithCatalog(
      { sourceLocale: "en", locales: { en: {}, nl: {} } },
      'export const title = { id: getId(), message: "Widgets" };',
    );
    expect(dynamicDescriptor
      .find((message) => message.ruleId === "terp/locale-catalogs-complete")?.message)
      .toContain("static non-empty id and message");

    const dynamicTrans = await lintWithCatalog(
      { sourceLocale: "en", locales: { en: {}, nl: {} } },
      'export const W = ({ id }) => <Trans id={id} message="Widgets" />;',
    );
    expect(dynamicTrans.find((message) => message.ruleId === "terp/locale-catalogs-complete")?.message)
      .toContain("requires static non-empty id and message");

    const staleAllowlist = await lintWithCatalog(
      {
        sourceLocale: "en",
        locales: {
          en: {},
          nl: { messages: { "widgets.title": "Onderdelen" }, allowIdentical: ["widgets.title"] },
        },
      },
      source,
    );
    expect(staleAllowlist[0].message).toContain("stale allowIdentical entry");
  });

  it("does not mistake dynamic business records for UiText descriptors", async () => {
    const messages = await lintWithCatalog(
      { sourceLocale: "en", locales: { en: {}, nl: {} } },
      "export const apiRecord = (id, message) => ({ id, message });",
    );
    expect(messages).toEqual([]);
  });

  it("honours the catalog-derived governed marker for an intentional exception", async () => {
    const messages = await lintWithoutCatalog(
      [
        "// terp-allow-locale-catalogs-complete: documented temporary catalog migration",
        'export const title = { id: "widgets.title", message: "Widgets" };',
      ].join("\n"),
    );
    expect(messages).toEqual([]);
  });
});

describe("untranslated UI coverage", () => {
  const declaration = { sourceLocale: "en", locales: { en: {}, nl: {} } };

  it("applies across src, not only module directories", async () => {
    const messages = await lintWithCatalog(
      declaration,
      'export const bootstrap = { label: "Single sign-on" };',
      "src/main.tsx",
    );
    expect(messages.map((message) => message.ruleId)).toContain("terp/no-untranslated-ui");
  });

  it.each([
    ['<ModuleNav ariaLabel="Modules" />', "ariaLabel"],
    ['<Tooltip content="More information" />', "content"],
    ['<Combobox loadingText="Loading options" />', "loadingText"],
    ['<Markdown source="Read the documentation" />', "source"],
    ['<DataView searchPlaceholder="Search widgets" />', "searchPlaceholder"],
    ['<div aria-description="Extra context" />', "aria-description"],
  ])("refuses literal UI copy in %s", async (jsx) => {
    const messages = await lintWithCatalog(declaration, `export const W = () => ${jsx};`);
    expect(messages.map((message) => message.ruleId)).toContain("terp/no-untranslated-ui");
  });

  it("covers UiText-bearing data properties beyond the original short list", async () => {
    const messages = await lintWithCatalog(
      declaration,
      'export const text = { actions: "Actions", "aria-label": "Open widget", cardView: "Card view", clearFilters: "Clear filters", clearSelection: "Clear selection", openRow: "Open details", pageOf: "Page of" };',
    );
    expect(messages.filter((message) => message.ruleId === "terp/no-untranslated-ui"))
      .toHaveLength(7);
  });

  it("tracks every public UiText property so new component copy cannot bypass the rule", async () => {
    const names = publicUiTextPropertyNames();
    expect(names.length).toBeGreaterThan(20);
    const sourceText = [
      "export const copy = {",
      ...names.map((name) => `  ${name}: "Translate ${name}",`),
      "};",
    ].join("\n");
    const messages = await lintWithCatalog(declaration, sourceText);
    const findingLines = new Set(
      messages
        .filter((message) => message.ruleId === "terp/no-untranslated-ui")
        .map((message) => message.line),
    );
    for (const [index, name] of names.entries()) {
      expect(findingLines.has(index + 2), `public UiText property "${name}" escaped`).toBe(true);
    }
  });

  it.each([
    '<>{"Save changes"}</>',
    '<Text>{ready ? "Ready" : "Waiting"}</Text>',
    '<Page title={ready && "Ready"} />',
    '<Text>{["First item", "Second item"]}</Text>',
  ])("refuses authored copy in nontrivial rendered expressions: %s", async (jsx) => {
    const messages = await lintWithCatalog(
      declaration,
      `export const W = ({ ready }) => ${jsx};`,
    );
    expect(messages.map((message) => message.ruleId)).toContain("terp/no-untranslated-ui");
  });

  it("refuses conditional object-property copy and unwraps TypeScript const assertions", async () => {
    const conditional = await lintWithCatalog(
      declaration,
      'export const action = { label: ready ? "Save changes" : "Cancel changes" };',
    );
    expect(conditional.map((message) => message.ruleId)).toContain("terp/no-untranslated-ui");

    const descriptor = await lintWithCatalog(
      {
        sourceLocale: "en",
        locales: { en: {}, nl: { messages: { "widgets.title": "Onderdelen" } } },
      },
      'export const title = { id: "widgets.title" as const, message: "Widgets" as const };',
    );
    expect(descriptor).toEqual([]);
  });

  it("keeps authored code samples exempt, including expression forms", async () => {
    const messages = await lintWithCatalog(
      declaration,
      'export const W = ({ ready }) => <Code>{ready ? "npm run build" : "npm run lint"}</Code>;',
    );
    expect(messages).toEqual([]);
  });

  it("refuses bare copy sent through the standard toast feedback channel", async () => {
    const messages = await lintWithCatalog(
      declaration,
      [
        'import { useToast as useFeedback } from "@terpjs/react-core";',
        "export function SaveButton({ ready }) {",
        "  const feedback = useFeedback();",
        "  const { warning: warn } = useFeedback();",
        '  feedback.success(ready ? "Saved" : "Still saving");',
        '  warn("Could not save");',
        "  return null;",
        "}",
      ].join("\n"),
    );
    expect(
      messages.filter((message) => message.ruleId === "terp/no-untranslated-ui"),
    ).toHaveLength(2);
  });

  it("accepts toast copy resolved from a catalog descriptor", async () => {
    const messages = await lintWithCatalog(
      {
        sourceLocale: "en",
        locales: { en: {}, nl: { messages: { "save.done": "Opgeslagen" } } },
      },
      [
        'import { useToast, useUiText } from "@terpjs/react-core";',
        "export function SaveButton({ error }) {",
        "  const toast = useToast();",
        "  const text = useUiText();",
        '  toast.success(text({ id: "save.done", message: "Saved" }));',
        "  toast.error(error.message);",
        "  return null;",
        "}",
      ].join("\n"),
    );
    expect(messages).toEqual([]);
  });
});
