"""The declared-reference seam: ``Ref`` / ``OnDelete`` and the metadata audit (ADR 0133).

Every case builds its own ``MetaData`` rather than reading the process-global
``SQLModel.metadata``, which accumulates every table any test in the session ever
declared. That is not fastidiousness: it is the same property the ADR cites as the
reason the audit is a function a consumer calls instead of an unconditional boot
check, so a test suite that depended on the global would be arguing against it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    Table,
)
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, SQLModel

from terp.capabilities.groups.models import GroupMember
from terp.core import (
    BaseTable,
    OnDelete,
    Ref,
    SoftDeleteMixin,
    UndeclaredReferenceError,
    assert_references_declare_delete_behaviour,
    reference_delete_policy,
    undeclared_references,
    unreachable_reference_actions,
)
from terp.core.base_models import SoftDeleteMixin as _TraitForColumnName
from terp.core.references import _SOFT_DELETE_COLUMN


def _parent(metadata: MetaData, name: str = "parent", *, soft: bool = False) -> Table:
    """A referenceable table, optionally soft-deletable."""
    columns = [Column("id", SAUuid, primary_key=True)]
    if soft:
        columns.append(Column("deleted_at", DateTime(timezone=True), nullable=True))
    return Table(name, metadata, *columns)


def _child(
    metadata: MetaData,
    *,
    ondelete: str | None = None,
    target: str = "parent.id",
    info: dict[str, object] | None = None,
) -> Table:
    """A table holding one foreign key, spelled at the DDL level."""
    return Table(
        "child",
        metadata,
        Column("id", SAUuid, primary_key=True),
        Column(
            "parent_id",
            SAUuid,
            ForeignKey(target, ondelete=ondelete),
            nullable=True,
            info=info or {},
        ),
    )


# --------------------------------------------------------------------------- #
# Ref: the decision cannot be skipped, and it lands where metadata can read it
# --------------------------------------------------------------------------- #
def test_ref_requires_the_decision_as_a_keyword() -> None:
    # The whole point of the seam: a reference with no decision does not compile,
    # rather than passing review and failing a lint somebody may not have wired.
    with pytest.raises(TypeError):
        Ref("parent.id")  # type: ignore[call-arg]


def test_ref_refuses_an_action_that_is_not_one() -> None:
    # A bare string would silently accept a typo ("CASACDE") that SQL then rejects
    # at DDL time, in a migration, far from the model that wrote it.
    with pytest.raises(TypeError, match="takes an OnDelete member"):
        Ref("parent.id", on_delete="CASCADE")  # type: ignore[arg-type]


@pytest.mark.parametrize("reserved", ["foreign_key", "ondelete"])
def test_ref_refuses_a_second_source_of_truth(reserved: str) -> None:
    # Two spellings of the same fact on one declaration is how they disagree.
    with pytest.raises(TypeError, match="already owns"):
        Ref("parent.id", on_delete=OnDelete.CASCADE, **{reserved: "whatever"})


def test_ref_refuses_a_hand_built_column_with_a_useful_message() -> None:
    # Ref records the declaration through sa_column_kwargs, which SQLModel refuses
    # alongside a whole sa_column -- so the raw failure is a RuntimeError naming a
    # keyword the caller never passed. The refusal has to name sa_column itself.
    with pytest.raises(TypeError, match="cannot take sa_column"):
        Ref(
            "parent.id",
            on_delete=OnDelete.CASCADE,
            sa_column=Column("parent_id", SAUuid, ForeignKey("parent.id")),
        )


def test_ref_emits_the_clause_and_records_the_declaration() -> None:
    class RefDeclared(BaseTable, table=True):
        __tablename__ = "ref_declared"
        parent_id: uuid.UUID = Ref("ref_target.id", on_delete=OnDelete.CASCADE)

    column = RefDeclared.__table__.c["parent_id"]
    assert next(iter(column.foreign_keys)).constraint.ondelete == "CASCADE"
    assert reference_delete_policy(RefDeclared, "parent_id") is OnDelete.CASCADE
    # Indexed by default: an unindexed foreign key turns every parent delete and
    # every join into a table scan.
    assert column.index is True


def test_no_action_is_declared_but_emits_no_clause() -> None:
    # The property that makes the rule adoptable: identical DDL to an undeclared
    # foreign key, so saying "the database takes no action here" costs no migration
    # -- and a database reports its default action as absent, so emitting the literal
    # would report drift forever.
    class NoActionDeclared(BaseTable, table=True):
        __tablename__ = "ref_no_action"
        parent_id: uuid.UUID = Ref("ref_target.id", on_delete=OnDelete.NO_ACTION)

    column = NoActionDeclared.__table__.c["parent_id"]
    assert next(iter(column.foreign_keys)).constraint.ondelete is None
    assert reference_delete_policy(NoActionDeclared, "parent_id") is OnDelete.NO_ACTION


def test_ref_forwards_other_field_keywords() -> None:
    class Forwarded(BaseTable, table=True):
        __tablename__ = "ref_forwarded"
        parent_id: uuid.UUID | None = Ref(
            "ref_target.id",
            on_delete=OnDelete.SET_NULL,
            default=None,
            index=False,
            sa_column_kwargs={"comment": "the owning record"},
        )

    column = Forwarded.__table__.c["parent_id"]
    assert column.index is not True
    assert column.comment == "the owning record"
    # A caller's own sa_column_kwargs survive alongside the declaration.
    assert reference_delete_policy(Forwarded, "parent_id") is OnDelete.SET_NULL


def test_reference_delete_policy_answers_none_for_anything_undeclared() -> None:
    class Bare(BaseTable, table=True):
        __tablename__ = "ref_bare"
        parent_id: uuid.UUID = Field(foreign_key="ref_target.id")

    assert reference_delete_policy(Bare, "parent_id") is None
    # An unknown column, and a schema that is not a table at all, answer None rather
    # than raising: the accessor is a question, not an assertion.
    assert reference_delete_policy(Bare, "no_such_column") is None
    assert reference_delete_policy(SQLModel, "parent_id") is None


class _RefTarget(BaseTable, table=True):
    __tablename__ = "ref_target"


# --------------------------------------------------------------------------- #
# undeclared_references: the silent default, and the two ways to answer it
# --------------------------------------------------------------------------- #
def test_a_foreign_key_with_no_clause_and_no_declaration_is_undeclared() -> None:
    metadata = MetaData()
    _parent(metadata)
    _child(metadata)
    assert undeclared_references(metadata) == ("child.parent_id -> parent.id",)


def test_a_clause_spelled_at_the_ddl_level_counts_as_declared() -> None:
    # A hand-built ForeignKey(..., ondelete=...) made the decision without the helper,
    # so the rule has nothing to add. What is refused is making none.
    metadata = MetaData()
    _parent(metadata)
    _child(metadata, ondelete="RESTRICT")
    assert undeclared_references(metadata) == ()


def test_a_declaration_with_no_clause_counts_as_declared() -> None:
    # The NO ACTION case seen from metadata: no clause, but the column carries the
    # decision, which is exactly the distinction a database cannot store.
    metadata = MetaData()
    _parent(metadata)
    _child(metadata, info={"terp_ref_on_delete": OnDelete.NO_ACTION})
    assert undeclared_references(metadata) == ()


def test_a_foreign_marker_value_is_not_mistaken_for_a_declaration() -> None:
    # Column.info is a shared mapping anything may write to, so a value that is not
    # an OnDelete member is not a declaration -- fail closed rather than trust it.
    metadata = MetaData()
    _parent(metadata)
    _child(metadata, info={"terp_ref_on_delete": "CASCADE"})
    assert undeclared_references(metadata) == ("child.parent_id -> parent.id",)


def test_a_composite_constraint_is_reported_once_with_both_columns() -> None:
    metadata = MetaData()
    Table(
        "compound_parent",
        metadata,
        Column("left", SAUuid, primary_key=True),
        Column("right", SAUuid, primary_key=True),
    )
    Table(
        "compound_child",
        metadata,
        Column("left", SAUuid),
        Column("right", SAUuid),
        ForeignKeyConstraint(
            ["left", "right"], ["compound_parent.left", "compound_parent.right"]
        ),
    )
    assert undeclared_references(metadata) == (
        "compound_child.(left, right) -> compound_parent.left, compound_parent.right",
    )


def test_a_schema_qualified_table_reports_its_full_name() -> None:
    metadata = MetaData()
    Table("parent", metadata, Column("id", SAUuid, primary_key=True), schema="billing")
    Table(
        "child",
        metadata,
        Column("parent_id", SAUuid, ForeignKey("billing.parent.id")),
        schema="billing",
    )
    assert undeclared_references(metadata) == (
        "billing.child.parent_id -> billing.parent.id",
    )


# --------------------------------------------------------------------------- #
# unreachable_reference_actions: an action a stamp can never trigger
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("action", ["CASCADE", "SET NULL", "SET DEFAULT"])
def test_an_action_against_a_soft_deletable_target_cannot_fire(action: str) -> None:
    metadata = MetaData()
    _parent(metadata, soft=True)
    _child(metadata, ondelete=action)
    assert unreachable_reference_actions(metadata) == (
        f"child.parent_id -> parent.id [{action}]",
    )


@pytest.mark.parametrize("action", ["RESTRICT", "NO ACTION"])
def test_the_honest_actions_against_the_same_target_are_accepted(action: str) -> None:
    # These two, and only these two. Both merely describe the hard-delete path, which
    # is the truthful thing to say about a target whose ordinary delete is a stamp;
    # every other action promises to change rows when the parent goes, and none of
    # those promises can be kept -- SET DEFAULT included, which is why the dividing
    # line is not "passive versus active".
    metadata = MetaData()
    _parent(metadata, soft=True)
    _child(metadata, info={"terp_ref_on_delete": OnDelete(action)})
    assert unreachable_reference_actions(metadata) == ()


def test_a_reachable_action_against_a_hard_deletable_target_is_accepted() -> None:
    metadata = MetaData()
    _parent(metadata)
    _child(metadata, ondelete="CASCADE")
    assert unreachable_reference_actions(metadata) == ()


def test_a_declaration_overrides_the_clause_when_reading_the_action() -> None:
    # The declaration is the authority: a column that says NO_ACTION is not judged by
    # a stale clause someone left on the constraint.
    metadata = MetaData()
    _parent(metadata, soft=True)
    _child(
        metadata,
        ondelete="CASCADE",
        info={"terp_ref_on_delete": OnDelete.NO_ACTION},
    )
    assert unreachable_reference_actions(metadata) == ()


def test_a_dialect_spelling_this_enum_does_not_model_is_not_judged() -> None:
    # An action the enum cannot name is not silently treated as one it can.
    metadata = MetaData()
    _parent(metadata, soft=True)
    _child(metadata, ondelete="SET NULL (col)")
    assert unreachable_reference_actions(metadata) == ()


def test_a_target_outside_this_metadata_is_skipped_not_guessed() -> None:
    # Auditing one module's models is a normal thing to want, and half a model set
    # must not raise: the topological sort would, so the audit does not use it.
    metadata = MetaData()
    _child(metadata, ondelete="CASCADE", target="absent.id")
    assert undeclared_references(metadata) == ()
    assert unreachable_reference_actions(metadata) == ()


# --------------------------------------------------------------------------- #
# the assertion, and the platform's own reference
# --------------------------------------------------------------------------- #
def test_the_assertion_passes_on_a_fully_declared_model_set() -> None:
    metadata = MetaData()
    _parent(metadata)
    _child(metadata, ondelete="CASCADE")
    assert_references_declare_delete_behaviour(metadata)


def test_the_assertion_names_both_kinds_of_finding() -> None:
    metadata = MetaData()
    _parent(metadata, "hard")
    _parent(metadata, "soft", soft=True)
    Table(
        "child",
        metadata,
        Column("hard_id", SAUuid, ForeignKey("hard.id")),
        Column("soft_id", SAUuid, ForeignKey("soft.id", ondelete="CASCADE")),
    )
    with pytest.raises(UndeclaredReferenceError) as caught:
        assert_references_declare_delete_behaviour(metadata)
    assert caught.value.undeclared == ("child.hard_id -> hard.id",)
    assert caught.value.unreachable == ("child.soft_id -> soft.id [CASCADE]",)
    message = str(caught.value)
    assert "declare no delete behaviour" in message
    assert "can never fire" in message


def test_the_assertion_reports_only_the_kind_that_is_present() -> None:
    # Each half of the message appears on its own, so a report never lists a heading
    # with nothing under it.
    undeclared_only = MetaData()
    _parent(undeclared_only)
    _child(undeclared_only)
    with pytest.raises(UndeclaredReferenceError) as caught:
        assert_references_declare_delete_behaviour(undeclared_only)
    assert "can never fire" not in str(caught.value)

    unreachable_only = MetaData()
    _parent(unreachable_only, soft=True)
    _child(unreachable_only, ondelete="CASCADE")
    with pytest.raises(UndeclaredReferenceError) as caught:
        assert_references_declare_delete_behaviour(unreachable_only)
    assert "declare no delete behaviour" not in str(caught.value)


def test_the_assertion_defaults_to_the_shared_metadata() -> None:
    # The documented consumer call is the no-argument one, from a suite that has
    # imported its models. Proven against a metadata this test owns, by pointing the
    # default at it -- reading the real global would make the assertion depend on
    # every other test in the session, which is the very thing ADR 0133 refuses.
    metadata = MetaData()
    _parent(metadata)
    _child(metadata)
    original = SQLModel.metadata
    try:
        SQLModel.metadata = metadata  # type: ignore[misc]
        with pytest.raises(UndeclaredReferenceError):
            assert_references_declare_delete_behaviour()
    finally:
        SQLModel.metadata = original  # type: ignore[misc]


def test_the_platform_declares_its_own_only_reference() -> None:
    # The framework ships exactly one foreign key, and it was the clearest example of
    # the problem: undeclared, with nothing recording whether that was deliberate.
    # GroupsService drains memberships through the audited chokepoint before the group
    # row goes, so the database is meant to take no action -- and now says so.
    assert reference_delete_policy(GroupMember, "group_id") is OnDelete.NO_ACTION
    # Source-only: the shipped DDL is unchanged, so no consumer needs a migration.
    column = GroupMember.__table__.c["group_id"]
    assert next(iter(column.foreign_keys)).constraint.ondelete is None


def test_soft_delete_column_name_matches_the_trait() -> None:
    # The audit names the trait's column rather than importing base_models, so a
    # rename there would silently stop the reachability half from ever firing.
    assert _SOFT_DELETE_COLUMN in _TraitForColumnName.model_fields
    assert _SOFT_DELETE_COLUMN in SoftDeleteMixin.model_fields
