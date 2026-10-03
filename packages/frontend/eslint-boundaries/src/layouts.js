/**
 * Slot-typed layout contracts, declared **as data** (ADR 0079) — the layout analog of
 * ./spec.js. A contract names, per governed page archetype ("slot owner"), the react-core
 * components its body slot accepts; everything else is refused by BOTH halves of the
 * two-layer control:
 *
 *   - build time — the `terp/layout-contract` ESLint rule (./index.js) checks the static
 *     JSX children of each slot owner against the contract, and
 *   - runtime    — react-core's archetypes verify the rendered DOM children (each
 *     sanctioned component stamps a `data-terp` marker) and refuse the view, fail closed.
 *
 * Both halves phrase the SAME agent-directive message (see {@link slotViolationMessage}),
 * so a failing check *tells the author how to build the screen*, wherever it fires.
 *
 * Both halves govern the slot's DIRECT children only: an allowed container's own
 * subtree (a Card's body, a Stack's rows) is the app's to compose — nesting content
 * inside an allowed component is sanctioned composition, not an escape hatch.
 *
 * Contracts are opt-in and backwards compatible: no checked-in `layout-contract.json`
 * (and no `layoutContract` option at runtime) means today's behavior. The react-core
 * runtime carries a TypeScript mirror of this table (src/layoutContract.ts); a parity
 * test in react-core keeps the two byte-equal, so the data cannot drift.
 */

/** The checked-in config file that activates a contract for an app (lint side). */
export const LAYOUT_CONTRACT_FILE = "layout-contract.json";

/**
 * Every layout contract, keyed by id. Per slot owner (a page archetype), `components`
 * maps each allowed react-core component name to the `data-terp` marker it stamps on
 * its root element — the lint checks the names, the runtime checks the markers.
 */
export const LAYOUT_CONTRACTS = {
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
      "body is two SplitPanes and nothing else. A screen that needs no contract " +
      "composes the plain Page, whose body this contract deliberately leaves unconstrained. " +
      "Every page, the plain one included, keeps two rules of its frame: its summary band " +
      "holds the page's own figures (Stat / StatGroup / Badge / Text), and at most one " +
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
 */
export function slotViolationMessage(contractId, slotOwner, found) {
  const allowed = Object.keys(LAYOUT_CONTRACTS[contractId].slots[slotOwner].components);
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
 * found, and the fix.
 */
export function summaryViolationMessage(contractId, found) {
  const allowed = Object.keys(LAYOUT_CONTRACTS[contractId].summary.components);
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
 * Scarcity is the rule: an accent means something only while one figure has it.
 */
export function headlineViolationMessage(contractId, found) {
  return (
    `Layout contract "${contractId}": a page carries at most one headline figure; found ` +
    `${found}. Keep headline on the one figure the page is about and render the others as ` +
    "ordinary figures (recipe: terp guide layouts), " +
    "or opt out on this line with a justified // terp-allow-layout-contract: <reason> " +
    "marker (counted by the escape-hatch budget)."
  );
}
