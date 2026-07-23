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
