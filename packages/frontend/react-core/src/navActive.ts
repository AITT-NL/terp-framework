/**
 * Which navigation item is current — one predicate, owned here (ADR 0097 §6, amended in 4e).
 *
 * The framework had two notions of "active" and they disagreed. `ModuleNav` compared
 * `pathname === item.to` raw while the `Link` it rendered compared through the router, and the
 * sheet's own comment beside the rule said so and deferred the fix to "the navigation model" —
 * this file. The sidebar had no predicate at all: it took whatever the router put on the anchor.
 *
 * The part that decides the shape is not the comparison, it is **arity**. "At most one item is
 * current" is a property of the SET, and a router computes `isActive` per link with no knowledge
 * of siblings. So a nav listing `/settings` and `/settings/users` gets two links the router
 * considers active at `/settings/users`, two `aria-current="page"` attributes and two painted
 * tabs — a screen reader says "current page" twice and neither is wrong on its own terms. Per
 * item `exact` cannot fix it either: turn it on and `/settings/appearance`, a real route that is
 * not itself a nav item, lights nothing at all. Only something looking at every item at once can
 * pick one, which is why {@link activeNavPath} exists and why the shell calls it rather than
 * asking each link how it feels.
 *
 * The comparison itself deliberately mirrors the router's, so the two never disagree about a
 * single item — see `node_modules/@tanstack/router-core/dist/esm/path.js` for
 * `removeTrailingSlash` and `exactPathTest`, and the non-exact branch in
 * `@tanstack/react-router/dist/esm/link.js`. Reimplemented rather than imported because
 * `@terpjs/contract` and a future non-React adapter need the same rule, and neither can take a
 * TanStack dependency to get it.
 *
 * Search and hash are ignored on purpose. A nav tab's identity is its path: filtering a list
 * must not unhighlight the tab the user is standing on.
 */

/**
 * The router's own normalisation: collapse repeated slashes, then drop one trailing slash
 * (except from the root itself). `cleanPath` and `removeTrailingSlash` in router-core, in that
 * order.
 *
 * The collapse is load-bearing rather than defensive tidying, and it is what removes a special
 * case rather than adding one. `/` has length 1, so the segment-boundary test below asks whether
 * `current[1]` is a slash — which is true for exactly one shape, `//foo`, and would let the root
 * item claim it. The router never produces that (`router.js:210` collapses on the way in), but
 * `activePath` is a plain string prop and the shell cannot assume its caller went through
 * TanStack: `window.location.pathname` does not. Normalising both operands the way the router
 * does makes the root behave exactly with no rule of its own — an earlier draft special-cased
 * `target === "/"` and justified it with `/profile`, which the boundary test already rejects.
 */
function normalise(path: string): string {
  const collapsed = path.replace(/\/{2,}/g, "/");
  return collapsed.endsWith("/") && collapsed !== "/" ? collapsed.slice(0, -1) : collapsed;
}

/**
 * Whether `to` matches `pathname` on its own — the per-item half of the predicate.
 *
 * `exact` compares normalised equality; otherwise it is a **segment-aligned** prefix, so
 * `/settings` matches `/settings/users` but not `/settings-users`. Both operands are normalised
 * in **both** branches, which the router also does and which an earlier draft of this rule
 * attached to the exact branch only.
 *
 * The root needs no special case: `/` matches another path only when that path's second
 * character is a slash, and {@link normalise} has already collapsed those away.
 *
 * A `to` that does not begin with `/` is never active, and that is a guard rather than
 * tidiness: the router resolves a relative or empty `to` against the *current* location, so
 * `to: ""` produces a link that always points at the current page — and a raw prefix test would
 * light every item in the sidebar at once, since every path starts with the empty string.
 */
export function isNavItemActive(pathname: string, to: string, exact = false): boolean {
  if (!to.startsWith("/")) {
    return false;
  }
  const current = normalise(pathname);
  const target = normalise(to);
  if (exact) {
    return current === target;
  }
  return (
    current.startsWith(target) &&
    (current.length === target.length || current[target.length] === "/")
  );
}

/** The shape {@link activeNavPath} needs from an item: where it goes, and how it matches. */
export interface NavActiveCandidate {
  to: string;
  exact?: boolean;
}

/**
 * The `to` of the one item that is current, or `undefined` when none is.
 *
 * **Longest match wins**, and that single rule replaces two special cases. Two items where one
 * path prefixes the other resolve to the deeper one, so exactly one is ever current. A URL below
 * a nav item still lights its parent, so `/settings/appearance` keeps `/settings` lit rather
 * than emptying the sidebar.
 *
 * It also retires the hand-written `exact: item.to === "/"` the router adapter used to carry.
 * That flag was there because `/` prefixes every path — but only as a STRING, and
 * {@link isNavItemActive} matches on segments, so `/` claims nothing but itself regardless.
 * The adapter was working around a prefix test it did not have.
 *
 * Ties are impossible: two items can only both match at the same length if their normalised
 * paths are equal, in which case the first wins and they were the same destination anyway.
 */
export function activeNavPath(
  pathname: string,
  items: readonly NavActiveCandidate[],
): string | undefined {
  let winner: string | undefined;
  let longest = -1;
  for (const item of items) {
    if (!isNavItemActive(pathname, item.to, item.exact)) {
      continue;
    }
    const length = normalise(item.to).length;
    if (length > longest) {
      longest = length;
      winner = item.to;
    }
  }
  return winner;
}
