# 0130 — An app's own operations live outside the catalog the template owns

- **Status:** Accepted and implemented. The template seeds
  `control_plane/app_operations.py` (in `_skip_if_exists`) exporting an empty typed
  `APP_OPERATIONS`, and `control_plane/operations.py` splats it. Held by
  `tests/architecture/test_template.py`.
- **Date:** 2026-09-09
- **Relates:** [ADR 0126](0126-a-capability-publishes-its-operation-set.md) (the upgrade
  this completes — a capability publishes its set so an app folds it in by splatting),
  [ADR 0102](0102-route-operations-are-declared.md) (the catalog and why it belongs to
  the app), [ADR 0039](0039-scaffolding-cli-and-copier-template.md) (what the template
  owns and what it merely seeds)

## Context

ADR 0126 set out to make an upgrade that "needs no edit at all" for the operation
catalog: a capability publishes `<CAP>_OPERATIONS`, the app splats it, and a release
that adds a route no longer refuses the app's boot.

The mechanism delivering that promise handed out a merge conflict in the very file the
promise was about. `control_plane/operations.py` is template-owned — which is
deliberate and worth keeping, because it is how a corrected folding rule, a new
capability or a better explanation reaches an existing app at all. But the template's
own docstring told the author to declare the app's operations *there*, next to the
capabilities. So the file contained two halves with opposite ownership, and every
`copier update` conflicted in it for any app with routes of its own — which is every
app past its first day.

Reported from an upgrade across several releases: the three-way merge did the useful
half (it converted the capability imports to the published sets) and still left the
app's own block to be reconstructed by hand.

`pyproject.toml` has the same shape and is discussed below.

## Decision

**The app's half moves to `control_plane/app_operations.py`,** seeded once by the
template, listed in `_skip_if_exists`, exporting a typed `APP_OPERATIONS` tuple that
starts empty. `control_plane/operations.py` imports it and splats it into the catalog
beside the capability sets — the same folding rule, applied to the app itself.

**The catalog stays template-owned.** The alternative was to make `operations.py` the
app's file. That removes the conflict too and costs the thing the split is protecting:
a release could never again correct the folding rule, add a mounted capability or
improve that docstring in an existing app. It would trade a visible conflict for silent
staleness, which is the worse of the two failures and the one this repository already
complains about elsewhere.

**The seeded file passes copier's own test for the list it joins.** `copier.yml` asks
whether the template's copy is a *stub that would destroy real content*, not merely
whether an app edits the file. An empty tuple is exactly that: restoring it un-declares
every operation the app has, and a `STRICT` catalog then refuses the boot of the app's
own routes — a total failure with nothing in the diff to explain it.

**Verified with copier, not by reasoning.** A rendered app was given one edit in each
half and re-rendered. Copier reports `skip` for `app_operations.py` and `overwrite` for
`operations.py`: the app's declaration survives, the template's half is delivered
fresh. The repository's test asserts the structure that makes that true, because
rendering needs copier and a network.

## Consequences

An existing app adopts this by moving its own `OperationDefinition` constants into
`app_operations.py` and leaving the splat. Until it does, nothing breaks — its
operations still work where they are; they just keep conflicting on every re-render.

**`pyproject.toml` is left as it is, and that is a decision rather than an omission.**
It has the same two-owner shape: the template owns the file and pins the lockstep, and
the app adds its own dependencies to it. But PEP 621 has no include mechanism, and the
candidate workaround — declaring the terp packages unpinned and moving the exact pins
into a template-owned constraints file — costs `pyproject.toml` its standing as the one
place the app's dependencies are declared, which `deptry`, the package-graph check and
now the lockstep gate all read. A predictable conflict in a manifest is cheaper than a
manifest that no longer answers the question. What was missing was saying so, which the
upgrade recipe now does: expect the conflict, keep your dependencies, take the
template's pins.

**`apps/example` keeps its operations in `operations.py`.** It is not rendered from the
template, so it has no conflict to fix, and moving twenty constants would be diff
without a behaviour change. The shape a reader should copy is the one a rendered app
has, which is what the template now ships.
