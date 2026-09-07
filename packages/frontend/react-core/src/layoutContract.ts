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

/** One named layout contract: a description and its per-archetype slot specs. */
export interface LayoutContractSpec {
  readonly description: string;
  readonly slots: Readonly<Record<string, LayoutSlotSpec>>;
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
      "collection; and a split " +
      "body is two SplitPanes and nothing else. A bespoke screen composes " +
      "the plain Page, which the contract deliberately leaves unconstrained.",
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
    "components (recipe: terp guide layouts), move bespoke content to a plain Page, " +
    "or opt out on this line with a justified // terp-allow-layout-contract: <reason> " +
    "marker (counted by the escape-hatch budget)."
  );
}

/** The active contract id for the current routed view, or null (no contract = no checks). */
export const LayoutContractContext = createContext<string | null>(null);

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
  const allowed = new Set(Object.values(slot.components));
  for (const child of children) {
    const marker = child.getAttribute("data-terp");
    if (marker === null || !allowed.has(marker)) {
      return slotViolationMessage(contractId, slotOwner, describeElement(child));
    }
  }
  return null;
}
