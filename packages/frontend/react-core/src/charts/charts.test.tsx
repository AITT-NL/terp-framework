// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";

// The pairings the contrast gate measures, read from the contract package that owns them.
import tokenPairs from "../../../contract/token-pairs.json";
import { LOCALE_EN, LOCALE_NL, LocaleProvider } from "../locale";
import { TERP_STYLES_CSS } from "../styles";
import { BarChart } from "./BarChart";
import { ProportionBar } from "./ProportionBar";
import { bandCentre, columnOf, niceStep, valueAxis, xOf, yOf } from "./scale";
import { StatusHistory } from "./StatusHistory";
import { TrendChart } from "./TrendChart";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function renderIn(locale: "nl" | "en", node: ReactNode) {
  return render(
    <LocaleProvider locales={{ nl: LOCALE_NL, en: LOCALE_EN }} defaultLocale={locale}>
      {node}
    </LocaleProvider>,
  );
}

const part = (marker: string) => document.querySelector(`[data-terp="${marker}"]`);
const parts = (marker: string) => [...document.querySelectorAll(`[data-terp="${marker}"]`)];

describe("the value axis", () => {
  it("rounds a step up to 1, 2, 2.5 or 5 times a power of ten", () => {
    expect([0.7, 1, 1.3, 2.2, 3, 7, 12, 260].map((raw) => niceStep(raw))).toEqual([1, 1, 2, 2.5, 5, 10, 20, 500]);
  });

  it("spans the values in two equal round steps, zero kept where a mark's length is its value", () => {
    // Mutation: drop zero from an area's axis, and the axis starts at the lowest value.
    expect(valueAxis([118, 172], true)).toEqual({ low: 0, high: 200, ticks: [200, 100, 0] });
    const line = valueAxis([118, 172], false);
    expect(line.low).toBeGreaterThan(0);
    expect(line.high).toBeGreaterThanOrEqual(172);
    expect(line.ticks[0] - line.ticks[1]).toBe(line.ticks[1] - line.ticks[2]);
  });

  it("gives a flat or empty series an axis with height", () => {
    const flat = valueAxis([5, 5, 5], true);
    expect(flat.high).toBeGreaterThan(flat.low);
    const empty = valueAxis([], false);
    expect(empty.high).toBeGreaterThan(empty.low);
  });

  it("steps an axis of counts in whole numbers", () => {
    // Half a run is no label: a count axis takes 1, 2, 3 or 5 times a power of ten. Mutation:
    // let 2.5 back in, and a maximum of five puts "2.5" -- or "3", rounded -- on the middle line.
    expect([0.4, 1, 1.3, 2.2, 2.6, 4, 7, 26].map((raw) => niceStep(raw, true))).toEqual([1, 1, 2, 3, 3, 5, 10, 30]);
    expect(valueAxis([0, 5], true, true).ticks).toEqual([6, 3, 0]);
    expect(valueAxis([0, 5], true).ticks).toEqual([5, 2.5, 0]);
  });

  it("spans negative values without losing zero", () => {
    const axis = valueAxis([-30, 40], true);
    expect(axis.low).toBeLessThanOrEqual(-30);
    expect(axis.high).toBeGreaterThanOrEqual(40);
    expect(axis.ticks.length).toBe(3);
  });

  it("places points edge to edge, and columns centred in bands of their own", () => {
    expect([0, 1, 2].map((index) => xOf(index, 3))).toEqual([0, 50, 100]);
    expect(columnOf(0, 4)).toEqual({ x: 5, width: 15 });
    expect([0, 3].map((index) => bandCentre(index, 4))).toEqual([12.5, 87.5]);
    expect(yOf(100, { low: 0, high: 200, ticks: [200, 100, 0] })).toBe(20);
  });
});

describe("TrendChart", () => {
  const WEEKS = [
    { label: "W1", value: 120 },
    { label: "W2", value: 140 },
    { label: "W3", value: 180 },
  ];

  it("hides its table through a block, which the visually-hidden rule can shrink", () => {
    // A table's width and height are minimums, so marking the table itself left a full-size box
    // hanging below the chart that stretched the page. Mutation: put the marker back on the
    // <table>, and the hidden part is a table again.
    renderIn("en", <TrendChart label="Rows synced" series={{ label: "This month", points: WEEKS }} />);
    const hidden = part("chart-table")!;
    expect(hidden.tagName).toBe("DIV");
    expect(hidden.children).toHaveLength(1);
    expect(hidden.firstElementChild?.tagName).toBe("TABLE");
  });

  it("is a captioned figure whose picture is hidden and whose data is a table", () => {
    renderIn("en", <TrendChart label="Rows synced" series={{ label: "This month", points: WEEKS }} />);
    const figure = screen.getByRole("figure", { name: "Rows synced" });
    expect(part("chart-body")).toHaveAttribute("aria-hidden", "true");
    // The table is the chart for assistive technology: a row header per period, a value each.
    // Mutation: drop the table, and the figure has nothing behind its caption.
    const table = within(figure).getByRole("table", { name: "Rows synced" });
    expect(within(table).getAllByRole("rowheader").map((cell) => cell.textContent)).toEqual([
      "W1",
      "W2",
      "W3",
    ]);
    expect(within(table).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
      "",
      "120",
      "140",
      "180",
    ]);
  });

  it("draws a line by default, and an area and columns from zero", () => {
    renderIn("en", <TrendChart label="Rows" series={{ label: "Rows", points: WEEKS }} />);
    expect(part("trend-chart-line")).not.toBeNull();
    expect(part("trend-chart-area")).toBeNull();
    cleanup();
    renderIn("en", <TrendChart label="Rows" mark="columns" series={{ label: "Rows", points: WEEKS }} />);
    const columns = parts("trend-chart-column");
    expect(columns).toHaveLength(3);
    // The axis is 0..200, so 180 stands 36 of the plot's 40 units tall.
    expect(columns[2]!.getAttribute("height")).toBe("36");
    expect(columns[2]!.getAttribute("y")).toBe("4");
  });

  it("prints the axis in the app's locale, top to bottom", () => {
    renderIn("nl", (
      <TrendChart
        label="Omzet"
        mark="area"
        format={{ style: "currency", currency: "EUR", maximumFractionDigits: 0 }}
        series={{ label: "Omzet", points: [{ label: "jan", value: 1500 }, { label: "feb", value: 3800 }] }}
      />
    ));
    expect([...part("chart-axis")!.children].map((tick) => tick.textContent)).toEqual([
      "€ 4.000",
      "€ 2.000",
      "€ 0",
    ]);
  });

  it("names the comparison in a legend and in the table, and draws it dashed behind the series", () => {
    renderIn("en", (
      <TrendChart
        label="Rows"
        series={{ label: "This month", points: WEEKS }}
        comparison={{ label: "Last month", points: [{ label: "W1", value: 100 }, { label: "W2", value: 90 }, { label: "W3", value: 130 }] }}
      />
    ));
    expect(parts("chart-legend-item").map((item) => item.textContent)).toEqual(["This month", "Last month"]);
    expect(part("trend-chart-comparison")).not.toBeNull();
    expect(
      within(screen.getByRole("table")).getAllByRole("columnheader").map((cell) => cell.textContent),
    ).toEqual(["This month", "Last month"]);
  });

  it("leaves a gap where a value is not a number, and prints the dash for it", () => {
    renderIn("en", (
      <TrendChart
        label="Rows"
        series={{ label: "Rows", points: [WEEKS[0]!, { label: "W2", value: Number.NaN }, WEEKS[2]!] }}
      />
    ));
    // The line breaks at W2 rather than inventing it, leaving a point on each side with no
    // neighbour, on a line's axis of counts from 120 to 180. A one-point polyline is never
    // stroked, so each is a dot: a zero-length stroke the sheet caps round. Mutation: draw them
    // as lines, and the plot is blank.
    expect(parts("trend-chart-line")).toHaveLength(0);
    expect(parts("trend-chart-dot").map((dot) => dot.getAttribute("points"))).toEqual([
      "0,40 0,40",
      "100,0 100,0",
    ]);
    expect(within(screen.getByRole("table")).getAllByRole("cell")[2]!.textContent).toBe("—");
  });

  it("draws a series of one point as a dot in the middle, its label under it", () => {
    renderIn("en", <TrendChart label="Rows" series={{ label: "Rows", points: [{ label: "Today", value: 40 }] }} />);
    expect(part("trend-chart-dot")!.getAttribute("points")).toMatch(/^50,[\d.]+ 50,[\d.]+$/);
    expect([...part("chart-labels")!.children].map((label) => label.textContent)).toEqual(["Today"]);
  });

  it("prints a line's middle label only where a point stands under it", () => {
    // The labels stand at the ends and the centre of the plot; with an even number of points no
    // point is at the centre. Mutation: print the middle anyway, and six weeks label week 3 at
    // the place between weeks 3 and 4.
    const weeks = (count: number) =>
      Array.from({ length: count }, (_, index) => ({ label: `P${index + 1}`, value: index }));
    const printed = () => [...part("chart-labels")!.children].map((label) => label.textContent);
    renderIn("en", <TrendChart label="Rows" series={{ label: "Rows", points: weeks(6) }} />);
    expect(printed()).toEqual(["P1", "P6"]);
    cleanup();
    renderIn("en", <TrendChart label="Rows" series={{ label: "Rows", points: weeks(7) }} />);
    expect(printed()).toEqual(["P1", "P4", "P7"]);
  });

  it("places a comparison on the series' own scale, point for point, and lists every point", () => {
    // A month so far against a whole month: point i of both stands at the same x, so the
    // current one stops short. Mutation: scale each series to itself, and both reach the edge.
    renderIn("en", (
      <TrendChart
        label="Rows"
        series={{ label: "This month", points: [{ label: "A", value: 10 }, { label: "B", value: 20 }] }}
        comparison={{
          label: "Last month",
          points: ["a", "b", "c", "d"].map((label, index) => ({ label, value: 5 * (index + 1) })),
        }}
      />
    ));
    const xs = (marker: string) =>
      part(marker)!.getAttribute("points")!.split(" ").map((point) => Number(point.split(",")[0]));
    expect(xs("trend-chart-line")).toEqual([0, 33.33]);
    expect(xs("trend-chart-comparison")).toEqual([0, 33.33, 66.67, 100]);
    // The table pairs the two by index and lists the longer one whole, the dash where the
    // series has no point yet.
    const table = screen.getByRole("table", { name: "Rows" });
    expect(within(table).getAllByRole("rowheader").map((cell) => cell.textContent)).toEqual(["A", "B", "c", "d"]);
    expect(within(table).getAllByRole("cell").slice(1).map((cell) => cell.textContent)).toEqual([
      "10", "5", "20", "10", "—", "15", "—", "20",
    ]);
  });

  it("bends a comparison over columns at their centres, drawn over them", () => {
    renderIn("en", (
      <TrendChart
        label="Runs"
        mark="columns"
        series={{ label: "This week", points: [1, 2, 3, 4].map((value) => ({ label: `D${value}`, value })) }}
        comparison={{ label: "Last week", points: [2, 2, 2, 2].map((value, index) => ({ label: `D${index + 1}`, value })) }}
      />
    ));
    const comparison = part("trend-chart-comparison")!;
    expect(comparison.getAttribute("points")!.split(" ").map((point) => Number(point.split(",")[0]))).toEqual([
      12.5, 37.5, 62.5, 87.5,
    ]);
    // After the columns in the drawing, so the opaque columns do not hide it.
    const plot = [...part("chart-plot")!.children].map((child) => child.getAttribute("data-terp"));
    expect(plot.lastIndexOf("trend-chart-column")).toBeLessThan(plot.indexOf("trend-chart-comparison"));
  });

  it("steps the axis of a series of counts in whole numbers", () => {
    renderIn("en", (
      <TrendChart
        label="Runs"
        mark="columns"
        series={{ label: "Runs", points: [1, 5, 3].map((value, index) => ({ label: `D${index}`, value })) }}
      />
    ));
    expect([...part("chart-axis")!.children].map((tick) => tick.textContent)).toEqual(["6", "3", "0"]);
  });

  it("prints a column chart's labels under each column, the ones not printed holding their place", () => {
    const many = Array.from({ length: 7 }, (_, index) => ({ label: `D${index + 1}`, value: index }));
    renderIn("en", <TrendChart label="Runs" mark="columns" series={{ label: "Runs", points: many }} />);
    const labels = [...part("chart-labels")!.children];
    expect(labels).toHaveLength(7);
    expect(labels.filter((label) => !label.hasAttribute("data-quiet")).map((label) => label.textContent)).toEqual([
      "D1",
      "D4",
      "D7",
    ]);
  });
});

describe("BarChart", () => {
  it("is a table of its categories, each bar scaled to the largest", () => {
    // The chart is its own table: a row header per category, the bar hidden, the value printed.
    renderIn("en", (
      <BarChart
        label="Rows by source"
        bars={[
          { label: "Customers", value: 1200 },
          { label: "Orders", value: 600 },
          { label: "Stock", value: 0 },
        ]}
      />
    ));
    const figure = screen.getByRole("figure", { name: "Rows by source" });
    expect(within(figure).getAllByRole("rowheader").map((cell) => cell.textContent)).toEqual([
      "Customers",
      "Orders",
      "Stock",
    ]);
    expect(parts("bar-chart-value").map((cell) => cell.textContent)).toEqual(["1,200", "600", "0"]);
    // Mutation: scale each bar to itself, and every bar is full.
    expect(parts("bar-chart-mark").map((mark) => mark.getAttribute("width"))).toEqual(["100", "50", "0"]);
  });

  it("names its table by the caption, and hides the bar's cell rather than reading it as blank", () => {
    renderIn("en", <BarChart label="Rows by source" bars={[{ label: "Customers", value: 1200 }]} />);
    // Mutation: drop the table's name, or read the bar cell, and a row reads "Customers, blank, 1,200".
    expect(screen.getByRole("table", { name: "Rows by source" })).toBeInTheDocument();
    expect(part("bar-chart-bar")).toHaveAttribute("aria-hidden", "true");
    // The name sits in a box of its own, which is what the sheet caps at a third of the chart.
    expect(part("bar-chart-name")!.textContent).toBe("Customers");
  });

  it("scales to a declared max, and draws no bar for a value that is not a number", () => {
    renderIn("en", (
      <BarChart label="Load" max={2000} bars={[{ label: "A", value: 500 }, { label: "B", value: Number.NaN }]} />
    ));
    expect(parts("bar-chart-mark").map((mark) => mark.getAttribute("width"))).toEqual(["25", "0"]);
    expect(parts("bar-chart-value")[1]!.textContent).toBe("—");
  });
});

describe("ProportionBar", () => {
  const RUN = [
    { label: "Created", value: 30, tone: "success" as const },
    { label: "Updated", value: 60, tone: "info" as const },
    { label: "Failed", value: 10, tone: "danger" as const },
  ];

  it("lays the parts along one bar by their shares, parted by hairlines", () => {
    renderIn("en", <ProportionBar label="Last run" parts={RUN} />);
    expect(parts("proportion-bar-part").map((rect) => [rect.getAttribute("x"), rect.getAttribute("width")])).toEqual([
      ["0", "30"],
      ["30", "60"],
      ["90", "10"],
    ]);
    expect(parts("proportion-bar-gap")).toHaveLength(2);
    expect(part("proportion-bar-track")).toHaveAttribute("aria-hidden", "true");
  });

  it("says every part in words: its name, its count and its share", () => {
    // A tone is always also a word: the legend is the chart's data. Mutation: drop the share,
    // and "10%" is never printed.
    renderIn("nl", <ProportionBar label="Laatste run" parts={RUN} />);
    // A space between the name and the count, or a screen reader says "Created30".
    expect(parts("chart-legend-item").map((item) => item.textContent)).toEqual([
      "Created 30 · 30%",
      "Updated 60 · 60%",
      "Failed 10 · 10%",
    ]);
  });

  it("takes the chart colours in order for parts without a tone, and no share from a part that is not positive", () => {
    renderIn("en", (
      <ProportionBar
        label="Sources"
        parts={[
          { label: "A", value: 3 },
          { label: "B", value: 1 },
          { label: "C", value: -2 },
        ]}
      />
    ));
    expect(parts("proportion-bar-part").map((rect) => rect.getAttribute("data-series"))).toEqual(["1", "2"]);
    expect(parts("chart-legend-value").map((value) => value.textContent)).toEqual(["3 · 75%", "1 · 25%", "-2 · 0%"]);
  });
});

describe("StatusHistory", () => {
  const SUCCEEDED = { label: "Succeeded", tone: "success" as const };
  const FAILED = { label: "Failed", tone: "danger" as const };
  const RUNS = [
    { label: "Mon", outcome: SUCCEEDED },
    { label: "Tue", outcome: FAILED },
    { label: "Wed", outcome: SUCCEEDED },
  ];

  it("draws a cell per run in its tone, and prints the latest ending", () => {
    renderIn("en", <StatusHistory label="Runs" runs={RUNS} />);
    expect(parts("status-history-cell").map((cell) => cell.getAttribute("data-tone"))).toEqual([
      "success",
      "danger",
      "success",
    ]);
    expect(part("status-history-latest")!.textContent).toBe("Succeeded");
    expect(part("status-history-cells")).toHaveAttribute("aria-hidden", "true");
  });

  it("reads every run out, its label and its ending, oldest first", () => {
    // Mutation: drop the text, and the cells' colours say it to nobody who cannot see them.
    renderIn("nl", <StatusHistory label="Runs" runs={RUNS} />);
    expect(part("status-history-data")!.textContent).toBe(
      "Runs, oudste eerst: Mon: Succeeded, Tue: Failed en Wed: Succeeded",
    );
  });

  it("renders nothing for no runs, rather than a sentence that stops at its colon", () => {
    const { container } = renderIn("en", <StatusHistory label="Runs" runs={[]} />);
    expect(container.textContent).toBe("");
  });

  it("is phrasing content, so it can sit in a link or a cell", () => {
    renderIn("en", <StatusHistory label="Runs" runs={RUNS} />);
    const tags = [part("status-history")!, ...part("status-history")!.querySelectorAll("*")].map(
      (element) => element.tagName.toLowerCase(),
    );
    expect(tags.every((tag) => tag === "span")).toBe(true);
  });
});

describe("the charts' colours are declared pairings", () => {
  const declared = (fg: string, bg: string) =>
    [...tokenPairs.textPairs, ...tokenPairs.nonTextPairs].some(
      (pair) => "fg" in pair && pair.fg === fg && pair.bg === bg,
    );

  it("holds every chart colour the sheet paints to 3:1 against the surface", () => {
    // The chart ramp only: every chart colour the sheet paints has its pairing on the surface.
    // Mutation: drop one of those pairings, and this names it.
    const painted = new Set(
      [...TERP_STYLES_CSS.matchAll(/(?:fill|background|stroke): var\((--color-chart-[1-5])\)/g)].map(
        (match) => match[1]!,
      ),
    );
    expect([...painted].sort()).toEqual([
      "--color-chart-1",
      "--color-chart-2",
      "--color-chart-3",
      "--color-chart-4",
      "--color-chart-5",
    ]);
    for (const token of painted) {
      expect(declared(token, "--color-bg-surface"), `${token} on the surface`).toBe(true);
    }
  });
});
