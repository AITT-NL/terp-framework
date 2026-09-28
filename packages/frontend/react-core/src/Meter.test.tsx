// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { Component } from "react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";

// The pairings the contrast gate measures, read from the contract package that owns them.
import tokenPairs from "../../contract/token-pairs.json";
import { DetailPage } from "./DetailPage";
import { DetailList } from "./layout";
import { LayoutContractContext, slotViolationMessage } from "./layoutContract";
import { LOCALE_EN, LOCALE_NL, LocaleProvider } from "./locale";
import { Meter } from "./Meter";
import type { MeterProps } from "./Meter";
import { TERP_STYLES_CSS } from "./styles";
import { Card } from "./ui/Card";

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

const meterOf = () => document.querySelector("meter")!;
const printed = () => document.querySelector('[data-terp="meter-value"]')!.textContent;

describe("Meter's name and value", () => {
  it("is named by its label, which it does not print", () => {
    // The name is what a screen reader says the number measures; without it a meter is
    // announced as a bare value. Not printed, because the caption beside it already is.
    renderIn("en", <Meter label="Storage" value={0.62} />);
    expect(screen.getByRole("meter", { name: "Storage" })).toBe(meterOf());
    expect(document.querySelector('[data-terp="meter"]')!.textContent).toBe("62%");
  });

  it("prints the value in the app's locale, and announces exactly what it prints", () => {
    // A value with a decimal is the one that tells the locales apart: nl writes the comma.
    const format = { style: "percent", maximumFractionDigits: 1 } as const;
    renderIn("nl", <Meter label="Opslag" value={0.625} format={format} />);
    expect(printed()).toBe("62,5%");
    expect(meterOf().getAttribute("aria-valuetext")).toBe("62,5%");
    cleanup();
    renderIn("en", <Meter label="Storage" value={0.625} format={format} />);
    expect(printed()).toBe("62.5%");
    expect(meterOf().getAttribute("aria-valuetext")).toBe("62.5%");
  });

  it("hands the printed value to the meter and hides the copy, so it is one element", () => {
    // Measured in Chromium: a meter inside a HubCard's link adds its value text to the link's
    // name, so with the printed copy left in the tree the link read its value twice.
    renderIn("en", <Meter label="Storage" value={0.62} />);
    expect(document.querySelector('[data-terp="meter-value"]')).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(screen.getAllByRole("meter")).toHaveLength(1);
  });
});

describe("what Meter prints", () => {
  it("prints a percentage as the share of the range, never Intl's hundredfold", () => {
    renderIn("en", <Meter label="Score" value={74} max={100} />);
    expect(printed(), "74 of 100 is 74%, where the bare Intl option says 7,400%").toBe("74%");
    cleanup();
    renderIn("en", <Meter label="Score" value={30} min={20} max={70} />);
    expect(printed(), "and the share is measured from min, not from zero").toBe("20%");
  });

  it("prints the value itself for any other style", () => {
    renderIn(
      "nl",
      <Meter
        label="Opslag"
        value={7.4}
        max={10}
        format={{ style: "unit", unit: "gigabyte", maximumFractionDigits: 1 }}
      />,
    );
    expect(printed()).toBe("7,4 GB");
    cleanup();
    renderIn("en", <Meter label="Score" value={72} max={100} format={{}} />);
    expect(printed(), "an empty format is a plain number").toBe("72");
  });

  it("prints an overrun as it is, while the element clamps the bar", () => {
    // The text is where a reader learns the bar has run out of room, so it is never clamped.
    renderIn("en", <Meter label="Storage" value={12} max={10} />);
    expect(printed()).toBe("120%");
    expect(meterOf().getAttribute("value"), "the element gets the real value to clamp").toBe("12");
  });

  it("prints the framework's dash for a range with no width, never an infinity", () => {
    // Chromium paints no fill for either shape (measured), and the division would print
    // "∞%" for the second.
    renderIn("en", <Meter label="Storage" value={5} min={5} max={5} />);
    expect(printed()).toBe("—");
    cleanup();
    renderIn("en", <Meter label="Storage" value={0.5} min={1} max={0.5} />);
    expect(printed()).toBe("—");
  });
});

type Case = Pick<MeterProps, "value" | "min" | "max" | "low" | "high" | "optimum"> & {
  region: "optimum" | "suboptimum" | "even-less-good";
};

/**
 * The region Chromium itself paints, per case — read off a rendered meter whose three value
 * pseudo-elements were given three different colours, not derived from the standard's prose.
 *
 * Chosen to make every boundary observable: each value sitting exactly ON a band edge, a band
 * declared outside the range, and a `high` below `low` with the optimum ABOVE the bands, which
 * is the one shape where clamping `high` up to `low` changes the answer (without it, 0.5 is
 * read as optimum; Chromium paints it even-less-good).
 */
const CHROMIUM_REGIONS: Case[] = [
  { low: 0.3, high: 0.7, optimum: 0.1, value: 0.3, region: "optimum" },
  { low: 0.3, high: 0.7, optimum: 0.1, value: 0.5, region: "suboptimum" },
  { low: 0.3, high: 0.7, optimum: 0.1, value: 0.7, region: "suboptimum" },
  { low: 0.3, high: 0.7, optimum: 0.1, value: 0.9, region: "even-less-good" },
  { low: 0.3, high: 0.7, optimum: 0.1, value: 1.5, region: "even-less-good" },
  { low: 0.3, high: 0.7, optimum: 0.9, value: 0.2, region: "even-less-good" },
  { low: 0.3, high: 0.7, optimum: 0.9, value: 0.3, region: "suboptimum" },
  { low: 0.3, high: 0.7, optimum: 0.9, value: 0.7, region: "optimum" },
  { low: 0.3, high: 0.7, optimum: 0.5, value: 0.2, region: "suboptimum" },
  { low: 0.3, high: 0.7, optimum: 0.5, value: 0.3, region: "optimum" },
  { low: 0.3, high: 0.7, optimum: 0.5, value: 0.7, region: "optimum" },
  { low: 0.3, high: 0.7, optimum: 0.5, value: 0.9, region: "suboptimum" },
  { low: 0.3, high: 0.7, optimum: 0.3, value: 0.2, region: "suboptimum" },
  { low: 0.3, high: 0.7, optimum: 0.7, value: 0.9, region: "suboptimum" },
  { low: 0.3, value: 0.2, region: "suboptimum" },
  { low: 0.3, value: 0.3, region: "optimum" },
  { high: 0.7, value: 0.9, region: "suboptimum" },
  { optimum: 0.1, value: 0.9, region: "optimum" },
  { low: -1, high: 5, optimum: 0.1, value: 0.9, region: "optimum" },
  { low: 0.8, high: 0.3, optimum: 0.1, value: 0.9, region: "even-less-good" },
  { low: 0.8, high: 0.3, optimum: 0.9, value: 0.5, region: "even-less-good" },
  { low: 0.8, high: 0.3, optimum: 0.9, value: 0.8, region: "optimum" },
  { min: 20, max: 70, low: 30, high: 60, optimum: 25, value: 30, region: "optimum" },
  { min: 20, max: 70, low: 30, high: 60, optimum: 25, value: 60, region: "suboptimum" },
  { min: 20, max: 70, low: 30, high: 60, optimum: 25, value: 65, region: "even-less-good" },
  { min: 20, max: 70, low: 30, high: 60, optimum: 65, value: 25, region: "even-less-good" },
  { min: 20, max: 70, low: 30, high: 60, optimum: 65, value: 60, region: "optimum" },
];

describe("Meter's bands", () => {
  it("stamps no region when no band is declared", () => {
    // Unbanded, the browser still files every value under "optimum" (measured) — so a region
    // stamped here would paint a bare quota in the success tone, a judgement nobody made.
    renderIn("en", <Meter label="Storage" value={0.95} />);
    expect(meterOf().hasAttribute("data-region")).toBe(false);
  });

  it.each(CHROMIUM_REGIONS)(
    "puts $value (low $low, high $high, optimum $optimum) where Chromium does: $region",
    ({ region, ...bands }) => {
      renderIn("en", <Meter label="Storage" {...bands} />);
      expect(meterOf().getAttribute("data-region")).toBe(region);
    },
  );
});

/** Every rule in the sheet, as `[selectors, declarations]`, comments stripped. */
function rules(): Array<[string[], string]> {
  const css = TERP_STYLES_CSS.replace(/\/\*[\s\S]*?\*\//g, "");
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => [
    match[1]!.split(",").map((part) => part.trim().replace(/\s+/g, " ")),
    match[2]!,
  ]);
}

/** The `var()` a rule's `background` names, for the one rule whose selectors include `selector`. */
function backgroundOf(selector: string): string | undefined {
  const found = rules().filter(([selectors]) => selectors.includes(selector));
  expect(found, `exactly one rule targets ${selector}`).toHaveLength(1);
  return /background:\s*var\((--[a-z0-9-]+)\)/.exec(found[0]![1])?.[1];
}

const VALUE_PSEUDOS = [
  "::-webkit-meter-optimum-value",
  "::-webkit-meter-suboptimum-value",
  "::-webkit-meter-even-less-good-value",
  "::-moz-meter-bar",
];
const TONES = {
  optimum: "--color-status-success",
  suboptimum: "--color-status-warning",
  "even-less-good": "--color-status-danger",
} as const;

describe("Meter's rules in the sheet", () => {
  it("paints the unbanded fill in the accent and each band in its own tone, in every engine's rule", () => {
    // The Gecko rules are the half no lane can see — the workbench runs one browser and it
    // drops them — so this is the only thing that notices one being deleted or retoned.
    for (const pseudo of VALUE_PSEUDOS) {
      expect(backgroundOf(`[data-terp="meter-bar"]${pseudo}`), pseudo).toBe("--color-fg-accent");
      for (const [region, tone] of Object.entries(TONES)) {
        expect(
          backgroundOf(`[data-terp="meter-bar"][data-region="${region}"]${pseudo}`),
          `${region} ${pseudo}`,
        ).toBe(tone);
      }
    }
  });

  it("keeps each engine's pseudo-elements in rules of their own", () => {
    // A selector list naming a pseudo-element an engine does not know is invalid as a whole,
    // so one mixed list would cost Chromium every meter rule in it rather than the Gecko half.
    for (const [selectors] of rules()) {
      const webkit = selectors.some((selector) => selector.includes("::-webkit-"));
      const gecko = selectors.some((selector) => selector.includes("::-moz-"));
      expect(webkit && gecko, selectors.join(", ")).toBe(false);
    }
  });

  it("paints only fills the contrast gate holds against the track they sit in", () => {
    // The sheet chooses the tokens; token-pairs.json is what the contrast gate measures in all
    // five themes. This joins the two, so retoning a fill to one nobody declared — the brand
    // fill, say, which falls under 3:1 against this track in the three dark themes — fails
    // here instead of shipping unmeasured.
    const track = backgroundOf('[data-terp="meter-bar"]');
    expect(track).toBe("--color-bg-inset");
    expect(backgroundOf('[data-terp="meter-bar"]::-webkit-meter-bar'), "both tracks agree").toBe(
      track,
    );
    const fills = new Set(
      rules()
        .filter(([selectors]) => selectors.some((s) => VALUE_PSEUDOS.some((p) => s.endsWith(p))))
        .map(([, body]) => /background:\s*var\((--[a-z0-9-]+)\)/.exec(body)?.[1]),
    );
    expect(fills.size).toBeGreaterThan(1);
    for (const fill of fills) {
      expect(
        tokenPairs.nonTextPairs.some((pair) => pair.fg === fill && pair.bg === track),
        `${fill} on ${track} is not a declared non-text pairing`,
      ).toBe(true);
    }
  });
});

class CatchBoundary extends Component<{ children: ReactNode }, { message: string | null }> {
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

/** Mount under the standard contract and let the archetype's slot check run once. */
async function underContract(node: ReactNode) {
  render(
    <CatchBoundary>
      <LayoutContractContext.Provider value="standard">{node}</LayoutContractContext.Provider>
    </CatchBoundary>,
  );
  // The slot check runs a macrotask after mount; flushing one inside act is what makes an
  // acceptance assertion wait for it rather than pass before it has run.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("where a Meter sits on a governed page", () => {
  it("is a value inside a section, and a section it is not", async () => {
    // Inside a section it is composition, which the contract never governs.
    await underContract(
      <DetailPage title="Project" parents={[{ label: "Projects", to: "/projects" }]}>
        <Card title="Usage">
          <DetailList
            items={[{ label: "Storage", value: <Meter label="Storage" value={0.62} /> }]}
          />
        </Card>
      </DetailPage>,
    );
    expect(screen.queryByTestId("refused")).toBeNull();
    cleanup();

    // Loose in the body it is refused. The label is an accessible name and not printed, so a
    // bare meter there is a bar with no visible caption at all — the section around it is
    // what supplies one.
    await underContract(
      <DetailPage title="Project" parents={[{ label: "Projects", to: "/projects" }]}>
        <Meter label="Storage" value={0.62} />
      </DetailPage>,
    );
    expect(screen.getByTestId("refused").textContent).toBe(
      slotViolationMessage("standard", "DetailPage", '<span data-terp="meter">'),
    );
  });
});
