import type { Action } from "@terpjs/contract";

/**
 * The minimum backend role rank that may perform each coarse UI {@link Action}.
 * The default is the bundled viewer/editor/admin ladder (ADR 0004 / 0022); an app
 * overrides the thresholds for a different role model.
 */
export type RankThresholds = Record<Action, number>;

export const DEFAULT_RANK_THRESHOLDS: RankThresholds = {
  read: 10,
  write: 20,
  admin: 30,
};

/**
 * Whether a caller may perform `action`, at `roleRank` globally and optionally at
 * `moduleRank` inside the module in question.
 *
 * The effective rank is the **higher** of the two, which is what the server's guard computes
 * (ADR 0112): a per-module rung raises authority inside one module and never lowers it. Passing
 * the rung is what stops the UI disagreeing with the guard — without it a caller who may reach
 * a module *only* through a rung had the button hidden, so the interface refused what the server
 * would have allowed, and the control existed on one side of the wire only.
 *
 * This is the UI gate only; the backend independently enforces authorization on every request.
 */
export function canPerform(
  roleRank: number,
  action: Action,
  thresholds: RankThresholds = DEFAULT_RANK_THRESHOLDS,
  moduleRank?: number,
): boolean {
  const effective = moduleRank === undefined ? roleRank : Math.max(roleRank, moduleRank);
  return effective >= thresholds[action];
}
