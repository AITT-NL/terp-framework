import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { TERP_STYLES_CSS } from "./styles";

// ADR 0223: type and shape have roles, as colour does.
//
// Four tokens name what a component IS rather than which step of a scale it happens to sit on:
// the face and the weight of a heading, the corner of a control and the corner of a container.
// Each defaults to a reference to the step its readers used before, so nothing renders
// differently until a theme sets one; a house style or an app's theme.css that sets one
// separates its readers from the scale.
//
// The value of the roles is entirely in who reads them, so this file holds the readers to exact
// lists, in both directions: a component that stops reading its role, or one that starts, is a
// change to what a house style's setting reaches, and it has to arrive here and say so. The
// same goes for what stays on the scale: a new rule reading `--radius-md` or `--radius-lg`
// directly lands in a recorded list or fails, so every new corner is a choice between a role
// and a step rather than a default nobody made.

/** The sheet with comments removed: prose naming a token is not a reader. */
const sheet = TERP_STYLES_CSS.replace(/\/\*[\s\S]*?\*\//g, "");

// Vitest stubs .css imports to empty modules, so the token sheet is read from disk.
const tokensCss = readFileSync(new URL("../../contract/src/tokens.css", import.meta.url), "utf-8");

interface Rule {
  /** The rule's selector list, whitespace collapsed: `a, b` rather than a line per selector. */
  selector: string;
  declarations: Array<[property: string, value: string]>;
}

/** The index of the brace that closes the one opened at `open`. */
function closing(text: string, open: number): number {
  let depth = 0;
  for (let i = open; i < text.length; i += 1) {
    if (text[i] === "{") depth += 1;
    else if (text[i] === "}") {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  throw new Error(`unbalanced braces after offset ${open}`);
}

/**
 * Every style rule in `text`, at any depth of `@layer`, `@media`, `@supports` or `@container`.
 *
 * A reader of the flat text would see a rule inside a media query as a rule like any other,
 * which is right for this file's question (does anything read the token at all) but only if the
 * rules are found at every depth. `@keyframes` is skipped: its blocks are not selectors.
 */
function rulesOf(text: string): Rule[] {
  const found: Rule[] = [];
  let at = 0;
  while (at < text.length) {
    const open = text.indexOf("{", at);
    if (open === -1) break;
    // A statement at-rule (`@layer a, b;`) declares no block: consume it, or its `;` would
    // carry the scan on into the next rule's prelude.
    const statement = text.indexOf(";", at);
    if (statement !== -1 && statement < open) {
      at = statement + 1;
      continue;
    }
    const prelude = text.slice(at, open).trim().replace(/\s+/g, " ");
    const close = closing(text, open);
    const body = text.slice(open + 1, close);
    if (prelude.startsWith("@keyframes")) {
      // Not style rules.
    } else if (prelude.startsWith("@")) {
      found.push(...rulesOf(body));
    } else {
      const declarations = body
        .split(";")
        .map((part) => part.trim())
        .filter((part) => part.includes(":"))
        .map((part): [string, string] => {
          const colon = part.indexOf(":");
          return [part.slice(0, colon).trim(), part.slice(colon + 1).trim()];
        });
      found.push({ selector: prelude.replace(/\s*,\s*/g, ", "), declarations });
    }
    at = close + 1;
  }
  return found;
}

const rules = rulesOf(sheet);

/** The selector of every rule with a declaration that reads `token`, sorted, duplicates kept. */
function readersOf(token: string): string[] {
  return rules
    .filter((rule) => rule.declarations.some(([, value]) => value.includes(`var(${token})`)))
    .map((rule) => rule.selector)
    .sort();
}

/** The `:root` value the contract's token sheet declares for `token`. */
function rootValue(token: string): string | undefined {
  const root = tokensCss.indexOf(":root {");
  const block = tokensCss.slice(root, closing(tokensCss, tokensCss.indexOf("{", root)));
  return new RegExp(`${token}:\\s*([^;]+);`).exec(block)?.[1]?.trim();
}

const sorted = (list: string[]) => [...list].sort();

/**
 * Everything that names a page, a section, a dialog or the app: the heading face's readers.
 */
const HEADING_FACE = [
  '[data-terp="heading"]',
  '[data-terp="page-title"]',
  '[data-terp="card-title"]',
  '[data-terp="dialog-title"]',
  '[data-terp="hubcard-title"]',
  '[data-terp="empty-state-title"]',
  '[data-terp="error-state-title"]',
  '[data-terp="dataview-title"]',
  '[data-terp="appshell-brand-title"]',
  '[data-terp="login-title"]',
  '[data-terp="admin-section-title"]',
];

/**
 * The two headings that take the face and keep their own weight, and why (ADR 0223 §3). Moving
 * either onto the role repaints the sign-in or the access screen of every app, which is a
 * re-baselined change of its own, not something to do in passing.
 */
const OWN_WEIGHT: Record<string, string> = {
  '[data-terp="login-title"]': "set bold, a step heavier than every other heading",
  '[data-terp="admin-section-title"]': "an h3 at the browser's bold, with no weight of its own",
};

/** The heading weight's readers: the face's, less the two recorded above. */
const HEADING_WEIGHT = HEADING_FACE.filter((selector) => !(selector in OWN_WEIGHT));

/**
 * Title markers that are deliberately NOT headings, each in its own voice. With
 * `HEADING_FACE` this is every `-title` marker the sheet styles, so a new one has to be put in
 * one list or the other: a component that names something is a heading's business, and one
 * that only labels something keeps the body's face.
 */
const NOT_HEADINGS: Record<string, string> = {
  "alert-title": "a message's first line, in the message's voice",
  "toast-title": "a message's first line, in the message's voice",
  "calendar-title": "the month a picker is showing: a control's label",
  "dataview-card-title": "a record's name in a list of cards, at the weight of the row it replaces",
  "dataview-column-settings-title": "the label of a menu of column options",
};

/** What a person presses or types into. */
const CONTROLS = [
  '[data-terp="button"]',
  '[data-terp="input"]',
  '[data-terp="menu-trigger"]',
  '[data-terp="appshell-nav"] a',
  '[data-terp="appshell-header"] > [data-terp="iconbutton"], [data-terp="appshell-brand-row"] > [data-terp="iconbutton"]',
  '[data-terp="dataview-toolbar-layout"] > [data-terp="iconbutton"]',
  '[data-terp="dataview-pager"] > [data-terp="iconbutton"]',
  '[data-terp="calendar-header"] > [data-terp="iconbutton"]',
  '[data-terp="dataview-inline-action"]',
  '[data-terp="page-sequence-previous"] > a, [data-terp="page-sequence-next"] > a',
  '[data-terp="calendar-day"]',
  '[data-terp="appshell-skip-link"]:focus-visible',
];

/**
 * Controls of several lines, which wear the control corner up to the container corner and no
 * rounder. A pill control corner suits a button and a one-line field, but on a box of several
 * lines it draws a stadium whose ends cut into the text; the default control corner is the
 * smaller of the two, so the cap is inert until a style rounds its controls past its
 * containers. Each reads both roles, in exactly this form.
 */
const MULTI_LINE_CONTROLS = [
  'textarea[data-terp="input"]',
  'select[data-terp="input"][multiple], select[data-terp="input"][size]:not([size="0"]):not([size="1"])',
  '[data-terp="combobox-field"][data-multiple="true"]',
];
const MULTI_LINE_CORNER = "min(var(--radius-control), var(--radius-container))";

/** What holds content on the surface ladder. */
const CONTAINERS = [
  '[data-terp="card"]',
  '[data-terp="page-summary"]',
  '[data-terp="canvas-host"]',
  '[data-terp="login-card"]',
  '[data-terp="profile-card"]',
  '[data-terp="hubcard-body"]',
  '[data-terp="dataview"][data-variant="full"] > [data-terp="dataview-scroll"], [data-terp="dataview"][data-variant="full"] > [data-terp="dataview-error"], [data-terp="dataview"][data-variant="full"] > [data-terp="dataview-skeleton"]',
  // The frame's header corners: the frame cannot clip (it would trap the scroller), so the two
  // end cells round themselves to the frame's own corner, and must follow it.
  '[data-terp="dataview"][data-variant="full"] [data-terp="dataview-table"] > thead > tr > th:first-child',
  '[data-terp="dataview"][data-variant="full"] [data-terp="dataview-table"] > thead > tr > th:last-child',
  '[data-terp="dataview-card"]',
  '[data-terp="empty-state"]',
  '[data-terp="error-state"]',
  '[data-terp="trend-chart"], [data-terp="bar-chart"], [data-terp="proportion-bar"]',
  '[data-terp="stat"]',
  '[data-terp="stat-group"] > [data-terp="stat"][data-headline]',
  '[data-terp="dialog"]',
  '[data-terp="popover-panel"]',
  '[data-terp="combobox-list"]',
];

/**
 * What still reads the scale's `md` step directly, by decision (ADR 0223 §3): messages, blocks
 * and the boxes inside a component, which move with the scale and with neither role.
 */
const MD_ON_THE_SCALE = [
  '[data-terp="alert"]',
  '[data-terp="toast"]',
  '[data-terp="code-block"]',
  '[data-terp="tile"]',
  '[data-terp="resource-list-row"]',
  '[data-terp="dataview-skeleton"] > div',
  '[data-terp="dataview-toolbar"][data-variant="selection"]',
  '[data-terp="appshell-brand"]',
  '[data-terp="hubcard-icon"]',
];

/** And the `lg` step: a badge is a label, not a container. */
const LG_ON_THE_SCALE = ['[data-terp="badge"]'];

describe("ADR 0223 — type and shape roles", () => {
  it("parses the sheet it is asserting about", () => {
    // Every list below is compared for equality, and an empty parse would make an empty
    // expectation pass. A few hundred rules is the order of magnitude of the sheet.
    expect(rules.length).toBeGreaterThan(400);
    expect(rules.some((rule) => rule.selector === '[data-terp="button"]')).toBe(true);
  });

  it("defaults every role to a reference to the step its readers used before", () => {
    // A reference rather than the value: a theme that moved the step before the role existed
    // keeps moving every reader it moved, and setting the role is the one way to separate them.
    expect(rootValue("--font-family-heading")).toBe("var(--font-family-sans)");
    expect(rootValue("--font-weight-heading")).toBe("var(--font-weight-semibold)");
    expect(rootValue("--radius-control")).toBe("var(--radius-md)");
    expect(rootValue("--radius-container")).toBe("var(--radius-lg)");
    // Declared once, in :root: type and shape are theme-invariant, and a theme block that
    // redeclared one would make an app's corners change with its palette.
    for (const token of ["--font-family-heading", "--font-weight-heading", "--radius-control", "--radius-container"]) {
      expect(tokensCss.match(new RegExp(`${token}:`, "g"))?.length, token).toBe(1);
    }
  });

  it("gives every heading the heading face, and no heading the body face", () => {
    expect(readersOf("--font-family-heading")).toEqual(sorted(HEADING_FACE));
    for (const selector of HEADING_FACE) {
      const families = rules
        .filter((rule) => rule.selector === selector)
        .flatMap((rule) => rule.declarations.filter(([property]) => property === "font-family"));
      expect(families, selector).toEqual([["font-family", "var(--font-family-heading)"]]);
    }
  });

  it("gives every heading the heading weight, except the two recorded with their reason", () => {
    expect(readersOf("--font-weight-heading")).toEqual(sorted(HEADING_WEIGHT));
    for (const selector of HEADING_WEIGHT) {
      const weights = rules
        .filter((rule) => rule.selector === selector)
        .flatMap((rule) => rule.declarations.filter(([property]) => property === "font-weight"));
      expect(weights, selector).toEqual([["font-weight", "var(--font-weight-heading)"]]);
    }
    // The exceptions are real: each still renders the weight its reason gives.
    expect(
      rules.find((rule) => rule.selector === '[data-terp="login-title"]')?.declarations,
    ).toContainEqual(["font-weight", "var(--font-weight-bold)"]);
    expect(
      rules
        .filter((rule) => rule.selector === '[data-terp="admin-section-title"]')
        .flatMap((rule) => rule.declarations.map(([property]) => property)),
    ).not.toContain("font-weight");
  });

  it("puts every title the sheet styles in one list or the other", () => {
    const markers = new Set(
      [...sheet.matchAll(/\[data-terp="([a-z-]*title|heading)"\]/g)].map((match) => match[1]!),
    );
    const headings = new Set(
      HEADING_FACE.map((selector) => /\[data-terp="([a-z-]+)"\]/.exec(selector)![1]!),
    );
    const recorded = new Set([...headings, ...Object.keys(NOT_HEADINGS)]);
    expect([...markers].sort()).toEqual([...recorded].sort());
    for (const marker of Object.keys(NOT_HEADINGS)) {
      expect(headings.has(marker), `${marker} is recorded as both`).toBe(false);
    }
  });

  it("gives every control the control corner, and nothing but those and the capped multi-line controls reads it", () => {
    expect(readersOf("--radius-control")).toEqual(sorted([...CONTROLS, ...MULTI_LINE_CONTROLS]));
  });

  it("gives every container the container corner, and nothing but those and the capped multi-line controls reads it", () => {
    expect(readersOf("--radius-container")).toEqual(sorted([...CONTAINERS, ...MULTI_LINE_CONTROLS]));
  });

  it("caps a multi-line control's corner at the container's, so a pill never clips its text", () => {
    for (const selector of MULTI_LINE_CONTROLS) {
      const corners = rules
        .filter((rule) => rule.selector === selector)
        .flatMap((rule) => rule.declarations.filter(([property]) => property === "border-radius"));
      expect(corners, selector).toEqual([["border-radius", MULTI_LINE_CORNER]]);
    }
    // Inert by default: the control corner's default step is the smaller one.
    expect(rootValue("--radius-control")).toBe("var(--radius-md)");
    expect(rootValue("--radius-container")).toBe("var(--radius-lg)");
  });

  it("records by name everything that still reads the md and lg steps directly", () => {
    // The other direction of the two above, and the one that keeps the roles honest over time:
    // a component written after this one, reaching for the step its neighbours use, has to
    // land in one of these lists or take a role, so its corner is a decision someone made.
    expect(readersOf("--radius-md")).toEqual(sorted(MD_ON_THE_SCALE));
    expect(readersOf("--radius-lg")).toEqual(sorted(LG_ON_THE_SCALE));
  });
});
