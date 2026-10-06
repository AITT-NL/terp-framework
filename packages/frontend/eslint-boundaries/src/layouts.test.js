import path from "node:path";

import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

import terpBoundaries from "./index.js";
import {
  LAYOUT_CONTRACTS,
  headlineViolationMessage,
  slotViolationMessage,
  summaryViolationMessage,
} from "./layouts.js";

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
      "export const W = ({title}) => <HubPage title={title}><div /></HubPage>;";
    expect((await lint(code)).map((m) => m.ruleId)).toEqual([]);
  });

  it("refuses a non-conforming child in a HubPage body, with the directive message", async () => {
    const code =
      'import { HubPage, Stack } from "@terpjs/react-core";\n' +
      "export const W = ({title}) => <HubPage title={title}><Stack /></HubPage>;";
    const messages = await lint(code, configWithContract("standard"));
    expect(messages.map((m) => m.ruleId)).toContain("terp/layout-contract");
    expect(messages[0].message).toBe(slotViolationMessage("standard", "HubPage", "<Stack>"));
  });

  it("passes a conforming hub / overview / detail composition", async () => {
    const code = [
      'import { Card, DataView, DetailList, HubCard, HubPage, OverviewPage, DetailPage, Stack } from "@terpjs/react-core";',
      "export const H = ({title}) => <HubPage title={title}><HubCard to='/a' title={title} /></HubPage>;",
      "export const O = ({title}) => <OverviewPage title={title}><Card title={title}><DataView /></Card></OverviewPage>;",
      "export const D = ({title, body}) => <DetailPage title={title} parents={[]}><Card title={title}>{body}</Card><Stack><DetailList items={[]} /></Stack></DetailPage>;",
    ].join("\n");
    expect((await lint(code, configWithContract("standard"))).map((m) => m.ruleId)).toEqual([]);
  });

  it("refuses raw text and recurses through fragments; dynamic children are left to the runtime half", async () => {
    const text =
      'import { OverviewPage } from "@terpjs/react-core";\n' +
      "export const W = ({title}) => <OverviewPage title={title}>loose text</OverviewPage>;";
    expect((await lint(text, configWithContract("standard"))).map((m) => m.ruleId)).toContain(
      "terp/layout-contract",
    );
    const fragment =
      'import { HubPage } from "@terpjs/react-core";\n' +
      "export const W = ({title}) => <HubPage title={title}><><span /></></HubPage>;";
    expect((await lint(fragment, configWithContract("standard"))).map((m) => m.ruleId)).toContain(
      "terp/layout-contract",
    );
    const dynamic =
      'import { HubPage } from "@terpjs/react-core";\n' +
      "export const W = ({title, items}) => <HubPage title={title}>{items}</HubPage>;";
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
      "export const W = ({title}) => <HubPage title={title}>\n" +
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

describe("terp/layout-contract — the page frame's two rules (ADR 0169 §4)", () => {
  const imports =
    'import { Badge, Card, DataView, DetailPage, OverviewPage, Page, Stack, Stat, StatGroup, Text } from "@terpjs/react-core";\n';

  it("governs a dashboard's body: figures and charts pass, a bare element is refused", async () => {
    const code =
      'import { BarChart, DashboardPage, Grid, Stat, StatusHistory, TrendChart } from "@terpjs/react-core";\n' +
      "export const D = ({title, points, runs}) => <DashboardPage title={title}><Grid template=\"2:1\"><TrendChart label={title} series={points} /><BarChart label={title} bars={[]} /></Grid><Stat label={title} value={1} /><StatusHistory label={title} runs={runs} /></DashboardPage>;\n" +
      "export const E = ({title}) => <DashboardPage title={title}><div /></DashboardPage>;";
    expect((await lint(code, configWithContract("standard"))).map((m) => m.message)).toEqual([
      slotViolationMessage("standard", "DashboardPage", "<div>"),
    ]);
  });

  it("governs a workspace's body: one canvas passes, a hand-sized box is refused (ADR 0179)", async () => {
    // What is drawn ON the canvas is the app's: the svg below is the host's child, not the slot's.
    const code =
      'import { CanvasHost, EmptyState, WorkspacePage } from "@terpjs/react-core";\n' +
      "export const W = ({title}) => <WorkspacePage title={title}><CanvasHost label={title}><svg viewBox=\"0 0 10 10\" /></CanvasHost></WorkspacePage>;\n" +
      "export const L = ({title}) => <WorkspacePage title={title}><EmptyState title={title} /></WorkspacePage>;\n" +
      "export const X = ({title}) => <WorkspacePage title={title}><div /></WorkspacePage>;";
    expect((await lint(code, configWithContract("standard"))).map((m) => m.message)).toEqual([
      slotViolationMessage("standard", "WorkspacePage", "<div>"),
    ]);
  });

  it("passes a status history in the summary", async () => {
    const code =
      'import { Page, StatusHistory } from "@terpjs/react-core";\n' +
      "export const P = ({title, runs}) => <Page title={title} summary={<StatusHistory label={title} runs={runs} />}><div /></Page>;";
    expect((await lint(code, configWithContract("standard"))).map((m) => m.message)).toEqual([]);
  });

  it("passes a summary of the page's own figures, on an archetype and on the plain Page", async () => {
    const code =
      imports +
      "export const O = ({title, n}) => <OverviewPage title={title} summary={<StatGroup><Stat label={title} value={n} /></StatGroup>}><DataView /></OverviewPage>;\n" +
      "export const D = ({title, n}) => <DetailPage title={title} parents={[]} summary={<><Stat label={title} value={n} /><Badge label={title} /><Text>{title}</Text></>}><Card title={title} /></DetailPage>;\n" +
      "export const P = ({title, n, figures}) => <Page title={title} summary={figures}><div /></Page>;";
    expect((await lint(code, configWithContract("standard"))).map((m) => m.message)).toEqual([]);
  });

  it("refuses anything else in a summary, on the plain Page too, with the directive message", async () => {
    // Mutation: drop checkSummary from the visitor, and both pages lint clean.
    const code =
      imports +
      "export const O = ({title}) => <OverviewPage title={title} summary={<DataView />}><DataView /></OverviewPage>;\n" +
      "export const P = ({title}) => <Page title={title} summary={<><Stat label={title} value={1} /><Card title={title} /></>}><div /></Page>;";
    const messages = (await lint(code, configWithContract("standard"))).map((m) => m.message);
    expect(messages).toEqual([
      summaryViolationMessage("standard", "<DataView>"),
      summaryViolationMessage("standard", "<Card>"),
    ]);
  });

  it("refuses a summary that is a bare string or a template literal", async () => {
    const code =
      imports +
      'export const A = ({title}) => <Page title={title} summary="Twelve open">{title}</Page>;\n' +
      "export const B = ({title, n}) => <Page title={title} summary={`${n} open`}>{title}</Page>;";
    const messages = await lint(code, configWithContract("standard"));
    expect(
      messages.filter((m) => m.ruleId === "terp/layout-contract").map((m) => m.message),
    ).toEqual([
      summaryViolationMessage("standard", "raw text"),
      summaryViolationMessage("standard", "raw text"),
    ]);
  });

  it("reads a bare-string summary as copy to translate, with or without a contract", async () => {
    // The band takes rendered nodes, as `actions` does, so a string written there is copy the
    // app's catalog never sees. Mutation: drop "summary" from UI_TEXT_ATTRIBUTES, and an app
    // with no contract ships it untranslated.
    const code =
      imports + 'export const A = ({title}) => <Page title={title} summary="Twelve open">{title}</Page>;';
    expect((await lint(code)).map((m) => m.ruleId)).toEqual(["terp/no-untranslated-ui"]);
  });

  it("refuses a page that carries two headline figures, wherever in its JSX they sit", async () => {
    // One in the summary and one in the body is still two on the page.
    // Mutation: report only when the count exceeds 2, and this lints clean.
    const code =
      imports +
      "export const D = ({title}) => <DetailPage title={title} parents={[]} summary={<Stat headline label={title} value={1} />}><Stack><Stat headline label={title} value={2} /></Stack></DetailPage>;";
    const messages = (await lint(code, configWithContract("standard"))).map((m) => m.message);
    expect(messages).toEqual([headlineViolationMessage("standard", "2 figures marked headline")]);
  });

  it("counts one headline per page, so a page with one passes and headline={false} is not one", async () => {
    const code =
      imports +
      "export const D = ({title}) => <DetailPage title={title} parents={[]} summary={<StatGroup><Stat headline label={title} value={1} /><Stat headline={false} label={title} value={2} /></StatGroup>}><Card title={title} /></DetailPage>;";
    expect((await lint(code, configWithContract("standard"))).map((m) => m.message)).toEqual([]);
  });

  it("counts the larger branch of a conditional, since only one branch renders", async () => {
    // Mutation: sum both branches, and this exclusive pair is refused.
    const exclusive =
      imports +
      "export const P = ({title, a}) => <Page title={title} summary={a ? <Stat headline label={title} value={1} /> : <Stat headline label={title} value={2} />}><div /></Page>;";
    expect((await lint(exclusive, configWithContract("standard"))).map((m) => m.message)).toEqual([]);
    const both =
      imports +
      "export const P = ({title, a}) => <Page title={title} summary={<>{a && <Stat headline label={title} value={1} />}<Stat headline label={title} value={2} /></>}><div /></Page>;";
    expect((await lint(both, configWithContract("standard"))).map((m) => m.message)).toEqual([
      headlineViolationMessage("standard", "2 figures marked headline"),
    ]);
  });

  it("reads summary={null} and summary={false} as the band left out", async () => {
    // Mutation: report any Literal as raw text again, and both are refused.
    const code =
      imports +
      "export const A = ({title}) => <Page title={title} summary={null}><div /></Page>;\n" +
      "export const B = ({title}) => <Page title={title} summary={false}><div /></Page>;";
    expect((await lint(code, configWithContract("standard"))).map((m) => m.message)).toEqual([]);
  });

  it("leaves a headline decided by an expression to the runtime's count", async () => {
    // `headline={isMain}` beside `headline={!isMain}` is one headline at a time, which no
    // static count can see. Mutation: count expression values again, and this is refused.
    const code =
      imports +
      "export const P = ({title, isMain}) => <Page title={title}><Stat headline={isMain} label={title} value={1} /><Stat headline={!isMain} label={title} value={2} /></Page>;";
    expect((await lint(code, configWithContract("standard"))).map((m) => m.message)).toEqual([]);
    const literal =
      imports +
      "export const P = ({title}) => <Page title={title}><Stat headline={true} label={title} value={1} /><Stat headline label={title} value={2} /></Page>;";
    expect((await lint(literal, configWithContract("standard"))).map((m) => m.message)).toEqual([
      headlineViolationMessage("standard", "2 figures marked headline"),
    ]);
  });

  it("counts a nested page on its own rather than twice", async () => {
    const code =
      imports +
      "export const P = ({title}) => <Page title={title}><Page title={title} summary={<Stat headline label={title} value={1} />}><div /></Page><Stat headline label={title} value={2} /></Page>;";
    expect((await lint(code, configWithContract("standard"))).map((m) => m.message)).toEqual([]);
  });

  it("is inert without an opted-in contract", async () => {
    const code =
      imports +
      "export const P = ({title}) => <Page title={title} summary={<DataView />}><Stat headline label={title} value={1} /><Stat headline label={title} value={2} /></Page>;";
    expect((await lint(code)).map((m) => m.ruleId)).toEqual([]);
  });

  it("declares a marker-named runtime marker for every summary and headline component (data sanity)", () => {
    for (const contract of Object.values(LAYOUT_CONTRACTS)) {
      for (const table of [contract.summary.components, contract.headline.components]) {
        for (const [name, marker] of Object.entries(table)) {
          expect(name).toMatch(/^[A-Z]/);
          expect(marker).toMatch(/^[a-z][a-z-]*$/);
        }
      }
    }
  });
});
