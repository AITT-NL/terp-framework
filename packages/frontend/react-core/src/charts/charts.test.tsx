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
import { columnOf, niceStep, valueAxis, xOf, yOf } from "./scale";
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
    expect([0.7, 1, 1.3, 2.2, 3, 7, 12, 260].map(niceStep)).toEqual([1, 1, 2, 2.5, 5, 10, 20, 500]);
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

  it("spans negative values without losing zero", () => {
    const axis = valueAxis([-30, 40], true);
    expect(axis.low).toBeLessThanOrEqual(-30);
    expect(axis.high).toBeGreaterThanOrEqual(40);
    expect(axis.ticks.length).toBe(3);
  });

  it("places points edge to edge, and columns centred in bands of their own", () => {
    expect([0, 1, 2].map((index) => xOf(index, 3))).toEqual([0, 50, 100]);
    expect(columnOf(0, 4)).toEqual({ x: 5, width: 15 });
    expect(yOf(100, { low: 0, high: 200, ticks: [200, 100, 0] })).toBe(20);
  });
});

describe("TrendChart", () => {
  const WEEKS = [
    { label: "W1", value: 120 },
    { label: "W2", value: 140 },
    { label: "W3", value: 180 },
  ];

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
    // The line breaks at W2 rather than inventing it: two runs, one point each, on a line's
    // axis of 100 to 200 -- a line's axis keeps the change visible rather than starting at zero.
    expect(parts("trend-chart-line").map((line) => line.getAttribute("points"))).toEqual([
      "0,32",
      "100,8",
    ]);
    expect(within(screen.getByRole("table")).getAllByRole("cell")[2]!.textContent).toBe("—");
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
    expect(parts("chart-legend-item").map((item) => item.textContent)).toEqual([
      "Created30 · 30%",
      "Updated60 · 60%",
      "Failed10 · 10%",
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
    // Mutation: paint a mark in a colour no pairing declares, and this names it.
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
