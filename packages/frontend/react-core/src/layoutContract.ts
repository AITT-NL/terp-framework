import { createContext, useContext } from "react";

/**
 * The runtime half of the slot-typed layout contract control (ADR 0079) — the layout
 * analog of ./pageMarker.ts. When an app opts into a contract
 * (`renderTerpApp({ layoutContract })` / `buildAppRouter(..., { layoutContract })`),
 * each governed page archetype verifies after mount that its body slot's rendered DOM
 * children are components the contract allows there — every sanctioned component stamps
 * a `data-terp` marker on its root — and refuses the view, fail closed, with the same
 * agent-directive message the `terp/layout-contract` lint rule phrases.
 *
 * Both halves govern the slot's DIRECT children only: an allowed container's own
 * subtree (a Card's body, a Stack's rows) is the app's to compose — nesting content
 * inside an allowed component is sanctioned composition, not an escape hatch.
 *
 * This table is the TypeScript mirror of the spec-as-data source in
 * `@terpjs/eslint-boundaries/src/layouts.js` (react-core ships standalone, so it cannot
 * import a lint package); the parity test in ./layoutContract.test.tsx keeps the two
 * identical, so the data cannot drift.
 */

/** One governed slot: allowed component names mapped to their `data-terp` root markers. */
export interface LayoutSlotSpec {
  readonly components: Readonly<Record<string, string>>;
}

/** One named layout contract: a description, its per-archetype slot specs and its frame rules. */
export interface LayoutContractSpec {
  readonly description: string;
  readonly slots: Readonly<Record<string, LayoutSlotSpec>>;
  /** What a page's summary band admits (ADR 0169 §4), on every page, the plain one included. */
  readonly summary: LayoutSlotSpec;
  /** The components whose `headline` marks the page's one headline figure (ADR 0169 §4). */
  readonly headline: LayoutSlotSpec;
}

/** Every layout contract, keyed by id (mirror of the eslint-boundaries source table). */
export const LAYOUT_CONTRACTS: Readonly<Record<string, LayoutContractSpec>> = {
  standard: {
    description:
      "The standard three-level shape: hub bodies are card grids (HubCard only), " +
      "overview bodies are data collections (DataView / ResourceList + framework " +
      "states), detail bodies are record sections (DetailList / Stack / Grid / Tabs " +
      "+ framework states); Card is allowed in overview and detail bodies as the " +
      "sanctioned visual separation between sections, and Divider / Text as a rule " +
      "between sections and a lead paragraph above them. Three specialised shapes sit " +
      "beside those: a form body is a container (Stack) with optional Grid / Card " +
      "sections and no Field at the top level, so the body is always a container rather " +
      "than a loose run of controls; a settings body is Card sections and holds no " +
      "collection; a split " +
      "body is two SplitPanes and nothing else; and a dashboard body is its figures and " +
      "charts in Grid sections, the collection they summarise and the framework states. " +
      "A workspace body is one CanvasHost, the surface that fills the screen, the " +
      "framework states and a ConfirmDialog. " +
      "A screen that needs no contract " +
      "composes the plain Page, whose body this contract deliberately leaves unconstrained. " +
      "Every page, the plain one included, keeps two rules of its frame: its summary band " +
      "holds the page's own figures (Stat / StatGroup / StatusHistory / Badge / Text), and " +
      "at most one " +
      "figure on the page is its headline.",
    slots: {
      HubPage: {
        components: { HubCard: "hubcard" },
      },
      OverviewPage: {
        components: {
          DataView: "dataview",
          ResourceList: "resource-list",
          ModuleNav: "module-nav",
          Stack: "stack",
          Card: "card",
          Divider: "divider",
          Text: "text",
          EmptyState: "empty-state",
          ErrorState: "error-state",
          LoadingState: "loading-state",
          Alert: "alert",
          ConfirmDialog: "dialog",
        },
      },
      FormPage: {
        components: {
          Stack: "stack",
          Grid: "grid",
          Card: "card",
          Divider: "divider",
          Text: "text",
          EmptyState: "empty-state",
          ErrorState: "error-state",
          LoadingState: "loading-state",
          Alert: "alert",
          ConfirmDialog: "dialog",
        },
      },
      SettingsPage: {
        components: {
          Card: "card",
          Stack: "stack",
          Divider: "divider",
          Text: "text",
          EmptyState: "empty-state",
          ErrorState: "error-state",
          LoadingState: "loading-state",
          Alert: "alert",
          ConfirmDialog: "dialog",
        },
      },
      SplitPage: {
        components: { SplitPane: "splitpane" },
      },
      DashboardPage: {
        components: {
          Grid: "grid",
          Stack: "stack",
          Card: "card",
          DataView: "dataview",
          Stat: "stat",
          StatGroup: "stat-group",
          TrendChart: "trend-chart",
          BarChart: "bar-chart",
          ProportionBar: "proportion-bar",
          StatusHistory: "status-history",
          Timeline: "timeline",
          Divider: "divider",
          Text: "text",
          EmptyState: "empty-state",
          ErrorState: "error-state",
          LoadingState: "loading-state",
          Alert: "alert",
          ConfirmDialog: "dialog",
        },
      },
      WorkspacePage: {
        components: {
          CanvasHost: "canvas-host",
          EmptyState: "empty-state",
          ErrorState: "error-state",
          LoadingState: "loading-state",
          Alert: "alert",
          ConfirmDialog: "dialog",
        },
      },
      DetailPage: {
        components: {
          DetailList: "detail-list",
          DetailListGroup: "detail-list-group",
          Stack: "stack",
          Tabs: "tabs",
          ModuleNav: "module-nav",
          DataView: "dataview",
          Card: "card",
          Grid: "grid",
          Divider: "divider",
          Text: "text",
          EmptyState: "empty-state",
          ErrorState: "error-state",
          LoadingState: "loading-state",
          Alert: "alert",
          ConfirmDialog: "dialog",
        },
      },
    },
    // The band a page renders under its title band when it is given a summary (ADR 0169 §4):
    // the page's own figures. Governed on every page, the plain Page included, because the
    // band belongs to the frame and not to a body.
    summary: {
      components: {
        Stat: "stat",
        StatGroup: "stat-group",
        StatusHistory: "status-history",
        Badge: "badge",
        Text: "text",
      },
    },
    // The components whose `headline` prop (rendered as `data-headline`) marks the page's
    // headline figure, of which a page carries at most one (ADR 0169 §4).
    headline: {
      components: { Stat: "stat" },
    },
  },
};

/**
 * The one agent-directive violation message both enforcement halves phrase: the
 * contract, the slot, what was found, what is allowed, and the concrete fix.
 * (Byte-identical to the eslint-boundaries builder; parity-tested.)
 */
export function slotViolationMessage(
  contractId: string,
  slotOwner: string,
  found: string,
): string {
  const allowed = Object.keys(LAYOUT_CONTRACTS[contractId]!.slots[slotOwner]!.components);
  return (
    `Layout contract "${contractId}": the ${slotOwner} body slot accepts only ` +
    `${allowed.join(" / ")}; found ${found}. Compose the body from those react-core ` +
    "components (recipe: terp guide layouts), move content that needs no contract to a " +
    "plain Page, " +
    "or opt out on this line with a justified // terp-allow-layout-contract: <reason> " +
    "marker (counted by the escape-hatch budget)."
  );
}

/**
 * The directive message for a page's summary band (ADR 0169 §4): what it admits, what was
 * found, and the fix. (Byte-identical to the eslint-boundaries builder; parity-tested.)
 */
export function summaryViolationMessage(contractId: string, found: string): string {
  const allowed = Object.keys(LAYOUT_CONTRACTS[contractId]!.summary.components);
  return (
    `Layout contract "${contractId}": a page's summary band accepts only ` +
    `${allowed.join(" / ")}; found ${found}. The band carries the page's own figures, so ` +
    "move anything else into the body (recipe: terp guide layouts), " +
    "or opt out on this line with a justified // terp-allow-layout-contract: <reason> " +
    "marker (counted by the escape-hatch budget)."
  );
}

/**
 * The directive message for a page that carries more than one headline figure (ADR 0169 §4).
 * (Byte-identical to the eslint-boundaries builder; parity-tested.)
 */
export function headlineViolationMessage(contractId: string, found: string): string {
  return (
    `Layout contract "${contractId}": a page carries at most one headline figure; found ` +
    `${found}. Keep headline on the one figure the page is about and render the others as ` +
    "ordinary figures (recipe: terp guide layouts), " +
    "or opt out on this line with a justified // terp-allow-layout-contract: <reason> " +
    "marker (counted by the escape-hatch budget)."
  );
}

/** The active contract id for the current routed view, or null (no contract = no checks). */
export const LayoutContractContext = createContext<string | null>(null);

/** A page's count of the figures marked headline, which each such figure joins. */
export interface HeadlineRegistry {
  /** Count one more headline; the function it returns counts that one out again. */
  register(): () => void;
}

/**
 * The nearest page's headline registry (ADR 0169 §4), or null outside a page.
 *
 * A registry rather than a DOM count, and the difference is when it looks. A count taken one
 * macrotask after the page renders missed a figure that rendered later -- a section that loads
 * its own data and then shows its headline -- because nothing renders the page again, and a
 * `querySelectorAll` over the article counted a nested page's figures as the outer page's,
 * which the lint does not. A figure that registers is counted whenever it mounts, by the page
 * it is nearest to, and only by that one.
 */
export const HeadlineContext = createContext<HeadlineRegistry | null>(null);

/** Read the active layout contract id (null outside an opted-in app). */
export function useLayoutContract(): string | null {
  return useContext(LayoutContractContext);
}

/**
 * The body-slot owner the enclosing archetype declared for its `Page` (set by
 * `OverviewPage` / `DetailPage`; `Page` resets it to null around its own children so a
 * nested tree is never judged by an ancestor's slot).
 */
export const LayoutSlotContext = createContext<string | null>(null);

/** How a rendered DOM child is described in a violation message. */
function describeElement(element: Element): string {
  const marker = element.getAttribute("data-terp");
  const tag = element.tagName.toLowerCase();
  return marker !== null ? `<${tag} data-terp="${marker}">` : `<${tag}>`;
}

/**
 * Verify a slot's rendered DOM children against the active contract: every child must
 * carry the `data-terp` marker of an allowed component. Returns the directive violation
 * message, or null when the slot conforms (or the contract/slot is not governed).
 */
export function verifySlotChildren(
  contractId: string,
  slotOwner: string,
  children: readonly Element[],
): string | null {
  const slot = LAYOUT_CONTRACTS[contractId]?.slots[slotOwner];
  if (slot === undefined) {
    return null;
  }
  return firstStranger(slot, children, (found) => slotViolationMessage(contractId, slotOwner, found));
}

/** The first child whose marker the slot does not admit, phrased by `describe`; or null. */
function firstStranger(
  slot: LayoutSlotSpec,
  children: readonly Element[],
  describe: (found: string) => string,
): string | null {
  const allowed = new Set(Object.values(slot.components));
  for (const child of children) {
    const marker = child.getAttribute("data-terp");
    if (marker === null || !allowed.has(marker)) {
      return describe(describeElement(child));
    }
  }
  return null;
}

/**
 * Verify a page's summary band against the contract (ADR 0169 §4): its children are the
 * figures it admits. Returns the directive message, or null when the band conforms or there is
 * none. The frame's other rule, one headline per page, is counted by registration instead (see
 * {@link HeadlineContext}).
 */
export function verifyPageSummary(contractId: string, page: Element): string | null {
  const contract = LAYOUT_CONTRACTS[contractId];
  if (contract === undefined) {
    return null;
  }
  const summary = [...page.children].find(
    (child) => child.getAttribute("data-terp") === "page-summary",
  );
  return summary === undefined
    ? null
    : firstStranger(contract.summary, [...summary.children], (found) =>
        summaryViolationMessage(contractId, found),
      );
}
