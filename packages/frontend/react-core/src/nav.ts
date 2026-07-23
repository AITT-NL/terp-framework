import type { ModuleManifest, NavItem } from "@terpjs/contract";

/**
 * Flatten the nav of every module manifest into one ordered sidebar list, keeping only
 * the items the current user may see. `canSeeRole(role)` decides visibility for an item's
 * required role (an item with no `role` is visible to any authenticated user).
 */
export function visibleNav(
  manifests: readonly ModuleManifest[],
  canSeeRole: (role: string | undefined) => boolean,
): NavItem[] {
  return manifests.flatMap((manifest) => manifest.nav ?? []).filter((item) => canSeeRole(item.role));
}
