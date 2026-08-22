/**
 * Stack-agnostic description of a module's UI surface (design §7.1, item 3).
 *
 * Decision: the manifest *types* are the shared contract (defined here), but each
 * frontend module authors its own manifest *values* — view names and navigation are
 * frontend concerns, so they are not emitted from the backend `ModuleSpec`. Each stack
 * ships a thin adapter that realises a manifest into its own router + sidebar (TanStack
 * Router for React, SvelteKit for Svelte). `role` references the app's backend role
 * names; the stack's auth adapter resolves a name to the backend role rank.
 */

/** A role name as understood by the app's backend (e.g. "viewer" | "editor" | "admin"). */
export type RoleName = string;

export interface ModuleRoute {
  /**
   * URL path the route mounts at, e.g. `/billing` or `/billing/:id`.
   *
   * Parameters are spelled the stack-agnostic way (`:id`) — each adapter translates
   * into its own router's dialect (`$id` for TanStack Router, `[id]` for SvelteKit).
   * The React adapter also accepts `$id` directly, which is what shipped before the
   * translation existed.
   */
  path: string;
  /** Stack-agnostic view identifier the adapter resolves to a component. */
  view: string;
  /** Minimum role required to see the route; omitted = any authenticated user. */
  role?: RoleName;
  /**
   * Also require this named permission grant — the caller must hold it in
   * `CurrentUser.permissions`.
   *
   * **ANDed with `role`**, and that is deliberately what the server does: a `Policy` carrying a
   * `Permission` enforces the permission's role floor *and* the grant, so a client checking
   * only one would disagree with the endpoint in one direction or the other. The same reasoning
   * the `Authorized` component's `permission` prop already records.
   *
   * Deliberately not a combinator. The server's own declaration is one ref per read and one per
   * write (`AuthzRef = Role | Permission | Roles`), so an any-of here could express a gate no
   * `Policy` can declare — and a client gate that cannot correspond to a server gate can only
   * drift from the endpoint it mirrors.
   *
   * A *display* and *routing* gate only; the server re-checks every request. Fails closed:
   * unknown or misspelled names are simply absent from the grant list, and an app that mounts
   * no grant capability has an empty list, which correctly hides everything that names one.
   */
  permission?: string;
  /**
   * Query-string keys this route reads, e.g. `["status", "page"]`.
   *
   * Declared for the same reason params are: the router is realised at runtime, so
   * nothing checks a search key either — and a list screen's filters live in the query
   * string, which is why *most* screens were the ones bypassing the typed navigation
   * seam entirely. `terp routes` emits these into the generated table, so navigating
   * with an undeclared key (or reading one) is a typecheck error.
   *
   * Values are `string | undefined` and nothing more: a query parameter is text, and
   * every key is absent until someone sets it. Parsing `page` into a number is the
   * screen's business — declaring the key is what stops it being a typo.
   */
  search?: string[];
}

export interface NavItem {
  /** Sidebar label. */
  label: string;
  /** Destination path; should match a {@link ModuleRoute.path}. */
  to: string;
  /** Icon identifier the stack maps to its own icon set. */
  icon?: string;
  /** Minimum role required to show the nav item. */
  role?: RoleName;
  /**
   * Also require this named permission grant — the caller must hold it in
   * `CurrentUser.permissions`.
   *
   * **ANDed with `role`**, and that is deliberately what the server does: a `Policy` carrying a
   * `Permission` enforces the permission's role floor *and* the grant, so a client checking
   * only one would disagree with the endpoint in one direction or the other. The same reasoning
   * the `Authorized` component's `permission` prop already records.
   *
   * Deliberately not a combinator. The server's own declaration is one ref per read and one per
   * write (`AuthzRef = Role | Permission | Roles`), so an any-of here could express a gate no
   * `Policy` can declare — and a client gate that cannot correspond to a server gate can only
   * drift from the endpoint it mirrors.
   *
   * A *display* and *routing* gate only; the server re-checks every request. Fails closed:
   * unknown or misspelled names are simply absent from the grant list, and an app that mounts
   * no grant capability has an empty list, which correctly hides everything that names one.
   */
  permission?: string;
  /**
   * Match the URL exactly rather than as a segment-aligned prefix.
   *
   * The default is the prefix, and that is the useful behaviour: a detail page under a section
   * keeps the section's tab lit, so `/records/123` leaves "Records" current. Set this where a
   * destination should own only itself — typically a landing page that also has children in the
   * nav, where the parent would otherwise stay lit on every child.
   *
   * It does not decide WHICH item is current when several match; that is a property of the set,
   * and the adapter resolves it by longest match. This only says whether this item is a
   * candidate at all.
   */
  exact?: boolean;
  /**
   * The {@link NavGroup} this item belongs to, by id.
   *
   * An item naming a group the app has not declared falls into the default headerless group
   * rather than disappearing, and that is the deliberate direction to fail. A group is declared
   * once by the **app**; the item is declared by a **module** that ships on its own schedule, so
   * an id with no declaration yet is the normal first-run state of a module the app has not
   * finished adopting. Silently dropping the link would hide a working screen and report nothing.
   */
  group?: string;
  /**
   * Sort key against the item's siblings inside its group.
   *
   * Absent is 0, so a positive number sorts below every unordered sibling and a negative one
   * above — CSS `order` semantics, which is the vocabulary this framework already speaks.
   * The sort is stable, so items that tie keep their declaration order and a manifest that
   * declares no order anywhere renders exactly as it does today.
   */
  order?: number;
}

/**
 * A named section of the primary navigation, declared once by the **app**.
 *
 * A group spans modules — a "Sales" group holds items contributed by several of them — so no
 * module can own its label or its position, and it is the one part of the navigation model that
 * cannot live on a module manifest. Items reference it by {@link NavItem.group}.
 *
 * Declaring groups is optional and additive: an app that declares none renders one flat,
 * unlabelled list, which is what every app renders today.
 */
export interface NavGroup {
  /** Referenced by {@link NavItem.group}. */
  id: string;
  /**
   * Rendered above the group's list.
   *
   * `null` renders **no label element at all** — a positioning-only group, which is how an app
   * places its otherwise-ungrouped items somewhere other than the end without inventing a
   * heading for them. Required rather than optional so that "no label" is a decision the
   * declaration states, not an omission.
   */
  label: string | null;
  /**
   * Sort key against sibling groups.
   *
   * Absent is 0 and the sort is stable, so groups that tie keep declaration order. The default
   * headerless group is **not** part of this sort: it is always emitted last. See
   * `groupNav` in `@terpjs/react-core` for why.
   */
  order?: number;
}

export interface ModuleManifest {
  /** Module name; matches the backend module / API prefix (e.g. "notes"). */
  name: string;
  routes: ModuleRoute[];
  nav?: NavItem[];
}

/** Identity helper that gives module authors full type-checking on a manifest literal. */
export function defineModuleManifest(manifest: ModuleManifest): ModuleManifest {
  return manifest;
}
