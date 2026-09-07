import type { components } from "@terpjs/contract";

export type AccessModel = components["schemas"]["AccessModelRead"];
type AccessModule = components["schemas"]["AccessModuleRead"];
type AccessEndpoint = components["schemas"]["AccessEndpointRead"];

/**
 * Pure derivation of the access pane's rows from one `/model` payload — no React, no fetching,
 * so the part that decides what a reader is told stays independently readable and testable.
 *
 * Everything here is a *rearrangement* of what the server already said. No allowance is
 * recomputed: `by_role` carries the outcome the kernel guard itself produced for each rung
 * (ADR 0121 §4), so this file groups and diffs those answers and never forms an opinion about
 * them. That is the whole reason the server projects per-rung outcomes rather than raw policy —
 * a client that re-derived allowance from rank comparisons would be a second implementation of
 * the decision, and the copy that drifts is the one an administrator is shown.
 */

/** What kind of thing an operation does, which is what makes a delta worth reading. */
export type OperationKind = "read" | "write" | "delete";

/** One operation a rung can reach, named in the source language where the route declared one. */
export interface ReachableOperation {
  kind: OperationKind;
  /** The declared operation label, or the route's own name when it declared none. */
  label: string;
  /** True when no operation was declared, so the pane can say "unexplained" rather than guess. */
  unexplained: boolean;
}

/** One rung of a module's ladder, with what it adds over the rung below. */
export interface ModuleRung {
  role: string;
  rank: number;
  /** Everything reachable at this rung, cumulative — the ladder is inclusive. */
  reachable: ReachableOperation[];
  /**
   * What moving *to* this rung hands over that the rung below did not.
   *
   * The tile shows this rather than the cumulative set, because "everything below, plus…" is
   * the only framing in which two rungs can be compared at a glance. Split by kind for the
   * reason the reference application split it: "may delete three things" is a different
   * decision from "may read thirty", and a mixed list buries the destructive half in the
   * middle of the harmless one.
   */
  added: Record<OperationKind, ReachableOperation[]>;
  /**
   * True when this rung adds nothing at all over the one below.
   *
   * Common and worth saying out loud: a module whose `Policy` only distinguishes read from
   * write has an `admin` rung that buys nothing, and an administrator who assigns it expecting
   * more has made a mistake the pane could have prevented. This is ADR 0121's second open
   * question, answered in the direction of telling the truth rather than hiding the rung.
   */
  addsNothing: boolean;
}

/** One module's row in the pane. */
export interface ModuleRow {
  name: string;
  /** What to call it: the declared label, falling back to the module's own identifier. */
  label: string;
  /** Whether a rung here can be assigned at all. */
  assignable: boolean;
  /** Why not, when a module refuses outright — the justification it declared. */
  platformReason: string | null;
  rungs: ModuleRung[];
  /** The permissions this module claims, by name. */
  permissions: string[];
  /**
   * Routes that declared no operation, so the pane can say the module is not fully explained
   * rather than presenting a partial list as complete. Empty is the good state.
   */
  unexplainedRoutes: number;
}

function kindOf(endpoint: AccessEndpoint): OperationKind {
  // Derived from the methods the server reported, not from a second opinion about the verb.
  // A WebSocket reports no method and is guarded at the write tier, which is what the guard
  // does with a connection that has no method after the upgrade.
  const methods = endpoint.methods ?? [];
  if (methods.includes("DELETE")) return "delete";
  if (methods.length === 0) return "write";
  if (methods.some((method) => method !== "GET" && method !== "HEAD" && method !== "OPTIONS")) {
    return "write";
  }
  return "read";
}

function describe(endpoint: AccessEndpoint): ReachableOperation {
  const declared = endpoint.operation?.label;
  return {
    kind: kindOf(endpoint),
    label: declared ?? endpoint.name,
    unexplained: declared === undefined || declared === null,
  };
}

/** Whether a rung may reach an endpoint, as the *server* answered it. */
function allowedAt(endpoint: AccessEndpoint, role: string): boolean {
  return endpoint.by_role?.some((row) => row.role === role && row.allowed) ?? false;
}

const EMPTY_ADDED: () => Record<OperationKind, ReachableOperation[]> = () => ({
  read: [],
  write: [],
  delete: [],
});

function buildRungs(module: AccessModule, ladder: AccessModel["roles"]): ModuleRung[] {
  const endpoints = module.endpoints ?? [];
  let below: ReadonlySet<string> = new Set();
  return ladder.map((role) => {
    const reachable = endpoints
      .filter((endpoint) => allowedAt(endpoint, role.name))
      .map(describe);
    const keys = new Set(reachable.map((operation) => `${operation.kind}:${operation.label}`));
    const added = EMPTY_ADDED();
    for (const operation of reachable) {
      if (!below.has(`${operation.kind}:${operation.label}`)) added[operation.kind].push(operation);
    }
    below = keys;
    return {
      role: role.name,
      rank: role.rank,
      reachable,
      added,
      addsNothing:
        added.read.length === 0 && added.write.length === 0 && added.delete.length === 0,
    };
  });
}

/**
 * The pane's rows, in ladder order, for every module the model describes.
 *
 * Modules that refuse assignment are **kept**, not filtered. A module missing from the pane is
 * a question an administrator cannot stop asking; one that is present and says "never
 * assignable, because administering grants hands out every other authority" answers it. The
 * reason is the useful part, which is why the declaration requires one.
 */
export function buildModuleRows(model: AccessModel): ModuleRow[] {
  const ladder = [...model.roles].sort((a, b) => a.rank - b.rank);
  return model.modules.map((module) => ({
    name: module.name,
    label: module.access?.label ?? module.name,
    assignable: module.access?.assignable ?? false,
    platformReason: module.access?.platform_reason ?? null,
    rungs: buildRungs(module, ladder),
    permissions: module.permissions ?? [],
    unexplainedRoutes: (module.endpoints ?? []).filter(
      (endpoint) => endpoint.operation === null || endpoint.operation === undefined,
    ).length,
  }));
}

/**
 * The value of the "no access" tile, which is a real tile rather than an option buried in a
 * menu — so revoking is exactly as reachable as granting, and the strip biases downward
 * instead of upward.
 *
 * The empty string, deliberately: no declared rung can carry it, so it cannot collide with a
 * role name, and `value === NO_ACCESS` is the same test as "no rung selected".
 */
export const NO_ACCESS = "";
