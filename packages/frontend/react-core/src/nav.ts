import type { ModuleManifest, NavItem } from "@terpjs/contract";

/**
 * What a manifest's declared visibility is resolved against.
 *
 * Built from what `/me` actually returns, which is the whole reason this type is two fields and
 * not four. ADR 0097 §5 specified a context of module grants, per-module role ranks, superuser
 * and internal-versus-external; `CurrentUser` carries none of them. It carries `role_rank`,
 * `role_name` and `permissions`, and the last of those is the general mechanism the decision
 * never named. A context built from what is real is honest; one built from that list would be
 * vocabulary with no source behind it.
 */
export interface NavVisibilityContext {
  /** Whether the caller clears a named role's floor — the existing `role` gate, unchanged. */
  canSeeRole: (role: string | undefined) => boolean;
  /**
   * The caller's named grants, from `CurrentUser.permissions`.
   *
   * Empty when signed out and empty for an app that mounts no grant capability, which is what
   * makes the gate fail closed in both cases rather than failing open in the second.
   */
  permissions: readonly string[];
}

/**
 * Whether one declared item is visible to the caller.
 *
 * `role` and `permission` are **ANDed**, which is deliberately what the server does: a `Policy`
 * carrying a `Permission` enforces the permission's role floor *and* the grant, so a client that
 * checked either alone would disagree with the endpoint in one direction or the other. It is the
 * same composition `Authorized` already ships, and reusing it means the navigation gains the gate
 * the buttons already have rather than a second vocabulary for the same idea.
 *
 * Exported because routes need it too. A nav-only gate would hide the link and leave the route
 * reachable by URL — `role` has never had that asymmetry, since it is declared on both
 * `NavItem` and `ModuleRoute`, and `permission` must not introduce one.
 */
export function isDeclarationVisible(
  declaration: { role?: string; permission?: string },
  context: NavVisibilityContext,
): boolean {
  if (!context.canSeeRole(declaration.role)) {
    return false;
  }
  return (
    declaration.permission === undefined ||
    context.permissions.includes(declaration.permission)
  );
}

/**
 * Flatten the nav of every module manifest into one ordered sidebar list, keeping only the items
 * the current user may see.
 *
 * The context is a **required** argument, and that is a breaking change taken on purpose. Making
 * it optional would have been source-compatible and silently wrong: an existing two-argument
 * caller would fail closed on every item that gained a `permission`, removing links from a
 * sidebar with no error anywhere. A required parameter turns that into a typecheck error at the
 * one call site each app has.
 */
export function visibleNav(
  manifests: readonly ModuleManifest[],
  context: NavVisibilityContext,
): NavItem[] {
  return manifests
    .flatMap((manifest) => manifest.nav ?? [])
    .filter((item) => isDeclarationVisible(item, context));
}
