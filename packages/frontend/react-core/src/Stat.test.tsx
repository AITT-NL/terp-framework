// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";

// The pairings the contrast gate measures, read from the contract package that owns them.
import tokenPairs from "../../contract/token-pairs.json";
import { HubCard, HubPage } from "./HubPage";
import { LOCALE_EN, LOCALE_NL, LocaleProvider } from "./locale";
import { Stat, StatGroup } from "./Stat";
import { TERP_STYLES_CSS } from "./styles";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

/** Render under a fixed app locale, so a formatting assertion never depends on the runner's. */
function renderIn(locale: "nl" | "en", node: ReactNode) {
  return render(
    <LocaleProvider locales={{ nl: LOCALE_NL, en: LOCALE_EN }} defaultLocale={locale}>
      {node}
    </LocaleProvider>,
  );
}

const part = (marker: string) => document.querySelector(`[data-terp="${marker}"]`);

describe("Stat's figure", () => {
  it("prints its label and a numeric value in the app's locale", () => {
    renderIn("nl", <Stat label="Open orders" value={1284.5} />);
    expect(part("stat-label")!.textContent).toBe("Open orders");
    expect(part("stat-value")!.textContent).toBe("1.284,5");
    cleanup();
    renderIn("en", <Stat label="Open orders" value={1284.5} />);
    expect(part("stat-value")!.textContent).toBe("1,284.5");
  });

  it("formats with the options it is given", () => {
    renderIn("en", <Stat label="Spend" value={842} format={{ style: "currency", currency: "EUR" }} />);
    expect(part("stat-value")!.textContent).toBe("€842.00");
  });

  it("prints a string as written, and the dash for a figure not known yet", () => {
    renderIn("en", <Stat label="Uptime" value="3 d 4 h" />);
    expect(part("stat-value")!.textContent).toBe("3 d 4 h");
    cleanup();
    for (const value of [null, undefined, ""] as const) {
      renderIn("en", <Stat label="Uptime" value={value} />);
      expect(part("stat-value")!.textContent).toBe("—");
      cleanup();
    }
  });

  it("stamps the headline only when asked", () => {
    // The page frame counts [data-terp="stat"][data-headline]; a stamp on every figure would
    // make every page with two figures fail closed.
    renderIn("en", <Stat label="Revenue" value={1} />);
    expect(part("stat")).not.toHaveAttribute("data-headline");
    cleanup();
    renderIn("en", <Stat label="Revenue" value={1} headline />);
    expect(part("stat")).toHaveAttribute("data-headline", "true");
  });

  it("prints a caption, and renders no empty line for an absent one", () => {
    renderIn("en", <Stat label="Spend" value={842} caption="of 1,200 budgeted" />);
    expect(part("stat-caption")!.textContent).toBe("of 1,200 budgeted");
    cleanup();
    for (const caption of [undefined, null, false, ""] as const) {
      renderIn("en", <Stat label="Spend" value={842} caption={caption} />);
      expect(part("stat-caption")).toBeNull();
      cleanup();
    }
  });
});

describe("Stat's delta", () => {
  it("prints the change with its sign, in the change's own format", () => {
    renderIn("en", (
      <Stat
        label="Orders"
        value={1284}
        delta={{ value: 0.12, sentiment: "positive", format: { style: "percent" } }}
      />
    ));
    // The sign is printed even when the caller's format says nothing about it.
    expect(part("stat-change")!.textContent).toBe("+12% favourable");
    cleanup();
    renderIn("en", <Stat label="Orders" value={1284} delta={{ value: -3, sentiment: "negative" }} />);
    expect(part("stat-change")!.textContent).toBe("-3 unfavourable");
  });

  it("colours by the declared sentiment, never by the sign", () => {
    // More rejections is up and bad: the caller says so, and the pill follows the caller.
    renderIn("en", (
      <Stat label="Rejections" value={40} delta={{ value: 6, sentiment: "negative" }} />
    ));
    expect(part("stat-change")).toHaveAttribute("data-sentiment", "negative");
    expect(part("stat-arrow")!.querySelector("path")!.getAttribute("d")).toBe("M6 2 L11 10 L1 10 Z");
  });

  it("points the arrow by the sign, and draws a bar for no change", () => {
    const arrows: Record<string, string> = {};
    for (const [name, value] of [["up", 2], ["down", -2], ["flat", 0]] as const) {
      renderIn("en", <Stat label="Runs" value={9} delta={{ value, sentiment: "neutral" }} />);
      arrows[name] = part("stat-arrow")!.querySelector("path")!.getAttribute("d")!;
      cleanup();
    }
    expect(new Set(Object.values(arrows)).size).toBe(3);
    expect(arrows.flat).toBe("M1 5 H11 V7 H1 Z");
  });

  it("says the sentiment as a word, and says nothing for a neutral change", () => {
    // A tone is always also a word (ADR 0169 §7): the pill's colour is read out after the
    // change. Mutation: drop the word, and a screen reader hears "+12%" with no judgement.
    renderIn("nl", (
      <Stat label="Orders" value={1284} delta={{ value: 12, sentiment: "positive" }} />
    ));
    expect(part("stat-sentiment")!.textContent).toBe(" gunstig");
    cleanup();
    renderIn("nl", <Stat label="Orders" value={1284} delta={{ value: 12, sentiment: "negative" }} />);
    expect(part("stat-sentiment")!.textContent).toBe(" ongunstig");
    cleanup();
    renderIn("nl", <Stat label="Orders" value={1284} delta={{ value: 12, sentiment: "neutral" }} />);
    expect(part("stat-sentiment")).toBeNull();
  });

  it("follows the change as it prints: a change that rounds to zero is no change", () => {
    // 0.004 as a whole percentage prints "0%"; an up arrow, a green pill and "favourable" beside
    // "0%" contradicted the number they decorate. Mutation: take the direction from the raw
    // value again, and the arrow points up.
    renderIn("en", (
      <Stat
        label="Orders"
        value={1}
        delta={{ value: 0.004, sentiment: "positive", format: { style: "percent" } }}
      />
    ));
    expect(part("stat-change")!.textContent).toBe("0%");
    expect(part("stat-change")).toHaveAttribute("data-sentiment", "neutral");
    expect(part("stat-arrow")!.querySelector("path")!.getAttribute("d")).toBe("M1 5 H11 V7 H1 Z");
  });

  it("keeps the sign over a format that asks to hide it", () => {
    // Mutation: spread the caller's format last, and "never" wins.
    renderIn("en", (
      <Stat label="Orders" value={1} delta={{ value: 5, sentiment: "positive", format: { signDisplay: "never" } }} />
    ));
    expect(part("stat-change")!.textContent).toBe("+5 favourable");
  });

  it("hides the arrow from assistive technology, which hears the sign instead", () => {
    renderIn("en", <Stat label="Orders" value={1} delta={{ value: 1, sentiment: "positive" }} />);
    expect(part("stat-arrow")).toHaveAttribute("aria-hidden", "true");
  });

  it("prints what the change is measured against", () => {
    renderIn("en", (
      <Stat
        label="Orders"
        value={1284}
        delta={{ value: 12, sentiment: "positive", label: "vs last week" }}
      />
    ));
    expect(part("stat-delta-label")!.textContent).toBe("vs last week");
  });
});

describe("Stat's trend", () => {
  const WEEK = [
    { label: "Mon", value: 10 },
    { label: "Tue", value: 30 },
    { label: "Wed", value: 20 },
  ];

  it("draws the series as SVG geometry, highest at the top", () => {
    renderIn("en", <Stat label="Runs" value={20} trend={WEEK} />);
    const line = part("stat-trend-line")!;
    // x spreads the points across 100, y maps 10..30 onto 22..2 (the canvas less its inset).
    expect(line.getAttribute("points")).toBe("0,22 50,2 100,12");
    expect(part("stat-trend-area")!.getAttribute("points")).toBe("0,24 0,22 50,2 100,12 100,24");
    expect(part("stat-trend-chart")).toHaveAttribute("aria-hidden", "true");
    // Geometry, not style: nothing here is an inline style (ADR 0169 §7).
    expect(part("stat")!.querySelector("[style]")).toBeNull();
  });

  it("draws a flat series through the middle rather than along the floor", () => {
    renderIn("en", <Stat label="Runs" value={5} trend={[{ label: "a", value: 5 }, { label: "b", value: 5 }]} />);
    expect(part("stat-trend-line")!.getAttribute("points")).toBe("0,12 100,12");
  });

  it("reads every point out, label and value, in the app's locale", () => {
    // ADR 0158's data alternative, as text because a figure is phrasing content throughout.
    // Mutation: drop the text, and the sparkline is a picture with nothing behind it.
    renderIn("nl", (
      <Stat
        label="Omzet"
        value={1500}
        trend={[{ label: "jan", value: 1200.5 }, { label: "feb", value: 1500 }]}
      />
    ));
    expect(part("stat-trend-data")!.textContent).toBe("Verloop: jan: 1.200,5 en feb: 1.500");
  });

  it("reads a series out as a sentence in English too, each point's label set off from its value", () => {
    // Intl's narrow unit list joins English with bare spaces, so "Mon 10 Tue 30 Wed 20" read as
    // one run of words and numbers. Mutation: go back to the narrow unit list, and this fails.
    renderIn("en", <Stat label="Runs" value={20} trend={WEEK} />);
    expect(part("stat-trend-data")!.textContent).toBe("Over time: Mon: 10, Tue: 30, and Wed: 20");
  });

  it("reads out a single point without drawing a line, or a block, for it", () => {
    // As the only child of the trend's own block, the hidden text left that block's margin
    // behind as an empty line. Mutation: keep the block for one point, and it is found.
    renderIn("en", <Stat label="Runs" value={5} trend={[{ label: "Mon", value: 5 }]} />);
    expect(part("stat-trend-chart")).toBeNull();
    expect(part("stat-trend")).toBeNull();
    expect(part("stat-trend-data")!.textContent).toBe("Over time: Mon: 5");
  });

  it("draws only the points that are numbers, and prints the dash for one that is not", () => {
    // A NaN in the points attribute is a console error and no line at all.
    // Mutation: draw every value, and the points carry a NaN.
    renderIn("en", (
      <Stat
        label="Runs"
        value={3}
        trend={[
          { label: "a", value: 1 },
          { label: "b", value: Number.NaN },
          { label: "c", value: 3 },
        ]}
      />
    ));
    expect(part("stat-trend-line")!.getAttribute("points")).toBe("0,22 100,2");
    expect(part("stat-trend-data")!.textContent).toBe("Over time: a: 1, b: —, and c: 3");
  });

  it("renders no trend at all for an empty series", () => {
    renderIn("en", <Stat label="Runs" value={5} trend={[]} />);
    expect(part("stat-trend")).toBeNull();
  });
});

describe("Stat's target", () => {
  it("draws the figure against its range as a Meter named by the figure's label", () => {
    renderIn("en", <Stat label="Spend" value={600} target={{ max: 1200, high: 1000, optimum: 0 }} />);
    expect(screen.getByRole("meter", { name: "Spend" })).toHaveAttribute("aria-valuetext", "50%");
  });

  it("draws no meter for a figure that is not a number", () => {
    renderIn("en", <Stat label="Spend" value={null} target={{ max: 1200 }} />);
    expect(screen.queryByRole("meter")).toBeNull();
  });
});

describe("Stat as phrasing content", () => {
  it("renders only phrasing elements, so it is valid inside a HubCard's link", () => {
    // A HubCard is one link whose body is spans; a block element inside it is invalid HTML.
    // Mutation: render the root as a div, and this fails.
    renderIn("en", (
      <Stat
        label="Spend"
        value={600}
        delta={{ value: 1, sentiment: "positive", label: "vs last week" }}
        trend={[{ label: "a", value: 1 }, { label: "b", value: 2 }]}
        target={{ max: 1200 }}
        caption="of 1,200"
      />
    ));
    const PHRASING = new Set(["span", "svg", "path", "polyline", "polygon", "meter"]);
    const tags = [part("stat")!, ...part("stat")!.querySelectorAll("*")].map((element) =>
      element.tagName.toLowerCase(),
    );
    expect(tags.filter((tag) => !PHRASING.has(tag))).toEqual([]);
  });

  it("sits in a HubCard's stat row and names the card's link with the figure", () => {
    renderIn("en", (
      <HubPage title="Admin">
        <HubCard to="/users" title="Users" stat={<Stat label="Total" value={1420} />} />
      </HubPage>
    ));
    expect(screen.getByRole("link").textContent).toContain("Total1,420");
  });
});

describe("StatGroup", () => {
  it("renders its figures in one group", () => {
    renderIn("en", (
      <StatGroup>
        <Stat label="A" value={1} />
        <Stat label="B" value={2} />
      </StatGroup>
    ));
    expect(part("stat-group")!.querySelectorAll(':scope > [data-terp="stat"]')).toHaveLength(2);
  });
});

describe("Stat's colours are declared pairings", () => {
  /** The declarations of the one rule whose selector is exactly *selector*. */
  function rule(selector: string): string {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = new RegExp(`(?:^|\\n)${escaped} \\{([^}]*)\\}`).exec(TERP_STYLES_CSS);
    expect(match, `no rule for ${selector}`).not.toBeNull();
    return match![1]!;
  }
  const declared = (fg: string, bg: string) =>
    [...tokenPairs.textPairs, ...tokenPairs.nonTextPairs].some(
      (pair) => "fg" in pair && pair.fg === fg && pair.bg === bg,
    );

  it("draws each delta pill in a pairing the contrast gate holds", () => {
    // The pill carries its own fill so its contrast travels with it onto a band, a card or the
    // headline. Mutation: colour the positive pill's ink with the accent, and no pairing
    // holds it.
    for (const sentiment of ["positive", "negative", "neutral"]) {
      const body = rule(`[data-terp="stat-change"][data-sentiment="${sentiment}"]`);
      const fg = /(?<![-\w])color: var\((--[a-z0-9-]+)\)/.exec(body)![1]!;
      const bg = /(?<![-\w])background: var\((--[a-z0-9-]+)\)/.exec(body)![1]!;
      expect(declared(fg, bg), `${sentiment}: ${fg} on ${bg}`).toBe(true);
    }
  });

  it("fills the headline with the brand and its contrast ink, the primary button's pairing", () => {
    const body = rule('[data-terp="stat"][data-headline]');
    const fg = /(?<![-\w])color: var\((--[a-z0-9-]+)\)/.exec(body)![1]!;
    const bg = /(?<![-\w])background: var\((--[a-z0-9-]+)\)/.exec(body)![1]!;
    expect(declared(fg, bg)).toBe(true);
  });

  it("writes the summary band's text in inks declared against its fill", () => {
    const body = rule('[data-terp="page-summary"]');
    const bg = /(?<![-\w])background: var\((--[a-z0-9-]+)\)/.exec(body)![1]!;
    expect(bg).toBe("--color-bg-summary");
    // The band's own ink, and the two a figure writes on it.
    for (const fg of ["--color-fg-default", "--color-fg-muted", "--color-fg-accent"]) {
      expect(declared(fg, bg), `${fg} on ${bg}`).toBe(true);
    }
  });
});
