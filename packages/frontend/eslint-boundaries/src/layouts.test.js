import path from "node:path";

import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

import terpBoundaries from "./index.js";
import { LAYOUT_CONTRACTS, slotViolationMessage } from "./layouts.js";

// The build-time half of the slot-typed layout contract control (ADR 0079): prove the
// `terp/layout-contract` rule fires on a non-conforming slot child, stays quiet on
// conforming screens, and stays fully inert when the app has not opted into a contract.
// The rule option stands in for the checked-in layout-contract.json here (the file
// lookup is exercised by consumers; tests must not depend on the repo's cwd).

const MODULE_FILE = path.resolve("src/modules/widgets/Widget.tsx");

function configWithContract(contract) {
  return terpBoundaries.map((entry) =>
    entry.rules?.["terp/layout-contract"]
      ? {
          ...entry,
          rules: { ...entry.rules, "terp/layout-contract": ["error", { contract }] },
        }
      : entry,
  );
}

async function lint(code, config = terpBoundaries) {
  const eslint = new ESLint({ overrideConfigFile: true, overrideConfig: config });
  const [result] = await eslint.lintText(code, { filePath: MODULE_FILE });
  return result.messages;
}

describe("terp/layout-contract", () => {
  it("is inert without an opted-in contract (backwards compatible)", async () => {
    const code =
      'import { HubPage } from "@terpjs/react-core";\n' +
      "export const W = () => <HubPage title='x'><div /></HubPage>;";
    expect((await lint(code)).map((m) => m.ruleId)).toEqual([]);
  });

  it("refuses a non-conforming child in a HubPage body, with the directive message", async () => {
    const code =
      'import { HubPage, Stack } from "@terpjs/react-core";\n' +
      "export const W = () => <HubPage title='x'><Stack /></HubPage>;";
    const messages = await lint(code, configWithContract("standard"));
    expect(messages.map((m) => m.ruleId)).toContain("terp/layout-contract");
    expect(messages[0].message).toBe(slotViolationMessage("standard", "HubPage", "<Stack>"));
  });

  it("passes a conforming hub / overview / detail composition", async () => {
    const code = [
      'import { DataView, DetailList, HubCard, HubPage, OverviewPage, DetailPage, Stack } from "@terpjs/react-core";',
      "export const H = () => <HubPage title='x'><HubCard to='/a' title='a' /></HubPage>;",
      "export const O = () => <OverviewPage title='x'><DataView /></OverviewPage>;",
      "export const D = () => <DetailPage title='x' parents={[]}><Stack><DetailList items={[]} /></Stack></DetailPage>;",
    ].join("\n");
    expect((await lint(code, configWithContract("standard"))).map((m) => m.ruleId)).toEqual([]);
  });

  it("refuses raw text and recurses through fragments; dynamic children are left to the runtime half", async () => {
    const text =
      'import { OverviewPage } from "@terpjs/react-core";\n' +
      "export const W = () => <OverviewPage title='x'>loose text</OverviewPage>;";
    expect((await lint(text, configWithContract("standard"))).map((m) => m.ruleId)).toContain(
      "terp/layout-contract",
    );
    const fragment =
      'import { HubPage } from "@terpjs/react-core";\n' +
      "export const W = () => <HubPage title='x'><><span /></></HubPage>;";
    expect((await lint(fragment, configWithContract("standard"))).map((m) => m.ruleId)).toContain(
      "terp/layout-contract",
    );
    const dynamic =
      'import { HubPage } from "@terpjs/react-core";\n' +
      "export const W = ({items}) => <HubPage title='x'>{items}</HubPage>;";
    expect((await lint(dynamic, configWithContract("standard"))).map((m) => m.ruleId)).toEqual([]);
  });

  it("reports an unknown contract id, fail closed", async () => {
    const messages = await lint("export const W = () => null;", configWithContract("ghost"));
    expect(messages.map((m) => m.ruleId)).toContain("terp/layout-contract");
    expect(messages[0].message).toContain('Unknown layout contract "ghost"');
  });

  it("honours a justified escape-hatch marker (and only a justified one)", async () => {
    const code =
      'import { HubPage } from "@terpjs/react-core";\n' +
      "export const W = () => <HubPage title='x'>\n" +
      "  {/* terp-allow-layout-contract: legacy widget pending HubCard port */}\n" +
      "  <div />\n" +
      "</HubPage>;";
    expect((await lint(code, configWithContract("standard"))).map((m) => m.ruleId)).toEqual([]);
  });

  it("declares a marker-named runtime marker for every allowed component (data sanity)", () => {
    for (const contract of Object.values(LAYOUT_CONTRACTS)) {
      for (const slot of Object.values(contract.slots)) {
        for (const [name, marker] of Object.entries(slot.components)) {
          expect(name).toMatch(/^[A-Z]/);
          expect(marker).toMatch(/^[a-z][a-z-]*$/);
        }
      }
    }
  });
});
