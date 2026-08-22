import type { ModuleManifest, NavGroup, NavItem } from "@terpjs/contract";

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

/**
 * One rendered section of the primary navigation: a declared {@link NavGroup} with the items that
 * named it, or the default headerless group with everything that named nothing.
 *
 * The group is flattened into `id` and `label` rather than carried whole, and that is what lets
 * one shape describe both cases. The default group has no declaration to carry — it is not a
 * `NavGroup` an app wrote, it is the absence of one — so a section holding an optional `NavGroup`
 * would force every reader through `section.group?.label` to ask a question that has the same
 * answer either way: what, if anything, do I render above this list.
 */
export interface NavSection {
  /** The declared group's id, or `null` for the default headerless group. */
  id: string | null;
  /** The label to render above the list, or `null` when the section renders none. */
  label: string | null;
  items: NavItem[];
}

/** Stable ascending sort on `order ?? 0` — see {@link groupNav} for why absent is 0. */
function byOrder<T extends { order?: number }>(values: T[]): T[] {
  return values.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
}

/**
 * Arrange visible nav items into the app's declared groups.
 *
 * Groups fix the defect ADR 0097 names in its own Context: sidebar order is "an accident of
 * `import.meta.glob` key order", because the sidebar is one flat list flattened out of whatever
 * sequence the module manifests happened to arrive in. A group spans modules, so no module can
 * own one — the app declares them, modules reference them by id, and this function is where the
 * two halves meet.
 *
 * **Additive by construction.** An app that declares no groups gets exactly one section holding
 * exactly the items it passed in, in the order it passed them: `groups` defaults to empty, every
 * item falls into the default bucket, and a stable sort over keys that are all 0 is the identity.
 * That is not an argument that it *should* be additive — it is the code path, and the shell
 * renders the same list it renders today.
 *
 * Four rules, and each one is a decision:
 *
 * **An unknown group id falls into the default bucket rather than dropping the item.** A group is
 * declared by the app; the item is declared by a module that ships on its own schedule. An id
 * with no declaration yet is therefore the ordinary state of a module the app has not finished
 * adopting, not a corruption — and the two ways to be wrong are not symmetric. An ungrouped link
 * is in the wrong place and works; a dropped link is a screen the user cannot reach, with nothing
 * anywhere saying why. Nothing warns about it either: this is a state the design calls normal,
 * and a diagnostic for a normal state is noise that teaches people to ignore diagnostics.
 *
 * **A section with no items is not emitted.** Reachable on the first render of any app that
 * groups the packaged admin entry's neighbours: `/admin` declares `role: "admin"`, so
 * {@link visibleNav} removes it for everyone else and a group holding only it is left empty. A
 * label over a void is worse than no label, because it names a place the user is being refused
 * and cannot see.
 *
 * **The default bucket is emitted LAST, and it is not part of the group sort.** This is the rule
 * that changed under review, and the case that decided it is the one case every app has. The
 * packaged admin area is appended after the app's own manifests, so its nav entry renders last
 * today. Emit the default bucket first and that entry — which no app authors and therefore no app
 * can annotate with a `group` — jumps to the top of the sidebar the moment the app declares its
 * first group. Emitting last leaves it exactly where it already is. It also puts an item naming
 * an undeclared group at the bottom rather than above the app's own structure, which is the
 * better place for a fail-open result to surface.
 *
 * The trade is real and is worth stating: an app that groups a *minority* of its items sees the
 * ungrouped majority sink below them. That is app-authored, visible on the first render, and
 * fixed in one line by declaring `{ id: "main", label: null, order: -1 }` and pointing those
 * items at it — a group with a `null` label renders no heading, so it is pure positioning. The
 * admin case has no such fix, which is what makes it decisive rather than merely also true.
 *
 * **Absent `order` is 0, everywhere, and the sort is stable.** Not `Infinity`: a single numbered
 * item would then leap above an entire unnumbered list, which breaks the additivity the rest of
 * this function is built on. Absent-is-0 is CSS `order` semantics exactly — positive sorts below
 * its unordered siblings, negative above — which is the vocabulary a framework styled in tokens
 * already speaks, and it means a manifest that numbers nothing is untouched.
 *
 * A duplicate group id is not an error here: the first declaration wins and the second is
 * inert, so this function stays total and a render can never throw. `buildAppRouter` refuses the
 * duplicate at composition time instead, where an authoring error belongs and where it can be
 * reported once rather than on every frame.
 */
export function groupNav(
  items: readonly NavItem[],
  groups: readonly NavGroup[] = [],
): NavSection[] {
  // First declaration wins. A Map also gives the declared ids an O(1) membership test, which is
  // what separates "this item names a real group" from "this item falls open".
  const declared = new Map<string, NavGroup>();
  for (const group of groups) {
    if (!declared.has(group.id)) {
      declared.set(group.id, group);
    }
  }

  // `null` keys the default bucket. It cannot collide with a declared id: an id is a string, and
  // the empty string — which is a legal id and would collide with any falsy sentinel — is a
  // distinct Map key from null.
  const buckets = new Map<string | null, NavItem[]>([[null, []]]);
  for (const id of declared.keys()) {
    buckets.set(id, []);
  }
  for (const item of items) {
    const key = item.group !== undefined && declared.has(item.group) ? item.group : null;
    buckets.get(key)!.push(item);
  }

  const sections: NavSection[] = [];
  for (const group of byOrder([...declared.values()])) {
    const bucket = buckets.get(group.id)!;
    if (bucket.length > 0) {
      sections.push({ id: group.id, label: group.label, items: byOrder(bucket) });
    }
  }
  const ungrouped = buckets.get(null)!;
  if (ungrouped.length > 0) {
    sections.push({ id: null, label: null, items: byOrder(ungrouped) });
  }
  return sections;
}
