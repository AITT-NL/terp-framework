# 0124 — A capability publishes its operation set, and an app folds it in

- **Status:** Accepted and implemented. Every capability that declares operations publishes
  `<CAP>_OPERATIONS`, the template and the example app fold each capability in by splatting
  that set, the aggregate is held exhaustive against its module by
  `tests/architecture/test_capability_operations.py`, and the boot refusal now tells a
  missing entry apart from a same-id shadow.
- **Date:** 2026-09-08
- **Relates:** [ADR 0102](0102-route-operations-are-declared.md) (a route declares what it
  does; the catalog, the no-drift guarantee and the coverage dial this amends),
  [ADR 0121](0121-a-module-role-is-an-assignment-not-a-policy.md) (the release that added
  four routes to a capability and surfaced this),
  [ADR 0008](0008-event-bus-catalog-and-typed-emit.md) (the event catalog this pattern is modelled
  on), [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md) (why the definition carries an
  id and a label and nothing else)

## Context

[ADR 0102](0102-route-operations-are-declared.md) gave every route a declared operation and
put the one catalog those declarations are checked against in the app's control plane. That
split is deliberate and stays: the catalog is the *app's* statement about what the app does,
so a capability cannot reach into it, and a capability therefore declares its operations
inside its own package and re-exports the constants.

What was missing is the join. An app folded a capability in by naming its operations one at
a time, which makes the app's control plane an inventory of somebody else's router — a list
of facts the app neither owns nor can see change. So the two halves drifted the moment a
release touched a capability's routes.

The drift is not a warning. `create_app` refuses a route that declares an operation the
catalog does not carry, and that check is **unconditional** — it sits above the coverage
dial, because the no-drift guarantee is the half of ADR 0102 that was never meant to be
tunable. An app with `coverage=OFF` is refused just as an app with `STRICT` is. This is
worth stating plainly because the failure reads like a strict-coverage problem and is not
one: turning coverage down does not avoid it.

Observed at 0.19.0. [ADR 0121](0121-a-module-role-is-an-assignment-not-a-policy.md) added
four routes to the `access` capability, each declaring its operation. Every app that mounted
that capability and had folded the previous three operations in by name was refused at boot
on upgrade, and the repair was to read the capability's source, find the four new constants
and copy their names across. That repair is not one an app can be expected to perform: it
requires knowing a capability's internal route inventory, which is precisely the thing the
package boundary exists to keep private.

## The decision

**Each capability publishes the operation set its routes declare, and an app folds the
capability in by splatting that set.**

```python
from terp.capabilities.access import ACCESS_OPERATIONS
from terp.capabilities.auth import AUTH_OPERATIONS

operation_catalog = OperationCatalog(
    operations=(*AUTH_OPERATIONS, *ACCESS_OPERATIONS, NOTES_LIST, ...),
    coverage=OperationCoverage.STRICT,
)
```

Three parts make that a fix rather than one more list to forget:

1. **`<CAP>_OPERATIONS` is a tuple on the capability's public surface**, in the order
   its module declares them, and is what an app references. It grows when the capability's router grows, so the app's
   catalog grows with it and no app edit is needed for a release that adds a route.
2. **The aggregate is held exhaustive**, in both directions, by
   `tests/architecture/test_capability_operations.py`: every `OperationDefinition` the
   capability's `operations.py` declares is in the set, and the set names nothing the module
   does not declare. Enumeration is parametrized off the source tree, so a capability that
   starts declaring operations is covered without an edit to the test. Without this the
   aggregate would be a second list to keep in sync — the same burden it removes, one
   indirection further away.
3. **The boot refusal says which repair applies.** `OperationCatalog.entry_for` distinguishes
   an id the catalog never registered from an id it registered with different wording, and
   the two get different messages. The first names the set to splat (derived from the
   operation id's own prefix) and says the refusal is coverage-independent; the second quotes
   both wordings, because a shadow is the route's declaration to fix and folding a capability
   in would not fix it. One message serving both cases sent readers of the first case looking
   at the second.

No new API on `OperationCatalog` is required for the fold itself: a splat is a language
feature, and `operations=` already takes a sequence.

## Consequences

- A capability release that adds a route is no longer potentially boot-breaking for the apps
  that mount it, at any coverage level.
- `<CAP>_OPERATIONS` is public surface. Adding an operation to a capability is additive for
  consumers; removing one is a breaking change and belongs in a release note as such.
- The template's catalog drops from 35 named constants to 8 splats, and the example app's
  from 45 to 9. Both now read as "these capabilities, plus this app's own modules", which is
  the sentence the file was always trying to be.
- `entry_for` returns to the catalog's surface. ADR 0102 removed `has_id`/`get`/`ids` as
  readerless and said they would come back with the consumer that needs them; the boot
  message is that consumer, and it is the only caller.
- An app is still free to name individual operations. Nothing forces the splat — an app that
  deliberately mounts a capability's router partially, or wants a narrower catalog, keeps the
  enumerated form and its maintenance cost.

## Alternatives rejected

**`OperationCatalog.include_capability(...)`.** The shape first asked for. It puts knowledge
of capabilities into `terp.core`, which sits below them — the keystone rule runs the other
way. It also buys nothing over a splat: the catalog would still be handed a sequence of
definitions, just through a method that has to be told which capability, by a caller that
already imported it.

**Auto-discovery: the catalog fills itself from the mounted capabilities.** Attractive, and
wrong for this feature. The catalog is the app's own statement of what it does, and the
declaration being explicit is what makes it reviewable — an app would no longer be able to
read one file and see every operation it serves. It also cannot work in the direction
needed: `create_app` receives the specs, but the catalog is constructed before it, in the
app's control plane, by code that has no view of what will be mounted. Deferring catalog
construction to boot would move a declaration into a runtime, which ADR 0102 §5 refuses.

**Downgrade the refusal to a report.** Also asked for, and it treats the symptom. The
no-drift check is the guarantee that a route cannot present an operation the catalog never
registered; making it a warning means a view can render an operation label that no catalog
documents, which is the drift the catalog exists to prevent. The right move is to make
compliance cheap enough that the guarantee costs nothing, which is what the aggregate does.
`terp check` reporting new capability operations ahead of an upgrade remains a reasonable
separate addition — it is a nicety once the boot no longer breaks, not a substitute for
fixing the join.

**Ship the operations as data (JSON) beside each capability.** Would make the set readable
without importing the package, which is the one real advantage — the enumerated-import
failure mode where an app imports a capability it does not install (see the note at the foot
of the example app's catalog) is unaffected by this ADR either way. Rejected as a larger
change than the problem needs: it introduces a second declaration format and a loader for
it, and the constants are already the referenced identity at every route.
