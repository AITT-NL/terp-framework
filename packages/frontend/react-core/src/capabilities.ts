import type { Action } from "@terp/contract";

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
 * Whether a caller with `roleRank` may perform `action` under `thresholds`. This is the
 * UI gate only; the backend independently enforces authorization on every request.
 */
export function canPerform(
  roleRank: number,
  action: Action,
  thresholds: RankThresholds = DEFAULT_RANK_THRESHOLDS,
): boolean {
  return roleRank >= thresholds[action];
}
