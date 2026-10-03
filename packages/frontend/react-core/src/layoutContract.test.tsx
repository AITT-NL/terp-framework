// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { Component, useEffect, useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

// The lint-side source of the contract table (spec-as-data in @terpjs/eslint-boundaries);
// react-core carries a TS mirror because a published runtime package cannot depend on a
// lint package. This parity test keeps the two identical, so the data cannot drift.
// @ts-expect-error — monorepo-relative untyped JS import, test-only
import * as lintLayouts from "../../eslint-boundaries/src/layouts.js";

import { BarChart } from "./charts/BarChart";
import { TrendChart } from "./charts/TrendChart";
import { DashboardPage } from "./DashboardPage";
import { DetailPage } from "./DetailPage";
import { FormPage } from "./FormPage";
import { SettingsPage } from "./SettingsPage";
import { SplitPage, SplitPane } from "./SplitPage";
import { Input } from "./ui/Input";
import { Field } from "./Field";
import { HubCard, HubPage } from "./HubPage";
import {
  LAYOUT_CONTRACTS,
  LayoutContractContext,
  headlineViolationMessage,
  slotViolationMessage,
  summaryViolationMessage,
  verifySlotChildren,
} from "./layoutContract";
import { Stat, StatGroup } from "./Stat";
import { StatusHistory } from "./charts/StatusHistory";
import { Badge } from "./ui/Badge";
import { OverviewPage } from "./OverviewPage";

// The public surface, as source: the archetype-coverage check below derives its list from
// the entry point's own exports rather than restating one. `raw.d.ts` declares the ambient
// ImportMeta.glob type this shares with the other scanning tests in the package.
const entryPoint = Object.values(
  import.meta.glob("./index.ts", { query: "?raw", import: "default", eager: true }),
)[0] as string;
import { Page } from "./Page";
import { EmptyState } from "./EmptyState";
import { DetailList, Divider, Grid, Stack } from "./layout";
import { Text } from "./typography";
import { PageActions } from "./PageActions";
import { ThemeProvider, ThemeToggle } from "./theme";
import { Button } from "./ui/Button";
import { Card } from "./ui/Card";

afterEach(cleanup);

class CatchBoundary extends Component<
  { children: ReactNode },
  { message: string | null }
> {
  state = { message: null };
  static getDerivedStateFromError(error: Error) {
    return { message: error.message };
  }
  render() {
    return this.state.message === null ? (
      this.props.children
    ) : (
      <p data-testid="refused">{this.state.message}</p>
    );
  }
}

function underContract(children: ReactNode, contract: string | null = "standard") {
  return render(
    <CatchBoundary>
      <LayoutContractContext.Provider value={contract}>
        {children}
      </LayoutContractContext.Provider>
    </CatchBoundary>,
  );
}

/**
 * Assert that a composition was ACCEPTED — after actually letting the check run.
 *
 * The obvious spelling is a false green, and it was the shape every acceptance test in this file
 * used:
 *
 *     await waitFor(() => expect(screen.queryByTestId("refused")).toBeNull());
 *
 * `waitFor` retries until its callback stops throwing, so a callback asserting that something is
 * ABSENT passes on the very first attempt — before `Page`'s `setTimeout(0)` slot check has run at
 * all. It waits for nothing and can never fail. Nine tests claimed to gate the acceptance half of
 * ADR 0079 and gated nothing; verified by putting a `Grid` — which the OverviewPage slot table
 * does not admit — into a governed overview body and watching the suite stay green.
 *
 * Flushing one macrotask inside `act` is what makes the assertion mean something: the check has
 * then either thrown into the boundary or decided the body was legal.
 */
async function expectAccepted() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(screen.queryByTestId("refused")).toBeNull();
}

describe("layout contract parity (docs/data can't drift)", () => {
  it("mirrors the eslint-boundaries contract table byte-for-byte", () => {
    expect(JSON.parse(JSON.stringify(LAYOUT_CONTRACTS))).toEqual(
      JSON.parse(JSON.stringify(lintLayouts.LAYOUT_CONTRACTS)),
    );
  });

  it("phrases the identical directive message on both halves", () => {
    expect(slotViolationMessage("standard", "HubPage", "<div>")).toBe(
      lintLayouts.slotViolationMessage("standard", "HubPage", "<div>"),
    );
    expect(summaryViolationMessage("standard", "<div>")).toBe(
      lintLayouts.summaryViolationMessage("standard", "<div>"),
    );
    expect(headlineViolationMessage("standard", "2 figures marked headline")).toBe(
      lintLayouts.headlineViolationMessage("standard", "2 figures marked headline"),
    );
  });
});

describe("every archetype the package exports is governed, or says it is not", () => {
  // The gap this closes was a green build. `verifySlotChildren` returns null for a slot the
  // table does not name (layoutContract.ts:138-141) and the lint rule early-returns the same
  // way, so an archetype exported WITHOUT a table entry is silently ungoverned by both halves
  // of the control — no error, no warning, and a governed app renders it with the body slot
  // wide open. Nothing asserted the two lists agreed, which means "forgot the table entry"
  // was indistinguishable from "deliberately unconstrained".
  //
  // Derived from the public surface rather than restated as a list, because a list is the
  // thing that was missing: a new `FormPage` export joins this check by existing, and has to
  // either take a slot or come here and say why.
  // Two independent derivations, unioned, because each has a blind spot the other covers.
  //
  // The named-export scan reads `export { X } from` and `export { X as Y } from` — the alias
  // form matters, since the exported name is what a consumer writes. It cannot see
  // `export * from`, and index.ts already contains one (`./dataview`), so on its own this
  // derivation would let an archetype re-exported through a sub-namespace escape all three
  // assertions below INCLUDING the vacuity guard, which is built from the same scan.
  //
  // The filename scan covers exactly that: an archetype lives in `<Name>Page.tsx` by
  // convention, wherever in the tree it sits. It cannot see an archetype declared inside some
  // other file — which the export scan can.
  const namedExports = [...entryPoint.matchAll(/^export \{([^}]*)\} from/gm)]
    .flatMap((match) => match[1]!.split(","))
    // `A as B` exports B; a bare name exports itself.
    .map((entry) => entry.trim().split(/\s+as\s+/).pop()!.trim());
  const archetypeFiles = Object.keys(
    import.meta.glob("./**/*Page.tsx", { query: "?raw", import: "default", eager: true }),
  )
    .filter((file) => !file.includes(".test."))
    .map((file) => file.split("/").pop()!.replace(/\.tsx$/, ""));
  const exported = [
    ...new Set(
      [...namedExports, ...archetypeFiles]
        // `endsWith` rather than a `\w*Page$` regex, which cannot match "Page" itself:
        // after the leading capital there is no "Page" left to match. The vacuity guard below
        // caught that on the first run, which is the whole reason it is there.
        .filter((name) => /^[A-Z]\w*$/.test(name) && name.endsWith("Page")),
    ),
  ].sort();

  /**
   * Archetypes with no slot entry, and the reason each is unconstrained.
   *
   * One entry, and it is the contract's own pressure valve rather than an omission: the
   * plain `Page` is what a bespoke screen composes when no archetype fits, and the
   * contract's description says so in as many words. Anything else added here is a claim
   * that a screen shape has no vocabulary, which is the claim the table exists to refuse.
   */
  const DELIBERATELY_UNCONSTRAINED: Record<string, string> = {
    Page: "the bespoke pressure valve — a screen no archetype fits composes this, and the contract leaves it open by design",
  };

  it("finds the archetype exports it is meant to check", () => {
    // Vacuity guard: a derivation that matched nothing would make every assertion below pass.
    expect(exported).toEqual([
      "DashboardPage",
      "DetailPage",
      "FormPage",
      "HubPage",
      "OverviewPage",
      "Page",
      "SettingsPage",
      "SplitPage",
    ]);
  });

  it("pins the namespace re-exports, which neither derivation can look inside", () => {
    // `export * from "./x"` is opaque to both scans: the filename scan only sees files named
    // `*Page.tsx`, and the named-export scan sees no names at all. So the set of namespace
    // re-exports is pinned instead — adding one is the moment to check it carries no archetype,
    // and this assertion is what forces that look.
    const namespaces = [...entryPoint.matchAll(/^export \* from "([^"]+)"/gm)].map(
      (match) => match[1]!,
    );
    expect(namespaces).toEqual(["./dataview"]);
  });

  it("keeps no excuse for an archetype that is no longer exported", () => {
    // The reverse-direction test filters these keys out of its comparison, so a stale excuse
    // changes nothing there and would sit in the file for ever — quietly claiming that a
    // component nobody exports is deliberately unconstrained.
    for (const excused of Object.keys(DELIBERATELY_UNCONSTRAINED)) {
      expect(
        exported,
        `${excused} is excused from the slot table but is not an exported archetype — the excuse is stale`,
      ).toContain(excused);
    }
  });

  it("gives every exported archetype a slot, or a named reason for having none", () => {
    const slots = LAYOUT_CONTRACTS.standard!.slots;
    for (const archetype of exported) {
      const governed = archetype in slots;
      const excused = archetype in DELIBERATELY_UNCONSTRAINED;
      expect(
        governed || excused,
        `${archetype} is exported but has no LAYOUT_CONTRACTS.standard.slots entry, so both ` +
          "halves of the layout contract silently skip it. Add the slot (in this file AND in " +
          "eslint-boundaries/src/layouts.js), or add it to DELIBERATELY_UNCONSTRAINED with the " +
          "reason its body has no vocabulary.",
      ).toBe(true);
      expect(
        governed && excused,
        `${archetype} is both governed and excused — the excuse is stale, delete it`,
      ).toBe(false);
    }
  });

  it("names no slot that no archetype exports", () => {
    // The other direction: a slot for an archetype that was renamed or withdrawn is a table
    // entry nothing can ever satisfy, and the message it phrases names a component that is
    // no longer there.
    expect(Object.keys(LAYOUT_CONTRACTS.standard!.slots).sort()).toEqual(
      exported.filter((name) => !(name in DELIBERATELY_UNCONSTRAINED)),
    );
  });
});

describe("runtime slot enforcement", () => {
  it("refuses a non-HubCard child in a HubPage grid, fail closed, with the directive message", async () => {
    underContract(
      <HubPage title="Home">
        {/* not a HubCard — a rogue list item */}
        <li>rogue</li>
      </HubPage>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("refused").textContent).toBe(
        slotViolationMessage("standard", "HubPage", "<li>"),
      );
    });
  });

  it("passes a conforming HubPage of HubCards", async () => {
    underContract(
      <HubPage title="Home">
        <HubCard to="/a" title="Area A" />
        <HubCard to="/b" title="Area B" />
      </HubPage>,
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByTestId("refused")).toBeNull();
    expect(screen.getByText("Area A")).toBeDefined();
  });

  it("refuses bespoke content in an OverviewPage body and names the found element", async () => {
    underContract(
      <OverviewPage title="Records">
        <div>hand-rolled listing</div>
      </OverviewPage>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("refused").textContent).toBe(
        slotViolationMessage("standard", "OverviewPage", "<div>"),
      );
    });
  });

  it("passes an OverviewPage whose body is allowed components", async () => {
    underContract(
      <OverviewPage title="Records">
        <Stack>
          <span>toolbar content lives inside allowed containers</span>
        </Stack>
      </OverviewPage>,
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByTestId("refused")).toBeNull();
  });

  it("passes a DetailPage of record sections and refuses a rogue one", async () => {
    underContract(
      <DetailPage title="Record 1" parents={[{ label: "Records", to: "/records" }]}>
        <Card title="A section">the sanctioned visual separation, directly in the slot</Card>
        <Stack>
          <DetailList items={[{ label: "Status", value: "open" }]} />
        </Stack>
      </DetailPage>,
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByTestId("refused")).toBeNull();
    cleanup();

    underContract(
      <DetailPage title="Record 1" parents={[{ label: "Records", to: "/records" }]}>
        <table />
      </DetailPage>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("refused").textContent).toBe(
        slotViolationMessage("standard", "DetailPage", "<table>"),
      );
    });
  });

  it("passes a governed DetailPage that steps through a sequence", async () => {
    // The bar is a `nav` of the page's own, and the check reads every child of the article
    // except its header as body — so a bar rendered inside the article would be judged a
    // body child no slot table admits, and fail every governed page closed. It renders after
    // the article instead, where the check never looks.
    const { container } = underContract(
      <DetailPage
        title="Record 4"
        parents={[{ label: "Records", to: "/records" }]}
        sequence={{
          label: "Records",
          previous: { label: "Record 3", to: "/records/3" },
          next: { label: "Record 5", to: "/records/5" },
          position: { current: 4, total: 9 },
        }}
      >
        <Card title="A section">the record</Card>
      </DetailPage>,
    );
    await expectAccepted();
    expect(container.querySelector('[data-terp="page"] [data-terp="page-sequence"]')).toBeNull();
    expect(container.querySelector('[data-terp="page"] + [data-terp="page-sequence"]')).not.toBeNull();
  });

  it("leaves the plain Page unconstrained (the contract's bespoke pressure valve)", async () => {
    underContract(
      <Page title="Bespoke">
        <div>anything goes here</div>
      </Page>,
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByTestId("refused")).toBeNull();
  });

  it("skips the check while the archetype shows the loading / error frame", async () => {
    underContract(
      <OverviewPage title="Records" isLoading>
        <div>never rendered</div>
      </OverviewPage>,
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByTestId("refused")).toBeNull();
  });

  it("does nothing without an opted-in contract (backwards compatible)", async () => {
    underContract(
      <OverviewPage title="Records">
        <div>legacy body</div>
      </OverviewPage>,
      null,
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByTestId("refused")).toBeNull();
  });

  it("verifySlotChildren returns null for an ungoverned contract/slot", () => {
    expect(verifySlotChildren("ghost", "HubPage", [])).toBeNull();
    expect(verifySlotChildren("standard", "Page", [])).toBeNull();
  });
});

// The styling migration (ADR 0094) is renaming rendered roots: components that used to emit
// an unmarked <div>, or to borrow Popover's `popover`, now name themselves. Every one of those
// names is read by this check, because the check IS the marker join — so the question is not
// whether the names look sensible but whether any slot's verdict moved.
//
// It did not, and the reason is worth stating rather than re-derived: verifySlotChildren
// refuses a direct body-slot child whose data-terp is not in the slot's allow table, and a
// missing attribute is refused too (`marker === null`). None of the new names is in any table,
// and neither was the unmarked element each replaced. So each of these was refused before the
// migration and is refused after it. What changed is the MESSAGE — describeElement now reports
// a named component instead of a bare tag, which is strictly more useful to the person reading
// the refusal, and is also a string a test could have pinned.
describe("layout contract survives the roots the styling migration renames", () => {
  it("still refuses a chrome menu in a governed body, and now names it", async () => {
    underContract(
      // The provider renders no element of its own, so the slot's direct child is still the
      // toggle. Without it ThemeToggle returns null and the body is empty — which passes for
      // no reason at all.
      <ThemeProvider>
        <OverviewPage title="Records">
          <ThemeToggle variant="stacked" />
        </OverviewPage>
      </ThemeProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("refused").textContent).toBe(
        slotViolationMessage("standard", "OverviewPage", '<div data-terp="theme-toggle">'),
      );
    });
  });

  it("still refuses an action cluster in a governed body, and now names it", async () => {
    underContract(
      <DetailPage title="Record 1" parents={[{ label: "Records", to: "/records" }]}>
        <PageActions primary={<Button>Publish</Button>} />
      </DetailPage>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("refused").textContent).toBe(
        slotViolationMessage("standard", "DetailPage", '<div data-terp="page-actions">'),
      );
    });
  });

  it("keeps every marker the allow tables name out of the migration's way", () => {
    // The tables are the audit surface: a rename of one of THESE would widen or close a slot
    // silently, so they are the markers the migration may not touch without changing both
    // halves of the contract. Asserted as a set so an addition has to be deliberate.
    const named = new Set(
      Object.values(LAYOUT_CONTRACTS.standard!.slots).flatMap((slot) =>
        Object.values(slot.components),
      ),
    );
    // The dashboard's body (ADR 0169 §4) added the figure and chart families -- the run history
    // among the charts -- and the timeline.
    expect([...named].sort()).toEqual([
      "alert",
      "bar-chart",
      "card",
      "dataview",
      "detail-list",
      "detail-list-group",
      "dialog",
      "divider",
      "empty-state",
      "error-state",
      "grid",
      "hubcard",
      "loading-state",
      "module-nav",
      "proportion-bar",
      "resource-list",
      "splitpane",
      "stack",
      "stat",
      "stat-group",
      "status-history",
      "tabs",
      "text",
      "timeline",
      "trend-chart",
    ]);
  });

  it("passes a governed body whose children are still allowed components", async () => {
    // The other direction: the migration must not have widened anything either. A Stack and a
    // Card are allowed, and they stay allowed with their markers unchanged.
    underContract(
      <ThemeProvider>
        <DetailPage title="Record 1" parents={[{ label: "Records", to: "/records" }]}>
          <Card title="A section">body</Card>
          <Stack>
            <ThemeToggle variant="stacked" />
          </Stack>
        </DetailPage>
      </ThemeProvider>,
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    // And the toggle really did render, or this asserts nothing.
    expect(document.querySelector('[data-terp="theme-toggle"]')).not.toBeNull();
    // Nested inside an allowed container is sanctioned composition — the check reads direct
    // children only, which is what makes a marked root safe to put anywhere below one.
    expect(screen.queryByTestId("refused")).toBeNull();
  });
});

describe("what 4b's widening does and does not admit", () => {
  it("accepts a Grid in a detail body, which is the two-column form case", async () => {
    // The diagnosis's headline evidence was a fifteen-field form shipped as one vertical run.
    // Shipping `Grid` without this widening would have shipped a component no governed page
    // could use — and only a copier-generated project has the contract switched on, so the
    // example app could not have detected that either.
    underContract(
      <DetailPage title="Record" parents={[{ label: "Records", to: "/records" }]}>
        <Grid columns={2}>
          <span>one</span>
          <span>two</span>
        </Grid>
      </DetailPage>,
    );
    await expectAccepted();
  });

  it("still refuses a Grid in an overview body, because a grid there is a hub", () => {
    // The asymmetry IS the decision, so it is pinned rather than left to the table. An
    // overview body is a data collection; a grid of summary cards is a hub, and the contract
    // has a hub archetype for that. Widening both slots identically would have been the easy
    // move and would have dissolved the distinction the three levels exist to carry.
    underContract(
      <OverviewPage title="Records">
        <Grid columns={2}>
          <span>one</span>
        </Grid>
      </OverviewPage>,
    );
    return waitFor(() => {
      expect(screen.getByTestId("refused").textContent).toBe(
        slotViolationMessage("standard", "OverviewPage", '<div data-terp="grid">'),
      );
    });
  });

  it("refuses a bare Field at the top of a form body, because that form cannot submit", () => {
    // The one refusal in FormPage's slot that is a decision rather than an omission. A run of
    // bare fields looks like a finished form and cannot be submitted: Enter does nothing
    // without a <form>, and the house spelling of one is `Stack as="form"`. So the slot takes
    // the container and not the fields — which is the opposite of what a reader would guess
    // from "a form page's body is fields".
    underContract(
      <FormPage title="New sync" parents={[{ label: "Syncs", to: "/syncs" }]}>
        <Field label="Name">
          <Input />
        </Field>
      </FormPage>,
    );
    return waitFor(() => {
      expect(screen.getByTestId("refused")).toHaveTextContent(
        /the FormPage body slot accepts only Stack \/ Grid \/ Card/,
      );
    });
  });

  it("accepts a form body that is a form container with sections beside it", () => {
    underContract(
      <FormPage title="New sync" parents={[{ label: "Syncs", to: "/syncs" }]}>
        <Text>Every definition needs a source and a target.</Text>
        <Stack as="form">
          <Field label="Name">
            <Input />
          </Field>
        </Stack>
      </FormPage>,
    );
    return waitFor(() => {
      expect(screen.queryByTestId("refused")).not.toBeInTheDocument();
    });
  });

  it("refuses a collection in a settings body, because that screen is an overview", () => {
    // SettingsPage's slot is Card sections and nothing that holds a collection. A settings
    // screen whose body is a table is an overview with the wrong chrome, and the contract is
    // where that distinction is enforceable rather than advisory.
    underContract(
      <SettingsPage title="Preferences">
        <DetailList items={[{ label: "Theme", value: "Dark" }]} />
      </SettingsPage>,
    );
    return waitFor(() => {
      expect(screen.getByTestId("refused")).toHaveTextContent(
        /the SettingsPage body slot accepts only Card \/ Stack/,
      );
    });
  });

  it("refuses anything but a SplitPane inside a split, and accepts the two panes", async () => {
    // The split governs its PANE ROW rather than the page body, which is HubPage's shape and
    // not DetailPage's — so this is the assertion that the choice actually took effect. A
    // Card dropped straight into the split is the realistic mistake.
    underContract(
      <SplitPage title="Syncs">
        <Card title="Not a pane" />
      </SplitPage>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("refused")).toHaveTextContent(
        /the SplitPage body slot accepts only SplitPane/,
      );
    });
    cleanup();
    underContract(
      <SplitPage title="Syncs">
        <SplitPane role="list" label="Definitions">
          <DetailList items={[{ label: "Customer master", value: "ok" }]} />
        </SplitPane>
        <SplitPane role="detail" label="Selected definition">
          <Card title="Customer master" />
        </SplitPane>
      </SplitPage>,
    );
    await waitFor(() => {
      expect(screen.queryByTestId("refused")).not.toBeInTheDocument();
    });
  });

  it("accepts a Divider and a lead paragraph in both governed bodies", async () => {
    // A rule between sections and a paragraph above them — the two things a body wanted that
    // needed no container. `Heading` is deliberately NOT admitted: a heading in a governed body
    // must own its section, and `Card` (plain or boxed) is how a section is owned. A bare
    // heading with siblings after it is a grouping the contract cannot see.
    for (const page of [
      <OverviewPage key="o" title="Records">
        <Text>Lead paragraph.</Text>
        <Divider />
        <EmptyState title="No records yet" />
      </OverviewPage>,
      <DetailPage key="d" title="Record" parents={[{ label: "Records", to: "/records" }]}>
        <Text>Lead paragraph.</Text>
        <Divider />
        <DetailList items={[{ label: "Owner", value: "Ada" }]} />
      </DetailPage>,
    ]) {
      cleanup();
      underContract(page);
      // Per iteration, not once after the loop. Two separate faults met here and only the
      // second one mattered. `Page` schedules its check as a setTimeout(0) and clears it on
      // unmount while RTL's `cleanup` unmounts synchronously, so a single trailing assertion
      // cancelled the OverviewPage timer and only ever reached the DetailPage. But moving the
      // assertion inside the loop changed nothing on its own, because the assertion itself
      // could not fail — see `expectAccepted`. Verified together: an illegal Grid in the
      // OverviewPage body above is green under either old form and red under this one.
      await expectAccepted();
    }
  });
});

describe("runtime enforcement of the page frame's two rules (ADR 0169 §4)", () => {
  it("passes a summary of figures, a badge and a line of text", async () => {
    underContract(
      <DetailPage
        title="Record 1"
        parents={[{ label: "Records", to: "/records" }]}
        summary={
          <>
            <StatGroup>
              <Stat label="Open" value={3} headline />
              <Stat label="Closed" value={9} />
            </StatGroup>
            <Badge tone="success">Active</Badge>
            <Text>Synced four minutes ago.</Text>
          </>
        }
      >
        <Card title="A section">the record</Card>
      </DetailPage>,
    );
    await expectAccepted();
  });

  it("refuses anything else in a summary, on an archetype, with the directive message", async () => {
    // Mutation: drop the summary half of verifyPageFrame, and the card is accepted.
    underContract(
      <OverviewPage title="Records" summary={<Card title="Not a figure">x</Card>}>
        <Stack>
          <span>body</span>
        </Stack>
      </OverviewPage>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("refused").textContent).toBe(
        summaryViolationMessage("standard", '<section data-terp="card">'),
      );
    });
  });

  it("governs the plain Page's summary too, whose body stays free", async () => {
    // Mutation: run the frame check only under a slot owner again, and this is accepted.
    underContract(
      <Page title="Bespoke" summary={<div>loose</div>}>
        <div>a bespoke body, which the contract leaves alone</div>
      </Page>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("refused").textContent).toBe(
        summaryViolationMessage("standard", "<div>"),
      );
    });
  });

  it("refuses a second headline anywhere on the page", async () => {
    // One in the summary and one in the body is two on the page.
    // Mutation: count only the summary's figures, and this is accepted.
    underContract(
      <Page title="Bespoke" summary={<Stat label="Revenue" value={1} headline />}>
        <Grid template="1:1">
          <Stat label="Margin" value={2} headline />
          <Stat label="Costs" value={3} />
        </Grid>
      </Page>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("refused").textContent).toBe(
        headlineViolationMessage("standard", "2 figures marked headline"),
      );
    });
  });

  it("passes a page with one headline", async () => {
    underContract(
      <Page title="Bespoke" summary={<Stat label="Revenue" value={1} headline />}>
        <Grid template="1:1">
          <Stat label="Margin" value={2} />
          <Stat label="Costs" value={3} />
        </Grid>
      </Page>,
    );
    await expectAccepted();
  });

  it("checks nothing without a contract", async () => {
    underContract(
      <Page title="Bespoke" summary={<div>loose</div>}>
        <Stat label="A" value={1} headline />
        <Stat label="B" value={2} headline />
      </Page>,
      null,
    );
    await expectAccepted();
  });
});

describe("a page counts the headlines that register with it (ADR 0169 §4)", () => {
  function LateHeadline() {
    // A section that shows its figure once its own data arrives: nothing renders the page again.
    const [ready, setReady] = useState(false);
    useEffect(() => {
      const timer = setTimeout(() => setReady(true), 5);
      return () => clearTimeout(timer);
    }, []);
    return ready ? <Stat label="Late" value={2} headline /> : null;
  }

  it("refuses a second headline that renders after the page did", async () => {
    // A DOM count taken one macrotask after the page rendered found one headline and was never
    // taken again. Mutation: count by DOM again, and the late figure ships.
    underContract(
      <Page title="Bespoke" summary={<Stat label="Revenue" value={1} headline />}>
        <Stack>
          <LateHeadline />
        </Stack>
      </Page>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("refused").textContent).toBe(
        headlineViolationMessage("standard", "2 figures marked headline"),
      );
    });
  });

  it("counts a nested page's headline on its own, as the lint does", async () => {
    // The outer page counted the inner page's figure as its own, and refused what the lint
    // accepts. Mutation: provide one registry for both pages, and this is refused.
    underContract(
      <Page title="Outer">
        <Page title="Inner" summary={<Stat label="Inner" value={1} headline />}>
          <div>inner body</div>
        </Page>
        <Stat label="Outer" value={2} headline />
      </Page>,
    );
    await expectAccepted();
  });
});

describe("the summary band admits a status history (ADR 0169 §4)", () => {
  it("passes a page whose summary holds the recent runs", async () => {
    // Mutation: drop StatusHistory from the summary table, and this is refused.
    underContract(
      <Page
        title="Customer master"
        summary={
          <StatusHistory
            label="Runs"
            runs={[{ label: "Mon", outcome: { label: "Succeeded", tone: "success" } }]}
          />
        }
      >
        <div>body</div>
      </Page>,
    );
    await expectAccepted();
  });
});

describe("the dashboard's body (ADR 0169 §4)", () => {
  it("passes figures and charts in a templated section, and the collection they summarise", async () => {
    underContract(
      <DashboardPage title="Overview" summary={<StatGroup><Stat label="Runs" value={84} /></StatGroup>}>
        <Grid template="2:1">
          <TrendChart label="Runs per day" series={{ label: "Runs", points: [{ label: "Mon", value: 3 }] }} />
          <BarChart label="By source" bars={[{ label: "Ledger", value: 9 }]} />
        </Grid>
        <TrendChart label="Rows" mark="columns" series={{ label: "Rows", points: [{ label: "Mon", value: 3 }] }} />
        <Stat label="Failed runs" value={3} />
        {/* Mutation: drop StatusHistory from the dashboard's table, and this is refused. */}
        <StatusHistory label="Runs" runs={[{ label: "Mon", outcome: { label: "Succeeded", tone: "success" } }]} />
      </DashboardPage>,
    );
    await expectAccepted();
  });

  it("refuses a body block the dashboard does not admit, with the directive message", async () => {
    // Mutation: drop the DashboardPage slot table, and the dashboard's body is unconstrained.
    underContract(
      <DashboardPage title="Overview">
        <div>hand-rolled tiles</div>
      </DashboardPage>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("refused").textContent).toBe(
        slotViolationMessage("standard", "DashboardPage", "<div>"),
      );
    });
  });
});
