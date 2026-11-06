# `backend/references_declare_delete_behaviour`

**Every stored reference declares what a delete of its target does, and can do it**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/references_declare_delete_behaviour.json`.

## Why this rule exists

A foreign key has a referential action whether or not anyone chose one: SQL supplies NO ACTION when nobody does, and the action you get by not choosing is indistinguishable in the source from the action you chose. A reader cannot tell a deliberate "the database takes no action here, the owning service handles this" from an oversight, and neither can a reviewer. Declare the behaviour on the column, so the decision is explicit, greppable and reviewable. The standard deliberately does NOT prefer an action: which one is correct is a property of what the reference means -- delete-with-parent for a component of its parent, refuse-the-delete for something the parent must not vanish underneath, blank-the-pointer for a reference allowed to go slack -- so every action is accepted, including the explicit form of the SQL default, and only the naming is enforced. Second condition: an action that cannot fire is not a declaration but a belief. Where the platform makes a delete a lifecycle stamp rather than a row removal (a soft-delete trait), no DELETE statement ever reaches the constraint, so every action whose value depends on firing is dead code against such a target -- delete-with-parent, blank-the-pointer and point-at-the-default alike, worst in the blank-the-pointer case, where the referencing rows keep a live pointer to a row that row-scoping now hides from every read, so the reference reads as broken rather than absent. The dividing line is not passive versus active: refuse-the-delete and explicit-no-action are accepted because they only ever described the hard-delete path, which nothing but an out-of-band deletion can reach. Against such a target, declare one of those as the backstop and perform the lifecycle cascade in the owning service.

## How Terp realises this

Ref(target, on_delete=OnDelete.<ACTION>) from terp.core declares the column, with on_delete as a required keyword so a missing decision is a TypeError where the model is defined; OnDelete offers CASCADE / RESTRICT / SET NULL / SET DEFAULT / NO ACTION. OnDelete.NO_ACTION is a full answer and emits no ON DELETE clause, so adopting the declaration on an existing schema needs no migration. SQLModel's own Field(foreign_key=..., ondelete=...) and a hand-built ForeignKey(..., ondelete=...) also count as declarations. terp.core.assert_references_declare_delete_behaviour audits live SQLAlchemy metadata for a consumer's own test suite. Recipe: terp guide references (ADR 0133).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-references-declare-delete-behaviour: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Not yet — a runtime control is planned; the gap is explicit and tracked.
- `build-time`: `terp.arch` — `check_references_declare_delete_behaviour`
