import path from "node:path";

import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

import terpBoundaries from "./index.js";

// App code never writes react-core's `data-terp` markers (ADR 0160): the stylesheet selects on
// them and the runtime layout contract identifies a slot's children by them, so a hand-written
// one borrows a component's styling and passes that check without the component.

const RULE = "terp/no-framework-markers";

async function markerFindings(source, relative = "src/modules/widgets/Widget.tsx") {
  const eslint = new ESLint({ overrideConfigFile: true, overrideConfig: terpBoundaries });
  const [result] = await eslint.lintText(source, { filePath: path.resolve(relative) });
  return result.messages.filter((message) => message.ruleId === RULE);
}

async function markerLines(source, relative) {
  return (await markerFindings(source, relative)).map((message) => message.line);
}

describe("no-framework-markers", () => {
  it("refuses a data-terp attribute on a raw element and on a react-core component", async () => {
    const source = [
      'import { Card, Stack } from "@terpjs/react-core";',
      "export function Widget() {",
      "  return (",
      "    <Stack>",
      '      <div data-terp="card" />',
      '      <Stack data-terp="hubcard" />',
      "      <Card data-terp />",
      "    </Stack>",
      "  );",
      "}",
    ].join("\n");
    expect(await markerLines(source)).toEqual([5, 6, 7]);
  });

  it("applies across src, not only inside modules", async () => {
    // A replaced sign-in screen is passed to renderTerpApp from the bootstrap, and nothing
    // requires it to live in a module.
    const source = 'export const SignIn = () => <div data-terp="login-title" />;\n';
    expect(await markerLines(source, "src/SignIn.tsx")).toEqual([1]);
    expect(await markerLines(source, "src/main.tsx")).toEqual([1]);
  });

  it("refuses the whole data-terp- namespace, whatever the case", async () => {
    const source = [
      "export const Picked = () => <div data-terp-preview-pick />;",
      "export const Loud = () => <div DATA-TERP=\"card\" />;",
    ].join("\n");
    expect(await markerLines(source)).toEqual([1, 2]);
  });

  it("refuses the marker as the key of a props object", async () => {
    const source = [
      'import { createElement } from "react";',
      'export const Inline = () => <div {...{ "data-terp": "card" }} />;',
      'const props = { "data-terp": "card" };',
      "export const Hoisted = () => <div {...props} />;",
      'export const Computed = () => <div {...{ ["data-terp"]: "card" }} />;',
      'export const Built = () => createElement("div", { "data-terp": "card" });',
    ].join("\n");
    expect(await markerLines(source)).toEqual([2, 3, 5, 6]);
  });

  it("refuses the marker written through the DOM", async () => {
    const source = [
      "export function stamp(element: HTMLElement) {",
      '  element.setAttribute("data-terp", "card");',
      '  element.setAttributeNS(null, "data-terp", "card");',
      '  element.toggleAttribute("data-terp-preview-pick");',
      '  element.setAttribute("DATA-TERP", "card");',
      '  element.dataset.terp = "card";',
      '  element.dataset["terp"] = "card";',
      '  element.dataset.terpPreviewPick = "";',
      "}",
    ].join("\n");
    expect(await markerLines(source)).toEqual([2, 3, 4, 5, 6, 7, 8]);
  });

  it("leaves every other data attribute alone", async () => {
    const source = [
      "export function Widget({ element }: { element: HTMLElement }) {",
      '  element.setAttribute("data-testid", "summary");',
      '  element.setAttributeNS(null, "data-state", "open");',
      '  element.dataset.state = "open";',
      '  element.dataset.terpentine = "resin";',
      '  const props = { "data-testid": "summary" };',
      '  return <div data-testid="summary" data-terpentine="resin" {...props} />;',
      "}",
    ].join("\n");
    expect(await markerFindings(source)).toEqual([]);
  });

  it("leaves reading a marker alone", async () => {
    const source = [
      "export function describe(element: HTMLElement, props: Record<string, string>) {",
      '  const { "data-terp": marker } = props;',
      '  const card = element.querySelector(\'[data-terp="card"]\');',
      '  return [marker, element.getAttribute("data-terp"), element.dataset.terp, card];',
      "}",
    ].join("\n");
    expect(await markerFindings(source)).toEqual([]);
  });

  it("names the fix: compose the component, and test a replaced screen by its own names", async () => {
    const [finding] = await markerFindings('export const W = () => <div data-terp="card" />;\n');
    expect(finding.message).toContain("data-terp is one of react-core's markers");
    expect(finding.message).toContain("Compose the react-core component");
    expect(finding.message).toContain("roles and accessible names");
  });

  it("honours the catalog-derived governed marker for an intentional exception", async () => {
    const line = 'export const W = () => <div data-terp="card" />;';
    const eslint = new ESLint({ overrideConfigFile: true, overrideConfig: terpBoundaries });
    const filePath = path.resolve("src/modules/widgets/Widget.tsx");
    const [waived] = await eslint.lintText(
      `// terp-allow-no-framework-markers: recorded parity exception\n${line}\n`,
      { filePath },
    );
    expect(waived.messages).toEqual([]);
    // ...and the same line without the marker is reported, so the waiver is what cleared it.
    expect(await markerLines(`${line}\n`)).toEqual([1]);
  });
});
