# 0173 — A breadcrumb keeps what it knows

- **Status:** Accepted and implemented (2026-10-05). `Breadcrumbs` takes a pending label (`null`),
  `Page`'s `title` may be `null`, and the router's shell holds the trail's memory
  (`trailMemory.ts`). Held by `Breadcrumbs.test.tsx` ("a trail that keeps what it knows") and
  `admin.test.tsx`, which goes through the real router.
- **Date:** 2026-10-05
- **Relates:** [ADR 0169](0169-a-page-is-composed-from-the-shape-of-its-data.md) and
  [ADR 0135](0135-the-page-band-spends-a-second-row-only-when-one-is-earned.md) (the page band
  whose leaf is the title), [ADR 0079](0079-slot-typed-layout-contracts.md) (the archetype frame
  every routed view renders)

---

## Context

The owner, using apps built on the framework: switching pages, the breadcrumb "reloads and
flashes", including when switching tabs on a content page. One level deeper, "it only has to add a
section".

Every routed view mounts its own `Page`, so the trail is built again on every navigation. What
the reader sees change is the labels that come from data. A detail page's title is its record's
name, and the record is read again on every mount. The framework's own admin screens titled
the page with the parent's name until it arrived (`record?.email ?? strings.adminUsers`). So
opening a user read "Admin › Users › Users" and then "Admin › Users › jane@…". A detail with
tabs as routes did it on every tab. A child page one level down did it to its parent crumb,
whose name only the child's read could supply. The crumbs were also keyed by their text, so a
label arriving replaced the crumb rather than changing its words.

## Decision

1. **A label not known yet is `null`, never a stand-in.** `BreadcrumbItem.label` and `Page`'s
   `title` accept `null` (and read `""` the same way). The pattern is `record?.name ?? null`. A
   stand-in such as the parent's name is a wrong title for as long as it shows, and is then
   replaced, which is the flash.
2. **The trail remembers what it said at each path.** The router's shell holds one map of path
   to label for the app's lifetime. Each routed view binds it to the path *its own match* is at
   (`useMatch`), and `Breadcrumbs` writes every known label under its crumb's path: an ancestor's
   `to`, or the leaf's own path. A pending crumb shows the last label at its path. So a tab of a
   detail, a return to it, and the parent crumb one level down all show the name already known,
   and nothing changes when the read lands.
3. **Only a place never seen shows a placeholder**: a quiet bar of fixed width, read as the
   framework's "Loading" string, with `aria-busy` on the heading. A pending ancestor is not a link
   until it has words.
4. **A crumb is keyed by its position.** A label that arrives is the same crumb with new words.
   Going one level deeper keeps every crumb before it and adds one.

Bound to the view's own match and not to the router's location, and the difference was
measured. During a navigation the old page is still rendered while the location is already the
new one. A leaf keyed by the location remembered the page being left ("Users") under the path
being opened, and the detail then recalled its parent's name as its own.

Outside a Terp router there is no memory: a pending crumb is the placeholder, and nothing else
changes.

## Consequences

- An app titling a detail page from its record should pass `null` while it loads. One that keeps
  a stand-in keeps the flash, because the stand-in is a known label and is shown as one.
- Paths are compared without query or fragment and without a trailing slash, so `/orders/7?tab=a`
  and `/orders/7/` are the same place.
- The memory is per app session and unbounded. It holds one short string per place visited. A
  label that changes, such as a renamed record, is replaced the moment the new one is shown.
- Two style markers join the inventory: `breadcrumbs-pending` and its visually hidden
  `breadcrumbs-pending-text`.

## Alternatives considered

**Move the band into the shell, so it never unmounts.** That would keep the very DOM nodes
across navigations. But the band is part of `Page`: its actions, badges and lead line are the
page's, and the archetype frame (ADR 0079) is checked on the page. Splitting it across the shell
and the page would trade a remount that paints identical pixels for a band with two owners. With
the labels known, the remount is invisible.

**Keep the previous page's trail until the new title arrives.** That shows the wrong page's title
under the new page, which is the same defect as the stand-in.
