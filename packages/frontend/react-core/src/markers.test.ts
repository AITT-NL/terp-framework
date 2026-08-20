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

import manifest from "../package.json";

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
  "appshell",
  "appshell-backdrop",
  "appshell-brand",
  "appshell-brand-row",
  "appshell-brand-title",
  "appshell-column",
  "appshell-footer",
  "appshell-header",
  "appshell-header-group",
  "appshell-main",
  "appshell-nav",
  "appshell-nav-label",
  "appshell-nav-list",
  "appshell-sidebar",
  "badge",
  "breadcrumbs",
  "breadcrumbs-current",
  "breadcrumbs-separator",
  "button",
  "button-icon",
  "calendar",
  "calendar-day",
  "calendar-grid",
  "calendar-header",
  "calendar-title",
  "calendar-week",
  "calendar-weekday",
  "card",
  "card-actions",
  "card-description",
  "card-header",
  "card-heading",
  "card-title",
  "checkbox",
  "combobox",
  "combobox-empty",
  "combobox-field",
  "combobox-list",
  "combobox-option",
  "control-label",
  "dataview",
  "dataview-actions-cell",
  "dataview-card",
  "dataview-card-body",
  "dataview-card-expanded",
  "dataview-card-fields",
  "dataview-card-heading",
  "dataview-card-list",
  "dataview-card-main",
  "dataview-card-meta",
  "dataview-card-status",
  "dataview-card-title",
  "dataview-column-option",
  "dataview-column-resizer",
  "dataview-column-settings",
  "dataview-column-settings-title",
  "dataview-column-sort",
  "dataview-error",
  "dataview-expand-cell",
  "dataview-expanded-cell",
  "dataview-inline-action",
  "dataview-pager",
  "dataview-pagination",
  "dataview-row",
  "dataview-row-actions",
  "dataview-row-open",
  "dataview-scroll",
  "dataview-select-cell",
  "dataview-skeleton",
  "dataview-table",
  "dataview-toolbar",
  "dataview-toolbar-actions",
  "dataview-toolbar-count",
  "dataview-toolbar-layout",
  "dataview-toolbar-search",
  "dataview-toolbar-spacer",
  "dataview-toolbar-status",
  "detail-list",
  "detail-list-term",
  "detail-list-value",
  "dialog",
  "dialog-actions",
  "dialog-body",
  "dialog-description",
  "dialog-title",
  "drawer-focus-end",
  "drawer-focus-start",
  "empty-state",
  "empty-state-description",
  "empty-state-icon",
  "empty-state-title",
  "error-state",
  "error-state-description",
  "error-state-icon",
  "error-state-title",
  "field",
  "field-error",
  "field-hint",
  "field-label",
  "field-label-text",
  "hubcard",
  "hubcard-body",
  "hubcard-description",
  "hubcard-heading",
  "hubcard-icon",
  "hubcard-link",
  "hubcard-stat",
  "hubcard-title",
  "hubpage-grid",
  "icon",
  "iconbutton",
  "input",
  "language-switcher",
  "language-switcher-label",
  "loading-state",
  "loading-state-spinner",
  "login-brand",
  "login-card",
  "login-error",
  "login-form",
  "login-separator",
  "login-separator-rule",
  "login-sso",
  "login-title",
  "login-view",
  "markdown",
  "menu",
  "menu-item",
  "menu-item-check",
  "menu-item-icon",
  "menu-trigger",
  "module-nav",
  "module-nav-link",
  "module-nav-list",
  "nav-icon",
  "nav-icon-fallback",
  "page",
  "page-actions",
  "page-breadcrumbs",
  "page-header",
  "page-heading",
  "page-title",
  "popover",
  "popover-panel",
  "profile-avatar",
  "profile-card",
  "profile-email",
  "profile-role",
  "radio",
  "radio-group",
  "radio-group-legend",
  "radio-group-options",
  "resource-list",
  "resource-list-create",
  "resource-list-empty",
  "resource-list-error",
  "resource-list-items",
  "resource-list-row",
  "spinner-ring",
  "stack",
  "switch",
  "tab",
  "tab-list",
  "tab-panel",
  "tabs",
  "theme-toggle",
  "theme-toggle-label",
  "toast",
  "toast-body",
  "toast-icon",
  "toast-title",
  "toast-viewport",
  "tooltip",
  "tooltip-anchor",
  "user-menu",
  "user-menu-avatar",
  "user-menu-email",
  "user-menu-header",
  "user-menu-identity",
  "user-menu-role",
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
 *     returned a bare `Menu` in their `inline` variant — the variant the app shell header
 *     actually uses — so their root was `Popover`'s wrapper and indistinguishable from any
 *     other popover. Both have graduated, and the answer added no DOM: `Popover` takes the
 *     root's marker as a prop named `data-terp`, `Menu` threads it through, and each
 *     component names its own root with `data-variant` separating the variants. `UserMenu` was
 *     the same shape and has graduated too — it was also the last consumer of `Menu`'s
 *     `triggerStyle` and `panelStyle` props, which are gone: a marked root makes the trigger
 *     reachable by descending from it, and the PANEL, which is portalled to `document.body`
 *     and so reachable from nowhere, carries a `data-owner` attribute naming whose panel it
 *     is.
 *
 *     The prop is named for the attribute deliberately. The scanner below reads `data-terp`
 *     sites in component source, so `<Menu data-terp="theme-toggle">` is seen exactly where
 *     it looks; a `rootMarker` prop would have put the only mention of the name somewhere the
 *     scanner never looks, and a marker rendered by nobody's `data-terp` site is precisely
 *     the blind spot this file exists to close.
 *   - **Returned a fragment.** `Markdown` emitted a sequence of block elements with no root at
 *     all, and the objection to marking it was that a wrapper is a new block box in every
 *     consumer's layout. It has graduated, and that objection turned out to be answerable
 *     rather than true: the wrapper is `display: contents`, which generates no box, so the
 *     blocks stay in-flow siblings and become real flex or grid items of any parent that
 *     spaces its children with `gap`. Zero diff by construction — and a prose-rhythm block
 *     wrapper remains a later, deliberate change rather than a side effect of marking.
 *
 * Both are styling decisions with visible consequences, not bookkeeping, so they belong to
 * the migration itself rather than to preparation for it. The archetypes and the DataView
 * internals are still unexamined.
 *
 * `PageActions` has graduated, and it was the easiest of the shapes above: it already rendered
 * a real root of its own, so the marker landed on an element that existed and no DOM moved.
 * Note the one thing it does that a rule cannot — it returns `null` when it has no actions at
 * all, so its presence is conditional rather than styled, and `:empty` is not a substitute.
 *
 * `files.tsx` has left the list without gaining a marker, which is the one exit this ratchet
 * allows that is not a migration: it turned out to have no styled surface. Its single
 * declaration was `display: none` on the file picker's hidden plumbing input — the visible
 * control is a `Button` — and that element is now `hidden`, the attribute HTML provides for
 * exactly this. A marker plus a `display: none` rule would have put a component with no visual
 * design into the sheet and offered an app the chance to un-hide it.
 *
 * `DetailPage` and `OverviewPage` have left the same way, and they were on this list by
 * mistake rather than by migration: each is a `LayoutSlotContext.Provider` wrapped around
 * `Page` and renders no element of its own at all, so they are view compositions — which the
 * paragraph above already excludes. There is nothing to mark without inventing a box, and the
 * box is the one thing that must not exist here: `Page`'s slot check reads `article.children`,
 * so a wrapper around the body — `display: contents` included, since that check is a DOM
 * traversal and the node is still in the collection — becomes the sole body-slot child, is in
 * no allow table, and fails every governed page closed. Their archetype identity is a context
 * value, which is the right place for it: `Page` renders the only box either of them has, and
 * it is marked.
 *
 * Worth knowing about the shape of this list, because it flatters two files: it names files
 * with NO marker at all, so one marker on one element exempts the rest of the file. `toast.tsx`
 * and `ConfirmDialog.tsx` were never on it despite styling five and four unreachable elements
 * respectively, because each rendered one `iconbutton` or one `dialog`. Both have since
 * migrated; the gap in the ratchet has not.
 *
 * `Field` has graduated: it renders a root plus label, label text, hint and error markers,
 * so each part of a form field is addressable from the sheet.
 *
 * THE LIST IS EMPTY. `LoginView` was the last entry, and it is kept rather than deleted for
 * the same reason as the ledger below: this is where a new unmarked styled surface has to
 * argue for itself. Note what an empty list does NOT say, because the shape above already
 * flatters two files — it names modules with NO marker at all, so one marker anywhere in a
 * file exempts the rest of it.
 */
const UNMARKED_STYLED_SURFACES: string[] = [];

/**
 * How many module-scope base style objects each file still declares — the migration's own
 * measurable, as a ratchet.
 *
 * This exists because `UNMARKED_STYLED_SURFACES` above flatters a file: it lists modules with
 * NO `data-terp` at all, so a single marker on a single element exempts everything else in the
 * file. `toast.tsx` and `ConfirmDialog.tsx` were never on that list while styling five and four
 * unreachable elements respectively, because each rendered one `iconbutton` or one `dialog`.
 * Both have migrated, and the gap had not — until this.
 *
 * Counted per file rather than as a set of filenames, so a PARTIAL migration shows: moving half
 * of `AppShell`'s twenty-two objects into the sheet has to update the number here. Asserted as
 * exact equality, which makes it a ratchet in both directions — a new base style object fails,
 * and a removed one fails until the ledger is corrected. That is the same bargain `MARKERS`
 * strikes, and it is the point: the number is meant to be read during review.
 *
 * What is deliberately NOT counted: a measured value passed inline at a call site. `Icon` sizes
 * its box from a prop that takes any CSS length, `Stack` passes `align` / `justify` through, and
 * `Popover` positions its panel from a rect it measured — ADR 0094 §3 puts all three on the
 * inline side of the line permanently, so counting them would make this list unable to reach
 * zero and therefore unable to mean anything.
 *
 * IT HAS REACHED ZERO, and the honest reading of that is narrow. The detector matches a
 * module-scope declaration annotated `CSSProperties`, which means a call-site literal and an
 * unannotated module-scope object are both invisible to it. Four of the built-in admin views
 * carried five base styles through this entire migration for exactly that reason — three as
 * call-site literals, one as an unannotated `payloadStyle` — while both ratchets read clean.
 * The next commit widens the detector and migrates them, so that zero means what it looks
 * like it means.
 */
const INLINE_BASE_STYLES: Record<string, number> = {};

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
 *
 * The cost of reading a whole expression is that EVERY string literal inside one counts as a
 * marker. `data-terp={variant === "inline" ? "theme-toggle" : undefined}` reports both
 * `inline` and `theme-toggle`, and the first is not a marker at all. That is caught rather
 * than tolerated — the inventory assertion fails on the phantom name — and the fix is to keep
 * a marker expression to marker literals by hoisting the comparison out. Worth knowing before
 * writing a conditional marker, because the failure names a marker nobody added.
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
  it("keeps the inline base-style ledger honest, file by file", () => {
    // The migration's measurable, gated. A base style object is a module-scope CSSProperties
    // literal or factory — the shape a component uses to style its own root, and the shape the
    // sheet replaces. Comments are stripped first so prose naming the type cannot count.
    const declared: Record<string, number> = {};
    for (const [file, text] of production) {
      const matches = stripComments(text).match(/CSSProperties\s*(?:=\s*\{|=>\s*\()/g);
      if (matches !== null) {
        declared[file] = matches.length;
      }
    }
    expect(declared).toEqual(INLINE_BASE_STYLES);
  });

  it("injects the sheet from every module that owns a rule, or is reachable from one that does", () => {
    // Twelve marker-rendering modules never call injectTerpStyles and do not need to: the
    // package publishes ONE entry point and declares no `sideEffects`, so importing anything
    // from it loads every module and two dozen of them inject. That guarantee is a packaging
    // property, and nothing asserted it — a `sideEffects: false` added for bundle size, plus
    // tree-shaking, would remove it silently and the first symptom would be Markdown's blocks
    // collapsing into one grid item. So the property itself is what this pins.
    expect(Object.keys(manifest.exports)).toEqual(["."]);
    expect(manifest.exports["."]).toBe("./src/index.ts");
    expect(
      "sideEffects" in manifest,
      "declaring sideEffects would let a bundler drop the modules that inject the stylesheet",
    ).toBe(false);
    // And the sheet has many independent injectors reachable from that entry, or the packaging
    // properties above prove nothing on their own. The entry does NOT re-export ./styles — the
    // injection is a module side effect of the components themselves, which is exactly why the
    // sideEffects assertion is the one that matters.
    const injectors = production.filter(([, text]) =>
      stripComments(text).includes("injectTerpStyles()"),
    );
    expect(injectors.length).toBeGreaterThan(20);
    const index = sources["./index.ts"] ?? "";
    for (const [file] of injectors.slice(0, 3)) {
      const module = file.replace(/^\.\//, "./").replace(/\.tsx?$/, "");
      expect(index, `${file} injects the sheet but is not reachable from the entry point`).toContain(
        `from "${module}"`,
      );
    }
  });
});
