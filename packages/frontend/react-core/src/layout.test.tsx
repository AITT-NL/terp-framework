// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DetailList, Grid, Stack } from "./layout";

afterEach(cleanup);

describe("Stack", () => {
  it("names a column at the default gap, with no inline styling", () => {
    render(
      <Stack data-testid="stack">
        <span>a</span>
        <span>b</span>
      </Stack>,
    );
    const el = screen.getByTestId("stack");
    expect(el.tagName).toBe("DIV");
    expect(el).toHaveAttribute("data-direction", "column");
    expect(el).toHaveAttribute("data-gap", "2");
    expect(el).not.toHaveAttribute("data-wrap");
    expect(el.getAttribute("style")).toBeNull();
  });

  it("renders the requested element and names direction, gap and wrap", () => {
    render(
      <Stack data-testid="row" as="section" direction="row" gap={4} wrap>
        <span>a</span>
      </Stack>,
    );
    const el = screen.getByTestId("row");
    expect(el.tagName).toBe("SECTION");
    expect(el).toHaveAttribute("data-direction", "row");
    expect(el).toHaveAttribute("data-gap", "4");
    expect(el).toHaveAttribute("data-wrap", "true");
    expect(el.getAttribute("style")).toBeNull();
  });

  it("keeps alignment inline, because it is an open set of CSS keywords", () => {
    // align/justify accept any alignment keyword, so they cannot become a rule per value
    // without inventing a vocabulary CSS already has (ADR 0094). They stay inline, and
    // the geometry attributes stay attributes — the two halves of the same element.
    render(
      <Stack data-testid="aligned" align="center" justify="space-between">
        <span>a</span>
      </Stack>,
    );
    const el = screen.getByTestId("aligned");
    expect(el.style.alignItems).toBe("center");
    expect(el.style.justifyContent).toBe("space-between");
    expect(el.style.display).toBe("");
  });

  it("splits a responsive prop into a narrow attribute and a wide one", () => {
    // jsdom evaluates no media query, so the unit-level claim is the attributes and nothing
    // more — which is the honest boundary. That the rules then apply at the right width is a
    // browser fact, held by the `stack-responsive-*` specimen pair at 420 and 900.
    render(
      <Stack
        data-testid="toolbar"
        direction={{ narrow: "column", wide: "row" }}
        gap={{ narrow: 2, wide: 4 }}
      >
        <span>a</span>
      </Stack>,
    );
    const el = screen.getByTestId("toolbar");
    expect(el).toHaveAttribute("data-direction", "column");
    expect(el).toHaveAttribute("data-direction-wide", "row");
    expect(el).toHaveAttribute("data-gap", "2");
    expect(el).toHaveAttribute("data-gap-wide", "4");
    expect(el.getAttribute("style")).toBeNull();
  });

  it("stamps no wide attribute when the prop is not responsive", () => {
    // The back-compatibility claim, asserted as absence: every Stack in every consuming app
    // passes scalars, so it must render exactly the attributes it always did — which is why
    // adding the feature moved no baseline anywhere.
    render(
      <Stack data-testid="plain" direction="row" gap={4}>
        <span>a</span>
      </Stack>,
    );
    const el = screen.getByTestId("plain");
    expect(el).toHaveAttribute("data-direction", "row");
    expect(el).toHaveAttribute("data-gap", "4");
    expect(el.hasAttribute("data-direction-wide")).toBe(false);
    expect(el.hasAttribute("data-gap-wide")).toBe(false);
  });

  it("accepts a responsive gap of 0, which a falsy check would drop", () => {
    // `gap: 0` is a legal step and the only one that is falsy, so a `value.wide || undefined`
    // anywhere in the split would silently render the narrow gap at every width.
    render(
      <Stack data-testid="zero" gap={{ narrow: 4, wide: 0 }}>
        <span>a</span>
      </Stack>,
    );
    expect(screen.getByTestId("zero")).toHaveAttribute("data-gap-wide", "0");
  });

  it("works as a form (submit handler fires)", () => {
    let submitted = false;
    render(
      <Stack
        as="form"
        data-testid="form"
        onSubmit={(event) => {
          event.preventDefault();
          submitted = true;
        }}
      >
        <button type="submit">go</button>
      </Stack>,
    );
    screen.getByText("go").click();
    expect(submitted).toBe(true);
  });
});

describe("Grid", () => {
  it("leaves every default unstamped, because the defaults ARE the base rule", () => {
    // auto columns, the sm track floor and stretched cells are what the base rule declares, so
    // their attributes would describe the standard shape a second time. Same idiom as density's
    // "comfortable" and Button's md — and asserted as absence, deliberately, because a later
    // change that starts stamping them would leave the sheet with two accounts of one default.
    render(
      <Grid data-testid="grid">
        <span>a</span>
      </Grid>,
    );
    const el = screen.getByTestId("grid");
    expect(el.tagName).toBe("DIV");
    expect(el).toHaveAttribute("data-terp", "grid");
    expect(el).toHaveAttribute("data-gap", "4");
    expect(el.hasAttribute("data-columns")).toBe(false);
    expect(el.hasAttribute("data-min-column")).toBe(false);
    expect(el.hasAttribute("data-align")).toBe(false);
    expect(el.getAttribute("style")).toBeNull();
  });

  it("names a fixed count, the element and the gap", () => {
    render(
      <Grid data-testid="grid" as="ul" columns={3} gap={2}>
        <li>a</li>
      </Grid>,
    );
    const el = screen.getByTestId("grid");
    expect(el.tagName).toBe("UL");
    // A number prop, a text attribute: `columns={3}` has to produce "3" or the rule misses.
    expect(el).toHaveAttribute("data-columns", "3");
    expect(el).toHaveAttribute("data-gap", "2");
    expect(el.getAttribute("style")).toBeNull();
  });

  it("names a non-default track floor, and only while the columns are auto", () => {
    // `minColumn` is meaningless at a fixed count — the tracks are counted, not floored — so
    // stamping it there would put an attribute on the element that no rule reads and that a
    // reader would take for an active choice.
    const { rerender } = render(
      <Grid data-testid="grid" minColumn="lg">
        <span>a</span>
      </Grid>,
    );
    expect(screen.getByTestId("grid")).toHaveAttribute("data-min-column", "lg");
    rerender(
      <Grid data-testid="grid" columns={2} minColumn="lg">
        <span>a</span>
      </Grid>,
    );
    const fixed = screen.getByTestId("grid");
    expect(fixed).toHaveAttribute("data-columns", "2");
    expect(fixed.hasAttribute("data-min-column")).toBe(false);
  });

  it("keeps alignment an attribute, unlike Stack's, and takes no style", () => {
    // The deliberate divergence: Stack's align is an open set of CSS keywords and stays inline
    // (ADR 0094 §3); Grid's is a closed four, so it is an attribute and Grid renders no inline
    // style at all. That is what keeps a new primitive out of the inline-style ledger.
    render(
      <Grid data-testid="grid" align="center">
        <span>a</span>
      </Grid>,
    );
    const el = screen.getByTestId("grid");
    expect(el).toHaveAttribute("data-align", "center");
    expect(el.getAttribute("style")).toBeNull();
  });
});

describe("DetailList", () => {
  it("renders label/value pairs as a definition list", () => {
    render(
      <DetailList
        items={[
          { label: "Owner", value: "Ada" },
          { label: { id: "detail.purchased", message: "Purchased" }, value: "2023-01-01" },
        ]}
      />,
    );
    expect(screen.getByText(/Owner/).tagName).toBe("DT");
    expect(screen.getByText("Ada").tagName).toBe("DD");
    expect(screen.getByText(/Purchased/)).toBeInTheDocument();
  });
});
