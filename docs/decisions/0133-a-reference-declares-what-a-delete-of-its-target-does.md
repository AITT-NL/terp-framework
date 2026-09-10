# 0133 — A reference declares what a delete of its target does

- **Status:** Accepted
- **Date:** 2026-09-10
- **Relates:** [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md) (the opinionation
  policy this reads as "enforce the decision, not the choice", and the home of the
  optimistic-concurrency contract — the *concurrency* half of the same question),
  [ADR 0010](0010-soft-delete-trait-and-no-manual-scope-filtering.md) (the trait that makes
  a delete a stamp, and therefore makes some referential actions unreachable),
  [ADR 0057](0057-files-storage-profiles-and-references.md) (`FileRef` — the
  declared-reference shape this copies),
  [ADR 0084](0084-runtime-applicability-classification.md) (the `runtime.applicability`
  classification this entry has to justify),
  [ADR 0090](0090-a-table-has-one-owning-history.md) (cross-package references and the
  migration ordering they imply),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (why this enforces
  the *decision* and not the choice),
  [ADR 0122](0122-the-catalog-is-frozen-at-its-breadth-and-grows-in-legibility.md) (the
  evidence test a new rule has to clear, argued in §6).

---

## Context

Terp has a complete answer for two of the three things that can happen to a row someone
else is pointing at, and no answer at all for the third.

**Concurrent change** is solved. `version` is registered as SQLAlchemy's `version_id_col`
on `BaseTable`, `BaseUpdateSchema` makes echoing it mandatory, two rules police the
plumbing, and a genuine race maps to the same 409 as a known-stale write.

**Key change** is solved by construction rather than by control. `BaseTable` mandates a
UUID surrogate primary key and `table_models_use_base_table` refuses a table model without
it, so a referenced key never changes. Half of the classic referential problem — the whole
`ON UPDATE` family — simply does not exist here, and this ADR says nothing about it.

**Deletion of the target** is not handled, and the way it is not handled is the part worth
writing down. Every foreign key has a referential action whether or not anyone chose one;
SQL supplies `NO ACTION` when nobody does. The action you get by not choosing is
**indistinguishable in the source** from the action you chose. A reviewer reading

```python
invoice_id: uuid.UUID = Field(foreign_key="invoice.id")
```

cannot tell whether the author considered what happens when the invoice is deleted and
concluded that the database should do nothing, or never thought about it. The platform's
own code was the clearest evidence of this: the framework has exactly one foreign key, it
carried no `ondelete`, and nothing anywhere recorded whether that was deliberate.

### The gate Terp already shipped could not see this

The strongest evidence is in this repository, and it is the kind that ADR 0122 asks for: a
check the platform already ships, in every generated application, that does not cover what
a reader would assume it covers.

The generated app template's `test_migrations_match_models` is the drift half of the
migration control: upgrade a scratch database to head, then assert autogenerate finds
nothing left over. It runs against **SQLite**. Alembic compares foreign keys by a
signature that includes their referential options only when the backend *reflects* those
options — and SQLite reports none, so Alembic falls back to the option-less signature
(`_compare_foreign_keys`, via `sqla_compat._fk_spec`). An `ON DELETE` clause that changed,
or that was never chosen, is invisible to it.

So every Terp application has been running a green drift check that proves nothing at all
about referential behaviour, and nothing said so — not the docstring, not the template, not
the release notes. That is a real failure this rule catches, in real applications, today.

Two more, both facts about the platform's own mechanics rather than predictions:

- **The platform's own only foreign key was undeclared.** Terp ships exactly one, and it
  carried no `ondelete`. The service that owns those rows cascades them itself, through the
  audited chokepoint — a good decision, recorded nowhere. The reference implementation was
  its own example of the problem.
- **A soft-deletable target makes some declared actions unreachable**, which is a
  consequence of `BaseService.delete` and `apply_row_scope` and could not be observed from
  outside the platform. It is written up below.

### Why the platform must not pick a default

One observation from outside Terp, because it is the only claim here that needs outside
evidence and it settles the question completely. In a large application on the same stack
(SQLModel over SQLAlchemy and Alembic — *not* a Terp application, so nothing else in this
ADR rests on it), the three actions appear in comparable volume: roughly 40% `CASCADE`,
30% `RESTRICT`, 28% `SET NULL` across some four hundred declarations.

**No default would have been right.** A platform shipping "cascade by default" would have
been wrong for well over half of them, and "restrict by default" for the other half. This
is not a case where the secure choice is obvious and can simply be imposed — which is why
what follows enforces the decision and never the choice.

The same codebase shows what the hand-rolled guard for this looks like, and it is worth
knowing because it is what an application will reach for if the platform offers nothing: a
line-based scan of the form "if the line contains `ForeignKey(` and does not contain
`ondelete`". That shape has two holes that only look small. It cannot see SQLModel's own
ergonomic spelling, `Field(foreign_key=...)`, at all — so the most convenient way to write
a foreign key is the one the guard is blind to. And the word `ondelete` anywhere on the
line satisfies it, a comment included. A rule the platform owns is checked on the syntax
tree and has neither hole.

### The interaction nobody had written down

`SoftDeleteMixin` turns a delete into a stamp: `BaseService.delete` sets `deleted_at` and
the row stays. No `DELETE` statement is ever issued for such a table, which means **every
referential action declared against a soft-deletable target is dead code**. A `CASCADE`
that never cascades. A `RESTRICT` that never restricts — the service deletes the parent
regardless, because it is not really deleting it.

`SET NULL` is the one that actually hurts. It does not fire either, so the children keep a
live, non-null pointer to a row that `apply_row_scope` now hides from every read. The
reference does not go absent; it goes *broken*. The soft-delete guide already said that
rows pointing at a stamped row "keep their referent, which is the point of the trait" —
true, and the sentence right after it, that the child's read of that referent is now
scoped away, was missing.

## Decision

### 1. A reference declares its delete behaviour

`terp.core.Ref` declares a foreign-key column and takes `on_delete` as a **required
keyword**:

```python
class InvoiceLine(BaseTable, table=True):
    invoice_id: uuid.UUID = Ref("invoice.id", on_delete=OnDelete.CASCADE)
```

Required, not conventional. A reference with no decision is a `TypeError` where the model
is defined — not a review finding somebody has to notice, and not a lint result that a
substring scan may or may not see. This is the `FileRef` shape (ADR 0057) applied to the
other thing a stored pointer carries: that one declares *who may read the target*, this
one declares *what happens when the target goes*.

### 2. The platform does not choose the action

All five SQL actions are legal answers and `OnDelete` offers all five. Which one is right
is a property of what the reference *means* — `CASCADE` for a part of its parent,
`RESTRICT` for something the parent must not vanish underneath, `SET NULL` for a pointer
allowed to go slack — and the evidence above says applications need all of them in bulk.

This is ADR 0103's posture applied one level up. Terp normally enforces one pattern
because the alternative is asking an audience that cannot evaluate a security trade-off to
evaluate one. Here there is no single secure pattern to enforce: the wrong `ondelete` is a
data-integrity bug in both directions. So the enforced thing is the **decision**, and the
choice stays with the author.

### 3. `NO ACTION` is a full answer, and it emits no clause

`OnDelete.NO_ACTION` means "the database takes no action; something above it owns this
lifecycle" — the honest declaration for a lifecycle a service cascades itself, and the only
available answer when the target is soft-deletable. It compiles to **no** `ON DELETE`
clause, which is exactly the DDL an undeclared foreign key already produces. Two reasons,
and the second is what makes the rule adoptable at all:

- A database reports its *default* referential action as absent, not as the words
  `NO ACTION`. Emitting the literal would make every model-versus-database comparison
  report drift on that constraint forever.
- Adopting the declaration then costs **no migration**. An existing schema keeps precisely
  the DDL it has. What changes is that the source now says the silence was chosen.

So the difference between "chose `NO ACTION`" and "chose nothing" lives in the declaration
and never in the schema. That is the point — the schema was never the ambiguous part.

### 4. An action that cannot fire is a violation

`CASCADE`, `SET NULL` or `SET DEFAULT` declared against a soft-deletable target is
refused. Such a declaration is not a declaration, it is a belief: the clause is dead and
the guarantee it looks like does not exist.

The dividing line is worth stating, because the obvious one is wrong. It is not "passive
actions are fine and active ones are not" — it is whether the *reason for declaring the
action depends on it firing*. `RESTRICT` and `NO_ACTION` are honest descriptions of the
only path that can reach the constraint at all, a hard delete no request can issue, so
they remain available as a backstop. The other three each promise to change other rows
when the parent goes, and against a stamped target none of them ever will.

For a soft-deletable target the referential action is therefore an **application**
concern — cascade the stamp from the owning service, or refuse the delete there.

Where a cascade must be *audited*, the service is the right layer regardless of
soft-delete: a database `CASCADE` removes the rows silently and leaves the audit trail with
a hole in it. The groups capability already worked this way and now says so — see §5.

### 5. Both layers, and what each one can see

- **Build time** — the `terp.arch` `references_declare_delete_behaviour` rule reads the
  source. It accepts `Ref(..., on_delete=...)`, SQLModel's `Field(foreign_key=...,
  ondelete=...)` and a hand-built `ForeignKey(..., ondelete=...)`, because each of those
  made the decision; it refuses the fourth case, which made none. Being source-level, it is
  the only half that can tell a chosen `NO ACTION` from an unchosen one.
- **Run time** — `terp.core.assert_references_declare_delete_behaviour` audits live
  `MetaData`, so it sees foreign keys in *any* spelling, including ones a source scan never
  reaches. It is the half that cannot be out-clevered.

The platform's own reference is now declared: `GroupMember.group_id` carries
`OnDelete.NO_ACTION` with the reason on the line above it, because `GroupsService` drains
memberships through the audited chokepoint before the group row goes. That is a
source-only change; the DDL is byte-identical to what shipped.

### 6. Why this rule exists at all, under ADR 0122

ADR 0122 froze the catalog's breadth: a new rule must name a failure it would have caught
in a real application, and "the category looks incomplete" is not a consumer. This clears
that bar on the platform's own evidence, not on symmetry and not on someone else's
codebase:

- **Every generated Terp application** runs a drift check that cannot see a foreign key's
  referential options, because it runs against SQLite. A green gate that does not cover
  what it appears to cover is the failure, and it is present in shipped applications now.
- The platform's single foreign key was undeclared, so the reference implementation was
  itself the example of the problem.
- The soft-delete interaction in §4 is a consequence of `BaseService.delete` and
  `apply_row_scope`: a stamped row cannot trigger a referential action, so an action
  declared against one is dead code. That is a fact about this platform, not a prediction
  about an application.

The outside observation in §"Why the platform must not pick a default" is doing one job
only — establishing that no default action is correct — and this ADR deliberately does not
lean on it for anything else. It comes from an application that is **not** built on Terp,
and treating a non-consumer's tree as a Terp consumer's evidence would be exactly the kind
of reasoning ADR 0122 exists to refuse.

## Consequences

- `Ref` and `OnDelete` join the `terp.core` public surface. `Ref` forwards every other
  keyword to `Field` and indexes by default, because an unindexed foreign key turns every
  parent delete and every join into a table scan.
- An app adopting this adds one keyword per foreign key and, if it chooses `NO_ACTION`,
  changes no schema. An app that wants the declaration reviewed rather than adopted uses
  the standard budgeted marker, like any other rule.
- The generated app template gains `test_references_declare_delete_behaviour`, which
  closes the SQLite blind spot in the Context above: it reads the declaration on the
  models and needs no database at all, so it covers exactly what the drift check beside it
  cannot. `assert_migrations_match_models` now states that limit in its own docstring
  rather than leaving it to be discovered.
- `runtime.applicability` for the catalog entry is **`deferred`**, and the reason is
  technical rather than cautious. The obvious runtime home would be an unconditional walk
  of `SQLModel.metadata` in `create_app` — but that metadata is process-global and
  accumulates every table any test ever declares, so one ad-hoc test model with a bare
  foreign key would fail an unrelated later test that happens to build an app. The audit is
  therefore a function a consumer calls where the model set is known, and the named seam
  for the deferral is a `create_app` boot check scoped to the app's own declared packages.
- **Not decided here:** tightening `GroupMember.group_id` from `NO_ACTION` to `RESTRICT`,
  which would add a real hard-delete backstop. It changes a shipped capability's schema and
  needs its own migration and its own release note, so it is deliberately not a side effect
  of introducing the seam.
- **Not covered here:** field-level immutability ("set once, then fixed") and
  state-conditional deletability ("editable until posted"). `BaseService.append_only`
  answers the whole-table version of the first and nothing answers the narrower questions;
  both remain a service's own code today. `terp guide append-only` now at least states which
  guarantee is which, so the choice is legible before someone hand-rolls the wrong one.
