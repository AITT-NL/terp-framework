"""Declared references: ``Ref`` + the delete-behaviour declaration (ADR 0133).

A stored pointer to another row carries a **lifecycle decision**: what happens to
this row when the row it references is deleted. SQL has an answer for every
foreign key whether or not anyone chose it, and the answer you get by not
choosing (``NO ACTION``) is indistinguishable in the source from the answer you
did choose. That is the whole problem this module exists for.

The posture is **declare, don't default** -- and deliberately *not* "cascade" or
"restrict". Which action is right depends on what the reference means: an invoice
line is part of its invoice (``CASCADE``), a ledger entry must not let its account
disappear underneath it (``RESTRICT``), an optional assignee is just a pointer that
can go slack (``SET NULL``). A platform that picked one would be wrong for the other
two, so :class:`OnDelete` offers all five SQL actions and the rule enforces only
that one of them was *named*:

* :func:`Ref` declares the column. ``on_delete`` is a **required keyword**, so a
  reference with no decision is a :class:`TypeError` at import -- not a review
  finding somebody has to notice.
* The declaration is recorded in the column's SQLAlchemy ``info`` mapping, which
  makes it readable from plain metadata: :func:`reference_delete_policy` reads one
  column, :func:`undeclared_references` and :func:`unreachable_reference_actions`
  audit a whole ``MetaData``, and :func:`assert_references_declare_delete_behaviour`
  turns both audits into one fail-closed refusal a consumer can wire into its own
  test suite or boot sequence.
* The build-time half is the ``terp.arch`` ``references_declare_delete_behaviour``
  rule, which reads the *source* -- so it also sees the case metadata cannot
  distinguish, a bare ``Field(foreign_key=...)`` that never made a decision at all.

``NO ACTION`` emits no clause
-----------------------------
:attr:`OnDelete.NO_ACTION` is a real, legal answer -- "the database takes no
action; something above it owns this lifecycle" -- and it deliberately compiles to
**no** ``ON DELETE`` clause at all, which is exactly the DDL an undeclared foreign
key already produces. Two reasons, and both matter more than the symmetry would:

* A database reports its *default* referential action as absent, not as the words
  ``NO ACTION``. Emitting the literal would make every model-versus-database
  comparison report drift on that constraint forever.
* Adopting the declaration then costs no migration. An existing schema keeps
  exactly the DDL it has; what changes is that the source now says the silence was
  chosen.

So the difference between "chose NO ACTION" and "chose nothing" lives in the
declaration, never in the schema. That is the point: the schema was never the part
that was ambiguous.

An action that cannot fire
--------------------------
:class:`~terp.core.SoftDeleteMixin` makes a delete a *stamp*: the audited write
chokepoint sets ``deleted_at`` and the row stays. No ``DELETE`` statement is ever
issued for it, so **every referential action declared against a soft-deletable
target is dead code** -- a ``CASCADE`` that never cascades, a ``RESTRICT`` that
never restricts. The trap is not the dead clause; it is what the author believed it
bought them. ``SET NULL`` is the sharpest: the children keep a live, non-null
pointer to a row that the read scope now hides from every query, so the reference
reads as broken rather than absent.

Which actions this refuses follows from that, and the line is not "passive versus
active": it is whether the reason for declaring the action depends on it *firing*.
``RESTRICT`` and ``NO ACTION`` are truthful about the only path that can reach the
constraint at all -- a hard delete no request can issue -- so they stay. ``CASCADE``,
``SET NULL`` and ``SET DEFAULT`` each promise to change other rows when the parent
goes, so against a stamped target each is a promise the platform cannot keep.

For a soft-deletable target the referential action is an **application** concern
-- cascade the stamp from the owning service, or refuse the delete there -- and the
database clause is only a backstop for the hard-delete path that no request can
reach. :attr:`OnDelete.RESTRICT` and :attr:`OnDelete.NO_ACTION` say that; the other
three claim something the platform cannot deliver, so
:func:`unreachable_reference_actions` reports them.

Recipe: ``terp guide references``.
"""

from __future__ import annotations

import enum
from typing import Any

from sqlalchemy import Column, ForeignKeyConstraint, MetaData, Table
from sqlmodel import Field, SQLModel

# The key a Ref-declared column carries in its SQLAlchemy ``Column.info``. Column
# info (rather than the field's JSON-schema extras) is the carrier on purpose: it
# survives into plain ``MetaData``, so every audit in this module reads a table
# without needing the model class that declared it.
_REF_MARKER = "terp_ref_on_delete"


class OnDelete(enum.StrEnum):
    """What the database does to this row when the row it references is deleted.

    All five SQL actions are legal answers and the platform does not prefer one:
    the rule is that a reference *names* its answer, never which answer it names
    (ADR 0133).

    :attr:`NO_ACTION` is the declared form of the SQL default and emits no clause
    -- see the module docstring for why that is deliberate rather than a shortcut.
    """

    CASCADE = "CASCADE"
    """Delete this row too. The reference means *part of*."""

    RESTRICT = "RESTRICT"
    """Refuse the parent's delete while this row exists. The reference means *depends on*."""

    SET_NULL = "SET NULL"
    """Blank the pointer and keep this row. Requires a nullable column."""

    SET_DEFAULT = "SET DEFAULT"
    """Point at the column's default instead. Requires a column default that exists.

    Like :attr:`CASCADE` and :attr:`SET_NULL`, this is a promise to change this row
    when the target goes -- so it cannot be declared against a soft-deletable target,
    whose delete is a stamp and never reaches the constraint.
    """

    NO_ACTION = "NO ACTION"
    """The database takes no action; something above it owns this lifecycle.

    Emits no ``ON DELETE`` clause (the SQL default is already NO ACTION), so
    declaring it changes the source and never the schema. Use it when the owning
    service performs the cascade itself, or when the target is soft-deletable and
    no database action could fire anyway.
    """


# Actions a soft-deletable target can never trigger: its delete is a stamp, so no
# DELETE statement ever reaches the constraint. The test is not whether an action is
# passive but whether the reason for declaring it depends on it *firing*: RESTRICT and
# NO_ACTION are truthful statements about the hard-delete path, while these three all
# promise to change other rows when the parent goes, and none of them ever will.
_UNREACHABLE_AGAINST_SOFT_DELETE = frozenset(
    {OnDelete.CASCADE, OnDelete.SET_NULL, OnDelete.SET_DEFAULT}
)

# The soft-delete trait's column. Named here rather than imported from
# ``base_models`` to keep this module free of a cycle; the two are held equal by
# ``test_soft_delete_column_name_matches_the_trait``.
_SOFT_DELETE_COLUMN = "deleted_at"


def Ref(  # noqa: N802 - a Field-style factory, named like the declaration it makes
    target: str,
    *,
    on_delete: OnDelete,
    **field_kwargs: Any,
) -> Any:
    """Declare a model column as a reference, naming what a delete of *target* does.

    Use it instead of a bare foreign-key field::

        class InvoiceLine(BaseTable, table=True):
            invoice_id: uuid.UUID = Ref("invoice.id", on_delete=OnDelete.CASCADE)

    *target* is the usual ``"<table>.<column>"`` foreign-key target. ``on_delete``
    is required and keyword-only, so the decision cannot be skipped: omitting it is
    a :class:`TypeError` where the model is defined. The column is otherwise an
    ordinary indexed foreign-key field -- extra keywords (``nullable``, ``unique``,
    ``default``, ...) are forwarded to :func:`sqlmodel.Field` unchanged, and
    ``index=True`` is the default because a foreign key that is never indexed turns
    every parent delete and every join into a table scan.

    Nullability comes from the annotation, as with any SQLModel field, and
    ``on_delete=OnDelete.SET_NULL`` on a non-nullable column is refused where every
    other such mismatch is (at table construction).
    """
    if not isinstance(on_delete, OnDelete):
        raise TypeError(
            f"Ref(on_delete=...) takes an OnDelete member, not {on_delete!r}; "
            "import OnDelete from terp.core and name the action "
            "(CASCADE / RESTRICT / SET NULL / SET DEFAULT / NO ACTION)"
        )
    for reserved in ("foreign_key", "ondelete"):
        if reserved in field_kwargs:
            raise TypeError(
                f"Ref() already owns {reserved!r}: pass the target positionally and "
                "the action as on_delete=OnDelete.<ACTION>, so one declaration is "
                "the single source of the reference's delete behaviour"
            )
    if "sa_column" in field_kwargs:
        # Ref records the declaration through sa_column_kwargs, and SQLModel refuses
        # those alongside a whole sa_column -- so without this the failure is a
        # RuntimeError naming a keyword the caller never passed. Say what to do instead.
        raise TypeError(
            "Ref() cannot take sa_column: it declares the column itself (including "
            "the foreign key and the delete behaviour). Pass the column's other "
            "properties as ordinary keywords, or as sa_column_kwargs={...} for the "
            "SQLAlchemy-only ones; a reference that genuinely needs a hand-built "
            "Column declares its action there instead, with "
            "ForeignKey(target, ondelete=...)"
        )

    kwargs: dict[str, Any] = dict(field_kwargs)
    kwargs.setdefault("index", True)
    # The declared action rides the column's info mapping either way; the clause is
    # emitted only when it is not the SQL default (see the module docstring).
    if on_delete is not OnDelete.NO_ACTION:
        kwargs["ondelete"] = on_delete.value
    column_kwargs: dict[str, Any] = dict(kwargs.pop("sa_column_kwargs", None) or {})
    column_kwargs["info"] = {
        **(column_kwargs.get("info") or {}),
        _REF_MARKER: on_delete,
    }
    kwargs["sa_column_kwargs"] = column_kwargs
    return Field(foreign_key=target, **kwargs)


def _declared_policy(column: Column[Any]) -> OnDelete | None:
    """The action :func:`Ref` recorded on *column*, if it was declared by one."""
    value = column.info.get(_REF_MARKER)
    return value if isinstance(value, OnDelete) else None


def reference_delete_policy(model: type[SQLModel], column: str) -> OnDelete | None:
    """The delete behaviour declared for *model*.*column*, or ``None`` if undeclared.

    Reads the declaration :func:`Ref` recorded, so a foreign key spelled some other
    way answers ``None`` even when it carries an ``ON DELETE`` clause of its own --
    the question this answers is "was a decision declared here", not "what does the
    database do". Use :func:`undeclared_references` to audit whole metadata, which
    accepts both forms.
    """
    table = getattr(model, "__table__", None)
    if table is None or column not in table.c:
        return None
    return _declared_policy(table.c[column])


def _constraint_columns(constraint: ForeignKeyConstraint) -> list[Column[Any]]:
    """The local columns *constraint* constrains, in declaration order."""
    return [element.parent for element in constraint.elements]


def _foreign_keys(metadata: MetaData) -> list[tuple[Table, ForeignKeyConstraint]]:
    """Every foreign-key constraint in *metadata*, in a stable order.

    Iterates ``metadata.tables`` rather than ``sorted_tables``: the topological sort
    resolves every foreign key to its target, which raises when the target table is
    not in this metadata -- and auditing a partial model set (one module's models,
    say) is a normal thing to want.
    """
    return [
        (table, constraint)
        for _key, table in sorted(metadata.tables.items())
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]


def _target_table(metadata: MetaData, constraint: ForeignKeyConstraint) -> Table | None:
    """The table *constraint* points at, when this metadata holds it.

    Resolved by name out of *metadata* instead of through the constraint's own
    ``element.column``, which would raise for a target this metadata does not
    contain. A target that is absent simply cannot be judged, so the caller skips
    it rather than failing.
    """
    fullname = constraint.elements[0].target_fullname
    key = fullname.rsplit(".", 1)[0]
    return metadata.tables.get(key)


def _label(table: Table, constraint: ForeignKeyConstraint) -> str:
    """A human address for *constraint*: ``schema.table.col -> target.col``.

    A composite constraint parenthesises its columns (``child.(left, right)``), so the
    table name is not read as belonging to the first column only.
    """
    names = [column.name for column in _constraint_columns(constraint)]
    local = names[0] if len(names) == 1 else f"({', '.join(names)})"
    target = ", ".join(element.target_fullname for element in constraint.elements)
    return f"{table.fullname}.{local} -> {target}"


def _effective_action(constraint: ForeignKeyConstraint) -> OnDelete | None:
    """The action *constraint* actually carries, declared or spelled in DDL."""
    for column in _constraint_columns(constraint):
        declared = _declared_policy(column)
        if declared is not None:
            return declared
    if constraint.ondelete is None:
        return None
    try:
        return OnDelete(constraint.ondelete.upper())
    except ValueError:  # a dialect-specific spelling this enum does not model
        return None


def undeclared_references(metadata: MetaData) -> tuple[str, ...]:
    """Foreign keys in *metadata* that name no delete behaviour at all.

    A constraint counts as declared when :func:`Ref` recorded the decision on one
    of its columns, **or** when it spells an ``ON DELETE`` clause directly -- a
    hand-built ``Column(ForeignKey(..., ondelete=...))`` made the decision even
    though it did not use the helper. What is refused is the third case: no clause
    and no declaration, which is the silent default nobody chose.
    """
    return tuple(
        _label(table, constraint)
        for table, constraint in _foreign_keys(metadata)
        if constraint.ondelete is None
        and not any(
            _declared_policy(column) is not None
            for column in _constraint_columns(constraint)
        )
    )


def unreachable_reference_actions(metadata: MetaData) -> tuple[str, ...]:
    """Foreign keys in *metadata* whose declared action can never fire.

    A ``CASCADE``, ``SET NULL`` or ``SET DEFAULT`` pointing at a soft-deletable table:
    that target's delete is a stamp, never a ``DELETE``, so the clause is dead and the
    guarantee the author was relying on does not exist. ``RESTRICT`` and ``NO ACTION``
    are not reported, because they only ever described the hard-delete path anyway.
    See the module docstring for what to declare instead.
    """
    findings: list[str] = []
    for table, constraint in _foreign_keys(metadata):
        action = _effective_action(constraint)
        if action not in _UNREACHABLE_AGAINST_SOFT_DELETE:
            continue
        target = _target_table(metadata, constraint)
        if target is not None and _SOFT_DELETE_COLUMN in target.c:
            findings.append(f"{_label(table, constraint)} [{action.value}]")
    return tuple(findings)


class UndeclaredReferenceError(Exception):
    """A foreign key names no delete behaviour, or names one that cannot fire.

    Raised by :func:`assert_references_declare_delete_behaviour`. Not an
    :class:`~terp.core.AppError`: this is a modelling defect discovered while
    auditing metadata, not something a request can provoke, so it has no HTTP
    envelope and never reaches a client.
    """

    def __init__(
        self, undeclared: tuple[str, ...], unreachable: tuple[str, ...]
    ) -> None:
        self.undeclared = undeclared
        self.unreachable = unreachable
        parts: list[str] = []
        if undeclared:
            parts.append(
                "foreign keys that declare no delete behaviour (declare one with "
                "Ref(target, on_delete=OnDelete.<ACTION>); OnDelete.NO_ACTION is a "
                f"legal answer and changes no DDL): {', '.join(undeclared)}"
            )
        if unreachable:
            parts.append(
                "foreign keys whose declared action can never fire, because the "
                "target is soft-deletable and its delete is a stamp (declare "
                "RESTRICT or NO_ACTION and cascade from the owning service): "
                f"{', '.join(unreachable)}"
            )
        super().__init__("; ".join(parts))


def assert_references_declare_delete_behaviour(
    metadata: MetaData | None = None,
) -> None:
    """Refuse metadata whose foreign keys have undeclared or unreachable delete behaviour.

    The reusable audit for a consumer's own test suite or boot sequence -- the
    runtime companion to the ``terp.arch``
    ``references_declare_delete_behaviour`` rule, which reads the source instead.
    Defaults to the shared ``SQLModel.metadata``, so a suite that has imported its
    models can call it with no arguments.

    It is deliberately **not** wired into ``create_app``: ``SQLModel.metadata`` is
    process-global and accumulates every table any test ever declared, so an
    unconditional walk at boot would make one ad-hoc test model fail an unrelated
    later test. Call it where the model set is known instead (ADR 0133).
    """
    target = SQLModel.metadata if metadata is None else metadata
    undeclared = undeclared_references(target)
    unreachable = unreachable_reference_actions(target)
    if undeclared or unreachable:
        raise UndeclaredReferenceError(undeclared, unreachable)


__all__ = [
    "OnDelete",
    "Ref",
    "UndeclaredReferenceError",
    "assert_references_declare_delete_behaviour",
    "reference_delete_policy",
    "undeclared_references",
    "unreachable_reference_actions",
]
