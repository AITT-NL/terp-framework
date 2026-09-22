import type { AdminRoleOption } from "./useAccessLadder";

export type { AdminRoleOption } from "./useAccessLadder";

/**
 * Resolve a rank to the label of the rung that carries it.
 *
 * The ladder is passed in rather than known here. This function used to build the ladder
 * itself, returning ranks `10 / 20 / 30` as literals — so an app that declared a fourth rung
 * got a three-rung admin UI, and one that re-ranked a tier got the wrong label, while ADR 0022
 * promised the role model belonged to the app rather than the framework. The rungs now come
 * from `useAccessLadder`, which reads them from the access model.
 *
 * A rank no declared rung carries still falls back to `rank N`: it means the record holds a
 * rank the app no longer declares, which is a real thing to say rather than a gap to paper
 * over — the same reasoning `terp grant list` uses when it marks a stale grant instead of
 * hiding it.
 */
export function adminRoleLabel(rungs: readonly AdminRoleOption[], rank: number): string {
  return rungs.find((option) => option.rank === rank)?.label ?? `rank ${rank}`;
}

/**
 * The rank a new-account form should start on: the least privileged rung the app declares.
 *
 * `null` while the ladder is still loading, which is what stops a form from defaulting to a
 * rank the app may not declare at all. The literal `10` it replaced was the packaged viewer
 * rank, and an app whose lowest rung is `5` would have been provisioning accounts one tier
 * above its own floor.
 */
export function lowestRank(rungs: readonly AdminRoleOption[]): number | null {
  return rungs.length === 0 ? null : rungs[0].rank;
}
