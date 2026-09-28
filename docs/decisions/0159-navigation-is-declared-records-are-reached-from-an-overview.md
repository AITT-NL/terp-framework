# 0159 — Navigation is declared; records are reached from an overview

- **Status:** Accepted, option 3 (2026-09-28). Navigation stays declared, and records are
  reached from an overview. Nothing is built. Option 2 stays open behind its own evidence. See
  the Decision section at the end. The fork and the recommendation are kept as the record of
  what was weighed.
- **Date:** 2026-09-27
- **Relates:** [ADR 0097](0097-shell-parameters-and-ordered-navigation.md) §5 (navigation is
  ordered groups declared by the app, items declared by modules, and a predicate on the
  manifest cannot exist),
  [ADR 0092](0092-typed-route-params.md) (routes generated from the manifests),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md)

---

## Context

App building on Terp reported that navigation cannot be data-driven. The sidebar lists what
the modules declare. An app whose main objects are records it holds — one entry per project,
per account, per running job — cannot put those records in the sidebar.

What a `NavItem` is today decides most of this. It lives on the stack-agnostic manifest in
`@terpjs/contract`: a label, a target, an icon, and a role and permission ANDed and resolved
against what `/me` returns. ADR 0097 §5's amendment already refused a function on it, because
the manifest is serialisable and emitted by a generator, and a function survives neither.
Route types are generated from the same manifests (ADR 0092). Navigation is data the build can
read.

## The fork

1. **Runtime nav items.** A module supplies a hook or an endpoint whose results become
   sidebar entries. This breaks the property 0097 kept: the sidebar would no longer be
   readable from the manifest, route-type generation would not see the targets, and the
   role and permission gate would have to be re-derived per record at runtime, for every
   item, on every render.
2. **A declared item with a data-bound decoration.** The item stays declared. Only something
   like a count or a status next to it comes from data (ADR 0097 §5 already names `badge`).
   Navigation keeps its shape, and the data sits beside it rather than making it.
3. **Decline, and name the pattern.** Records are reached from an overview. A module declares
   one nav item for the collection. Its page is a `DataView` or a `HubPage` of the records,
   and each record has a parameterised detail route that the generator types. The overview is
   the one place the whole set is visible, searchable and sortable.

## Recommendation

**Option 3, keeping option 2 open behind its own evidence.**

- **A sidebar that grows with the data does not scale.** It is fine at three records and
  unusable at forty: the navigation pushes out everything else, and the only way to find one
  record is to scroll a list with no search.
- **An overview answers the question the sidebar was asked to answer.** "What do I have, and
  how is each one doing?" needs one view of the whole set. A list of links gives one record
  at a time and no comparison.
- **The ideology refuses the second pattern.** Records already have one way to be listed,
  searched and opened: `DataView` and a detail route. Sidebar entries would be a second way
  that does all three worse, and they would break the manifest's serialisability, which
  other tools rely on.

Option 2 stays open because it does not change what navigation *is*. A declared item that
shows a count ("Review · 3") keeps every property above. But the report asked for records in
the navigation, not counts beside it, so option 2 is not what was requested and needs its own
evidence.

## What would change this

- Two independent reports of an app needing quick access to a *few* specific records — pinned
  or recently opened — would argue for a shell affordance for exactly that. It would still be
  declared and still be bounded, and it would not list the whole set.
- A report of a declared item needing a live count or status argues for option 2.

## Decision (2026-09-28): navigation stays declared

**Option 3, as recommended.** A `NavItem` stays declared data on the manifest, and records are
reached from an overview: one declared item for the collection, a `DataView` or a `HubPage` of
the records, and a parameterised detail route per record that the generator types. Nothing is
built, because every part of that pattern ships today. A sidebar entry per record is declined.

The reasons are the three the recommendation gave. A sidebar that grows with the data is fine
at three records and unusable at forty. An overview answers "what do I have, and how is each
one doing?", which a list of links cannot. And records already have one way to be listed,
searched and opened, so sidebar entries would be a second way that does all three worse, and
would break the manifest's serialisability, which route generation relies on.

**Option 2 is open, and it is not built.** A declared item with a data-bound decoration — a
count or a status beside it, as in "Review · 3" — keeps every property ADR 0097 §5 holds,
because the item stays declared and only the decoration comes from data. But the report asked
for records in the navigation, not for a count beside an item, so nothing yet asks for option
2. The second bullet under "What would change this" is the evidence that builds it. The first
bullet, quick access to a few pinned or recently opened records, is a separate shell affordance
with its own bar of two reports, and it would still list a bounded few rather than the whole
set.
