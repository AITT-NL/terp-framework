import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { NARROW_VIEWPORT, WIDE_VIEWPORT_QUERY } from "./breakpoints";
import { TERP_STYLES_CSS } from "./styles";

// Vitest stubs .css imports to empty modules, so the sheet is read from disk.
const tokensCss = readFileSync(
  new URL("../../contract/src/tokens.css", import.meta.url),
  "utf-8",
);

// The package keeps its deliberate `"types": []` isolation: react-core source must never
// see ambient Node globals. The source scan uses Vite's raw glob and the sheet needs fs;
// both are declared minimally in raw.d.ts, shared with the other scanning tests.
const sources = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
});

/** Every custom property the token sheet declares (any palette block). */
const declared = new Set(
  [...tokensCss.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((match) => match[1]!),
);

/** The framework sheet with its comments removed — prose naming a token is not a reader. */
const sheet = TERP_STYLES_CSS.replace(/\/\*[\s\S]*?\*\//g, "");

/**
 * Published motion tokens no rule in the sheet reads, as an exact list.
 *
 * The other three are wired: every `transition` in the sheet names
 * `--motion-duration-fast` / `--motion-duration-instant` with
 * `--motion-easing-standard`, which was inert by construction because those tokens'
 * values ARE the `150ms` / `100ms` / `ease` literals they replaced.
 *
 * These four are not, and leaving them that way is a position rather than an omission.
 * They map onto no literal this sheet contains, so there is nothing to convert. The two
 * ways out are both worse than naming them here: deleting them is a **contract change**,
 * since `tokens.manifest.json` publishes them and a consumer may already read one; and
 * giving them readers means inventing overlay entrance/exit animations, which is a
 * behaviour change wearing a token wiring's clothes — and one the screenshot lane cannot
 * see either way, because it runs with `animations: "disabled"`.
 *
 * Exact equality in both directions, which is what makes it a decision instead of drift:
 * wiring one has to shrink this list, and publishing an eighth motion token has to
 * either name a reader or land here with a reason.
 */
const UNREAD_TOKENS: Record<string, string[]> = {
  "--motion-": [
    "--motion-duration-base",
    "--motion-duration-slow",
    "--motion-easing-entrance",
    "--motion-easing-exit",
  ],
  // The published type scale, wired in 4b by the prose components — and the reason it took a
  // new component rather than a conversion is the interesting part. Every motion literal
  // mapped exactly onto a token, so wiring those was inert. Here the sheet writes line heights
  // of 1.2, 1.25, 1.3, 1.4 and 1.5 while the scale offers 1.2, 1.35, 1.5 and 1.7: only 8 of 32
  // literals map. Converting those eight and leaving thirteen is a half-migration, and
  // converting the rest CHANGES rendered line heights across a dozen components — a typography
  // pass with its own baselines, not a token wiring done in passing. New components have
  // nothing depending on their metrics, so they take the scale as published.
  "--font-line-height-": [],
  // EMPTY, and `wide` is what emptied it. It sat here reading "for the uppercase-label
  // treatment nothing in the package uses" — a token waiting for a component. The navigation
  // group label is that treatment, and it takes 0.08em from the scale rather than adding a
  // third bare literal beside the sheet's 0.04em and 0.06em. Which is the whole point of
  // keeping this list: it named the reader before the reader existed, so the new rule had one
  // obvious right answer instead of a plausible wrong one.
  "--font-letter-spacing-": [],
  // The shell's published geometry, tracked from the day it shipped rather than after
  // something rots. All four have readers — two sidebar widths, the header's floor and the
  // content measure — so the list is empty, and empty is the assertion: a fifth shell token
  // added without a rule to read it lands here and has to justify itself. That is the exact
  // offence `--color-fg-on-brand` was deleted for, and the reason it went unnoticed for a
  // release is that only three families were tracked at all. (Still only four: `--color-`,
  // `--space-`, `--radius-` and the rest publish unread tokens with nothing to say so. The
  // sidebar colour family WAS in that state for four releases — five tokens declared in every
  // theme and read by nothing — which is the offence `--color-fg-on-brand` was deleted for. The
  // difference there is that the vocabulary was wrong; here it was right and the readers were
  // missing, so the fix was to wire them. Tracked from now on.)
  "--shell-": [],
  "--color-sidebar-": [],
  // The whole semantic colour layer, which the comment above admitted was untracked and then
  // left untracked. Seventeen of the forty-eight published `--color-` tokens have no `var()`
  // reader anywhere in the sheet, and until now nothing said so — the exact `--color-fg-on-brand`
  // shape that comment describes, seventeen times over.
  //
  // Booked as one family rather than four narrower ones on purpose. `--color-bg-`,
  // `--color-border-`, `--color-interactive-` and `--color-chart-` are each read by NOTHING, and
  // the assertion below requires a tracked family to publish more than it books — a deliberate
  // "is the prefix right?" check that a wholly-unread family would trip. The broader prefix
  // subsumes them and still catches the eighteenth. `--color-sidebar-` stays above because it
  // makes a narrower claim worth keeping: that family is read in full.
  //
  // None of these seventeen is a defect on its own. They are a published vocabulary that shipped
  // ahead of its consumers — four surface tokens, three borders, three interactive states, a
  // five-step chart ramp and two neutrals — and the point of booking them is that the list can
  // only shrink from here, so wiring one is visible and adding an eighteenth has to argue.
  "--color-": [
    "--color-bg-canvas",
    "--color-bg-inset",
    "--color-bg-raised",
    "--color-bg-surface",
    "--color-border-default",
    "--color-border-strong",
    "--color-border-subtle",
    "--color-chart-1",
    "--color-chart-2",
    "--color-chart-3",
    "--color-chart-4",
    "--color-chart-5",
    "--color-interactive-active",
    "--color-interactive-hover",
    "--color-interactive-selected",
    "--color-neutral-500",
    "--color-neutral-800",
  ],
};

/**
 * Bare `line-height` / `letter-spacing` values still in the sheet, as an exact multiset.
 *
 * The reconciliation debt, made a number so it cannot grow quietly. The scale above is now
 * read, but these 32 declarations predate it and most map onto nothing in it — so a new rule
 * that adds a 27th bare line height has to either use a token or come here and say why, and
 * whoever does the typography pass has a target rather than a grep.
 *
 * Two entries are permanent rather than pending: `line-height: 0` and `line-height: 1` are
 * icon and avatar boxes, where the line box is being removed rather than set to a step on a
 * prose scale.
 */
const BARE_TYPE_LITERALS: Record<string, Record<string, number>> = {
  "line-height": { "0": 2, "1": 4, "1.2": 4, "1.25": 7, "1.3": 2, "1.4": 3, "1.5": 4 },
  // `inherit` is recorded rather than tokenised, and it is the one value here that is not
  // debt: the sort button in a table header must render the tracking its own `th` sets, and
  // naming a token would pin it to whatever that header uses TODAY. The UA stylesheet resets
  // letter-spacing on form controls, so inheritance has to be asked for explicitly — the
  // header and its button were rendering two different treatments side by side until it was.
  "letter-spacing": { "0": 4, "0.04em": 1, "0.06em": 1, inherit: 1 },
};

describe("design tokens", () => {
  it("only references custom properties the contract token sheet declares", () => {
    // A fallback-less var() against an undeclared token silently computes to the
    // inherited/initial value — the exact class of bug this guard pins down
    // (e.g. a font-weight token typo reintroducing parent-font inheritance).
    expect(declared.size).toBeGreaterThan(0);
    expect(Object.keys(sources).length).toBeGreaterThan(0);
    const offenders: string[] = [];
    for (const [file, text] of Object.entries(sources)) {
      for (const match of text.matchAll(/var\((--[a-z0-9-]+)\)/g)) {
        const token = match[1]!;
        if (!declared.has(token)) {
          offenders.push(`${file}: ${token}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("opts native chrome into the palette via color-scheme (light + dark)", () => {
    // Without `color-scheme`, native chrome the framework cannot restyle — the
    // <select> option popup, and any scrollbar a browser draws natively — stays
    // in OS-light rendering even under the dark theme. The light root declares
    // it and both dark blocks (explicit [data-theme='dark'] and the
    // prefers-color-scheme media query) flip it.
    expect(tokensCss).toContain("color-scheme: light");
    expect(tokensCss.match(/color-scheme: dark/g)?.length ?? 0).toBeGreaterThanOrEqual(2);
  });

  it("spells the one viewport cutover from the published token, in one place", () => {
    // The breakpoint is the other token family nothing can `var()`: CSS forbids a custom
    // property in a media-query condition, and `matchMedia` takes a string, so neither
    // consumer can read `--breakpoint-md` the way a colour is read. The literal is therefore
    // unavoidable — and unguarded it was already written twice, verbatim, in `AppShell` and
    // `DataView`, which is the duplication the diagnosis named.
    //
    // So this holds three things together that CANNOT agree by construction: the token the
    // contract publishes, the string the components hand to `matchMedia`, and the query the
    // stylesheet uses. The third one at least is the complement of the second by construction
    // rather than by a second literal.
    const declaredMd = /--breakpoint-md:\s*([^;]+);/.exec(tokensCss)?.[1]?.trim();
    expect(declaredMd, "the contract should publish --breakpoint-md").toBe("768px");
    expect(NARROW_VIEWPORT).toBe(`(max-width: ${declaredMd})`);
    expect(WIDE_VIEWPORT_QUERY).toBe(`not all and ${NARROW_VIEWPORT}`);
    expect(sheet).toContain(`@media ${WIDE_VIEWPORT_QUERY}`);

    // And nobody re-spells it. The two components import the constant now; a third copy is
    // exactly how the first two came to disagree with nothing noticing.
    const offenders = Object.entries(sources)
      .filter(([file]) => !file.includes(".test.") && file !== "./breakpoints.ts")
      .filter(([, text]) => text.includes("max-width: 768px"))
      .map(([file]) => file);
    expect(offenders, "the breakpoint belongs in ./breakpoints.ts and nowhere else").toEqual([]);
  });

  it("names every published token in a tracked family that the sheet does not read", () => {
    // The other direction of this file's join. The test above catches a `var()` naming a
    // token the contract never declared; this one catches a token the contract publishes
    // that nothing consumes — the `--color-fg-on-brand` shape, which was deleted for
    // being declared in five themes and read by none. A Studio editor built from the
    // manifest offers a control per published token, so an unread one is a knob that
    // does nothing.
    for (const [family, unread] of Object.entries(UNREAD_TOKENS)) {
      const published = [
        ...new Set(
          // `[a-z0-9-]`, not `[a-z-]`. The narrower class could not match a token name with a
          // DIGIT in it, which is every step of every scale the contract publishes — all nine
          // neutrals, the five chart colours, every `--space-N` and `--font-size-N`. So a family
          // containing them reported only its wordy members as published, and an unread numbered
          // token was invisible to a test whose entire job is to name unread tokens. Found when
          // the semantic colour layer was booked and the guard could see ten of its seventeen.
          [...tokensCss.matchAll(new RegExp(`(${family}[a-z0-9-]+)\\s*:`, "g"))].map(
            (match) => match[1]!,
          ),
        ),
      ];
      expect(published.length, `${family} publishes nothing — is the prefix right?`).toBeGreaterThan(
        unread.length,
      );
      expect(
        published.filter((token) => !sheet.includes(`var(${token})`)).sort(),
        `a published ${family} token gained or lost a reader — wire it, or record it with a reason`,
      ).toEqual(unread);
    }
  });

  it("holds the bare type literals at their recorded count", () => {
    // The debt the type scale's arrival did not clear, as a ratchet. See BARE_TYPE_LITERALS:
    // most of these map onto no step in the published scale, so converting them changes
    // rendered line heights and belongs in a typography pass. What this stops is the count
    // growing in the meantime.
    for (const [property, expected] of Object.entries(BARE_TYPE_LITERALS)) {
      const counts: Record<string, number> = {};
      for (const match of sheet.matchAll(new RegExp(`\\b${property}:\\s*([^;]+);`, "g"))) {
        const value = match[1]!.trim();
        if (value.includes("var(")) continue;
        counts[value] = (counts[value] ?? 0) + 1;
      }
      expect(
        counts,
        `${property}: use the published scale, or record the new literal here`,
      ).toEqual(expected);
    }
  });
});
