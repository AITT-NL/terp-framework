// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { Component } from "react";
import { afterEach, describe, expect, it } from "vitest";

// The lint-side source of the contract table (spec-as-data in @terpjs/eslint-boundaries);
// react-core carries a TS mirror because a published runtime package cannot depend on a
// lint package. This parity test keeps the two identical, so the data cannot drift.
// @ts-expect-error — monorepo-relative untyped JS import, test-only
import * as lintLayouts from "../../eslint-boundaries/src/layouts.js";

import { DetailPage } from "./DetailPage";
import { HubCard, HubPage } from "./HubPage";
import {
  LAYOUT_CONTRACTS,
  LayoutContractContext,
  slotViolationMessage,
  verifySlotChildren,
} from "./layoutContract";
import { OverviewPage } from "./OverviewPage";
import { Page } from "./Page";
import { DetailList, Stack } from "./layout";
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
    expect([...named].sort()).toEqual([
      "alert",
      "card",
      "dataview",
      "detail-list",
      "dialog",
      "empty-state",
      "error-state",
      "hubcard",
      "loading-state",
      "module-nav",
      "resource-list",
      "stack",
      "tabs",
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
