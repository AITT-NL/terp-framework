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
      "states), detail bodies are record sections (DetailList / Stack / Tabs + " +
      "framework states). A bespoke screen composes the plain Page, which the " +
      "contract deliberately leaves unconstrained.",
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
          Stack: "stack",
          Tabs: "tabs",
          ModuleNav: "module-nav",
          DataView: "dataview",
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
 */
export function slotViolationMessage(contractId, slotOwner, found) {
  const allowed = Object.keys(LAYOUT_CONTRACTS[contractId].slots[slotOwner].components);
  return (
    `Layout contract "${contractId}": the ${slotOwner} body slot accepts only ` +
    `${allowed.join(" / ")}; found ${found}. Compose the body from those react-core ` +
    "components (recipe: terp guide layouts), move bespoke content to a plain Page, " +
    "or opt out on this line with a justified // terp-allow-layout-contract: <reason> " +
    "marker (counted by the escape-hatch budget)."
  );
}
