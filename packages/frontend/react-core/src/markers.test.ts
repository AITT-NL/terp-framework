import { describe, expect, it } from "vitest";

// The `data-terp` marker inventory, pinned.
//
// A marker names a sanctioned component's rendered root. Two things already read them: the
// layout contract's runtime slot check (ADR 0079) verifies the identity of the components a
// body slot contains, and `TERP_STYLES_CSS` hangs every hover/active/disabled/selected
// declaration off them. So a marker is not decoration — it is the join between a component
// and both its enforcement and its styling.
//
// Nothing held that join in place. A renamed marker silently unstyles a component (the
// stylesheet rule stops matching, and no test asserts the rule matched anything) and
// silently widens a layout slot. Renaming is also exactly what a refactor does casually,
// because the string looks like a debug hook.
//
// Two sides are scanned separately and that separation is the whole point of this file:
// `styles.ts` *consumes* markers as CSS selectors, every component *produces* them as DOM
// attributes. Scanning them together is worse than not testing at all — the selectors in
// the sheet re-supply any name a component stopped rendering, so deleting a marker from a
// component leaves the inventory intact and the suite green while the app loses its styling.
//
// The ambient `ImportMeta.glob` type lives in raw.d.ts, shared with the other scanning tests.

const sources = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
});

/** The single module holding the framework stylesheet: markers appear there as selectors. */
const STYLESHEET = "./styles.ts";

/**
 * Every marker a component renders today.
 *
 * Adding a component adds a name here. Renaming one is a breaking change to both the
 * stylesheet and the layout contract, so it belongs in a release note.
 */
const MARKERS = [
  "alert",
  "alert-body",
  "alert-icon",
  "alert-title",
  "appshell-brand",
  "appshell-nav",
  "badge",
  "breadcrumbs",
  "button",
  "button-icon",
  "card",
  "card-actions",
  "card-header",
  "checkbox",
  "control-label",
  "dataview",
  "dataview-card",
  "dataview-row",
  "dataview-row-open",
  "dataview-table",
  "dataview-toolbar",
  "detail-list",
  "detail-list-term",
  "detail-list-value",
  "dialog",
  "drawer-focus-end",
  "drawer-focus-start",
  "empty-state",
  "error-state",
  "field",
  "field-error",
  "field-hint",
  "field-label",
  "field-label-text",
  "hubcard",
  "hubcard-body",
  "hubcard-description",
  "hubcard-link",
  "hubcard-stat",
  "hubcard-title",
  "iconbutton",
  "input",
  "loading-state",
  "menu",
  "menu-item",
  "module-nav",
  "nav-icon",
  "popover",
  "popover-panel",
  "radio",
  "radio-group",
  "radio-group-legend",
  "radio-group-options",
  "resource-list",
  "spinner-ring",
  "stack",
  "switch",
  "tab",
  "tabs",
  "tooltip",
  "tooltip-anchor",
];

/**
 * Styled surfaces that render no marker, and therefore cannot be reached by an attribute
 * selector or verified by a slot check.
 *
 * A ratchet that shrinks only: this list is the worklist for moving component styling out
 * of inline `style={}` and into the sheet, because a surface with no marker has nothing for
 * a rule to match. Providers, hooks, module manifests and view compositions are deliberately
 * absent — they render no styled root of their own.
 *
 * `Badge` and `Tooltip` have graduated: both own a single styled element, so marking them
 * changed no DOM and no pixels. What is left does *not* reduce to adding an attribute, and
 * the reason splits into two shapes worth knowing before the styling migration is planned:
 *
 *   - **Delegates its root.** `theme.tsx` (ThemeToggle) and `locale.tsx` (LanguageSwitcher)
 *     return a bare `Menu` in their `inline` variant — the variant the app shell header
 *     actually uses — so their root already carries `data-terp="menu"` and is
 *     indistinguishable from any other menu. `UserMenu` is the same shape. Marking them
 *     means either threading a marker through `Menu` or introducing a wrapper element.
 *   - **Returns a fragment.** `Markdown` emits a sequence of block elements with no root at
 *     all. A marker requires a wrapper, and a wrapper is a new block box in every consumer's
 *     layout.
 *
 * Both are styling decisions with visible consequences, not bookkeeping, so they belong to
 * the migration itself rather than to preparation for it. The archetypes, `PageActions` and
 * the DataView internals are still unexamined.
 *
 * `Field` has graduated: it renders a root plus label, label text, hint and error markers,
 * so each part of a form field is addressable from the sheet.
 */
const UNMARKED_STYLED_SURFACES = [
  "./DetailPage.tsx",
  "./LoginView.tsx",
  "./OverviewPage.tsx",
  "./PageActions.tsx",
  "./ProfileView.tsx",
  "./UserMenu.tsx",
  "./dataview/DataViewColumnSettings.tsx",
  "./dataview/DataViewExpandableRow.tsx",
  "./dataview/DataViewRowActions.tsx",
  "./files.tsx",
  "./locale.tsx",
  "./theme.tsx",
  "./ui/Markdown.tsx",
];

/**
 * `text` with comments removed, so prose naming a marker cannot stand in for rendering one.
 *
 * Line comments are only stripped from a `//` that does not follow a colon, which keeps
 * `https://` inside a string intact. Approximate by design: the result is fed to a marker
 * regex, never compiled.
 */
function stripComments(text: string) {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

/**
 * Marker values authored in `text`, in any of the forms the package actually uses:
 * `data-terp="x"`, `data-terp={"x"}`, `data-terp={open ? "x" : "y"}`, and `"data-terp": "x"`.
 *
 * A regex anchored to `data-terp="…"` alone misses the conditional form — which is how the
 * DataView row markers are written — so renaming one of those would not fail anything.
 */
function markersIn(text: string) {
  const source = stripComments(text);
  const found = new Set<string>();
  const attribute = /data-terp["']?\s*[=:]\s*/g;
  for (let match = attribute.exec(source); match; match = attribute.exec(source)) {
    const rest = source.slice(match.index + match[0].length);
    // An expression container may hold several literals (a ternary); a bare literal holds
    // one. Read only as far as the value actually extends, so the next attribute's string
    // is never absorbed.
    const scope = rest.startsWith("{") ? expressionAt(rest) : rest.slice(0, firstLiteralEnd(rest));
    for (const literal of scope.matchAll(/["']([a-z0-9-]+)["']/g)) {
      found.add(literal[1]!);
    }
  }
  return found;
}

/** The `{ … }` expression starting at `text[0]`, brace-matched. */
function expressionAt(text: string) {
  let depth = 0;
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === "{") depth += 1;
    else if (text[index] === "}") {
      depth -= 1;
      if (depth === 0) return text.slice(0, index + 1);
    }
  }
  return text;
}

/** The end of the single quoted literal starting at `text[0]`, or 0 when there is none. */
function firstLiteralEnd(text: string) {
  const quote = text[0];
  if (quote !== '"' && quote !== "'") return 0;
  const close = text.indexOf(quote, 1);
  return close === -1 ? 0 : close + 1;
}

const production = Object.entries(sources).filter(([file]) => !file.includes(".test."));
const components = production.filter(([file]) => file !== STYLESHEET);

/** Markers a component renders as a DOM attribute. */
const rendered = new Set(components.flatMap(([, text]) => [...markersIn(text)]));

/** Markers the framework stylesheet targets as `[data-terp="…"]` selectors. */
const styled = new Set(
  [...(sources[STYLESHEET] ?? "").matchAll(/\[data-terp=["']([a-z0-9-]+)["']\]/g)].map(
    (match) => match[1]!,
  ),
);

describe("data-terp markers", () => {
  it("reads both sides of the join it is asserting about", () => {
    expect(components.length).toBeGreaterThan(0);
    expect(sources[STYLESHEET], `${STYLESHEET} is not in the scanned source`).toBeDefined();
    expect(rendered.size).toBeGreaterThan(0);
    expect(styled.size).toBeGreaterThan(0);
    // The two sets must be gathered from different files, or the separation is cosmetic.
    expect(components.some(([file]) => file === STYLESHEET)).toBe(false);
  });

  it("renders exactly the pinned inventory", () => {
    // Sorted both sides so the diff on failure names the added or removed marker rather
    // than showing two long reordered lists.
    expect([...rendered].sort()).toEqual([...MARKERS].sort());
  });

  it("pins the inventory in sorted order with no duplicates", () => {
    // The list is read by humans during review; an unsorted or duplicated entry makes an
    // addition look like a rename.
    expect(MARKERS).toEqual([...new Set(MARKERS)].sort());
  });

  it("styles no marker that no component renders", () => {
    // A selector matching nothing is dead styling that reads as live: the rule is right
    // there in the sheet, so the state it describes looks handled when it is not.
    expect([...styled].filter((marker) => !rendered.has(marker)).sort()).toEqual([]);
  });

  it("keeps the unmarked-surface worklist accurate", () => {
    // One direction only: a file that gained a marker must leave the list, or the ratchet
    // stops meaning anything. It deliberately does not assert the converse — every
    // provider, hook and manifest in the package renders no marker legitimately, so
    // requiring the list to name every unmarked file would make it a list of everything.
    // A *new* unmarked primitive is therefore caught at review, not here.
    const stillUnmarked = components
      .filter(([, text]) => markersIn(text).size === 0)
      .map(([file]) => file);
    expect(
      UNMARKED_STYLED_SURFACES.filter((file) => !stillUnmarked.includes(file)),
      "these now render a marker — remove them from the worklist",
    ).toEqual([]);
    expect(
      UNMARKED_STYLED_SURFACES,
      "the worklist must stay sorted and duplicate-free",
    ).toEqual([...new Set(UNMARKED_STYLED_SURFACES)].sort());
  });
});
