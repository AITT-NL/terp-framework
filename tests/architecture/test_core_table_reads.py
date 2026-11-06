"""The request session scopes every aggregate it can, and refuses the reads it cannot (ADR 0204).

Since 0.36.0 the ORM execution hook attaches soft-delete and the registered row predicates as
loader criteria to every mapped entity a statement reaches, so an aggregate over a scope-trait
model is scoped even when it skipped ``base_query()``. Nothing held that in a test until now:
these pin each aggregate shape, on SQLite and on PostgreSQL, for soft-delete, tenant and owner
scope.

What the hook cannot scope is a SELECT that reads a scoped table through Core: a column of
``Model.__table__``, ``select_from(Model.__table__)``, a Core join or scalar subquery over it, a
Core alias, ``table("name")``, literal SQL in a FROM, or a many-to-many whose link table is
row-scoped. The criteria attach to a mapped entity, and a mapped entity elsewhere in the
statement does not cover that SELECT. Those are refused before they run, with
:class:`UnscopedReadError`, rather than answered unscoped.
"""

# No `from __future__ import annotations`: SQLModel reads the relationship annotations below
# at class creation, and a string there is a generic it cannot resolve.
import datetime
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import column, exists, func, literal_column, table, text
from sqlalchemy.orm import aliased, joinedload, relationship, selectinload, subqueryload
from sqlmodel import Field, Relationship, Session, SQLModel, create_engine, select

from terp.core import BaseTable, OnDelete, OwnedMixin, Ref, SoftDeleteMixin
from terp.core.audit import audit_actor_ctx
from terp.core.scoping import (
    register_owner_read_scope,
    register_scope_predicate,
    registered_scope_predicates,
)
from terp.core._internal.registry_resets import reset_scope_predicates
from terp.core._internal.session_guard import UnscopedReadError, WriteGuardedSession
from terp.capabilities.tenancy import TenantScopedMixin, tenant_context


class Ledger(BaseTable, table=True):
    __tablename__ = "core_reads_ledger"
    label: str = Field(max_length=50)
    entries: list["Entry"] = Relationship(back_populates="ledger")
    # A many-to-many through a soft-deletable link table: no mapped entity takes its scope.
    tags: list["Tag"] = Relationship(
        sa_relationship=relationship("Tag", secondary="core_reads_link", viewonly=True)
    )


class Entry(SoftDeleteMixin, BaseTable, table=True):
    __tablename__ = "core_reads_entry"
    ledger_id: uuid.UUID = Ref("core_reads_ledger.id", on_delete=OnDelete.RESTRICT)
    kind: str = Field(max_length=20)
    amount: int = 0
    ledger: Ledger | None = Relationship(back_populates="entries")


class Tag(BaseTable, table=True):
    __tablename__ = "core_reads_tag"
    label: str = Field(max_length=20)


class Link(SoftDeleteMixin, BaseTable, table=True):
    __tablename__ = "core_reads_link"
    ledger_id: uuid.UUID = Ref("core_reads_ledger.id", on_delete=OnDelete.CASCADE)
    tag_id: uuid.UUID = Ref("core_reads_tag.id", on_delete=OnDelete.CASCADE)


class Share(TenantScopedMixin, BaseTable, table=True):
    __tablename__ = "core_reads_share"
    amount: int = 0


class Draft(OwnedMixin, BaseTable, table=True):
    __tablename__ = "core_reads_draft"
    amount: int = 0


_TABLES = [model.__table__ for model in (Ledger, Entry, Tag, Link, Share, Draft)]  # type: ignore[attr-defined]
TENANT_A, TENANT_B = uuid.uuid4(), uuid.uuid4()
ME, OTHER = uuid.uuid4(), uuid.uuid4()
E = Entry.__table__  # type: ignore[attr-defined]


@pytest.fixture
def engine(terp_db_url: str) -> Iterator[object]:
    value = create_engine(terp_db_url)
    SQLModel.metadata.create_all(value, tables=_TABLES)
    ledger, tag = Ledger(label="main"), Tag(label="hidden")
    with Session(value) as session:
        session.add_all([ledger, tag])
        session.flush()
        now = datetime.datetime.now(datetime.UTC)
        session.add_all(
            [
                Entry(ledger_id=ledger.id, kind="fee", amount=10),
                Entry(ledger_id=ledger.id, kind="fee", amount=20),
                Entry(ledger_id=ledger.id, kind="refund", amount=5),
                Entry(ledger_id=ledger.id, kind="fee", amount=1000, deleted_at=now),
                # The tag's only link is soft-deleted: the ledger has no live tag.
                Link(ledger_id=ledger.id, tag_id=tag.id, deleted_at=now),
                Share(tenant_id=TENANT_A, amount=7),
                Share(tenant_id=TENANT_B, amount=700),
                Draft(owner_id=ME, amount=1),
                Draft(owner_id=OTHER, amount=500),
            ]
        )
        session.commit()
    try:
        yield value
    finally:
        value.dispose()


@pytest.fixture
def owner_scope() -> Iterator[None]:
    saved = registered_scope_predicates()
    register_owner_read_scope()
    try:
        yield
    finally:
        reset_scope_predicates()
        for predicate in saved:
            register_scope_predicate(predicate)


def _ledger_id(session) -> uuid.UUID:
    return session.exec(select(Ledger.id)).one()


SCOPED = {
    "sum": lambda s: s.exec(select(func.sum(Entry.amount))).one(),
    "count of a column": lambda s: s.exec(select(func.count(Entry.id))).one(),
    "count select_from the model": lambda s: s.exec(select(func.count()).select_from(Entry)).one(),
    "count over a subquery of the entity": lambda s: s.exec(
        select(func.count()).select_from(select(Entry).subquery())
    ).one(),
    "count over a CTE of the entity": lambda s: s.exec(select(func.count()).select_from(select(Entry).cte())).one(),
    "count of an aliased entity": lambda s: s.exec(select(func.count(aliased(Entry).id))).one(),
    "an ORM column over the Core table": lambda s: s.exec(select(func.sum(Entry.amount)).select_from(E)).one(),
    "a Core column narrowed by a mapped one": lambda s: s.exec(
        select(func.sum(E.c.amount)).where(Entry.amount > 0)
    ).one(),
}
EXPECTED = {
    "sum": 35,
    "count of a column": 3,
    "count select_from the model": 3,
    "count over a subquery of the entity": 3,
    "count over a CTE of the entity": 3,
    "count of an aliased entity": 3,
    "an ORM column over the Core table": 35,
    "a Core column narrowed by a mapped one": 35,
}


@pytest.mark.parametrize("shape", sorted(SCOPED))
def test_an_aggregate_over_a_soft_delete_model_leaves_the_deleted_row_out(engine, shape: str) -> None:
    with WriteGuardedSession(engine) as session:
        assert SCOPED[shape](session) == EXPECTED[shape]


def test_a_grouped_aggregate_and_joins_through_a_scoped_child_are_scoped(engine) -> None:
    child = aliased(Entry)
    with WriteGuardedSession(engine) as session:
        grouped = select(Entry.kind, func.sum(Entry.amount)).group_by(Entry.kind).order_by(Entry.kind)
        assert session.exec(grouped).all() == [("fee", 30), ("refund", 5)]
        joined = select(Ledger.label, func.count(Entry.id)).join(Entry, Entry.ledger_id == Ledger.id).group_by(Ledger.label)
        assert session.exec(joined).all() == [("main", 3)]
        through_alias = select(func.sum(child.amount)).select_from(Ledger).join(child, child.ledger_id == Ledger.id)
        assert session.exec(through_alias).one() == 35
        has_entries = select(func.count()).select_from(Ledger).where(exists().where(Entry.ledger_id == Ledger.id))
        assert session.exec(has_entries).one() == 1


def test_relationship_loads_and_a_primary_key_get_are_scoped_and_allowed(engine) -> None:
    with WriteGuardedSession(engine) as session:
        ledger_id = _ledger_id(session)
        assert sorted(entry.amount for entry in session.get(Ledger, ledger_id).entries) == [5, 10, 20]
        assert session.exec(select(Entry)).first().ledger.label == "main"
    for loader in (selectinload, subqueryload, joinedload):
        with WriteGuardedSession(engine) as session:
            ledger = session.exec(select(Ledger).options(loader(Ledger.entries))).unique().one()
            assert len(ledger.entries) == 3, loader.__name__
    with WriteGuardedSession(engine) as session:
        entry_id = session.exec(select(Entry.id)).first()
        assert session.get(Entry, entry_id) is not None


def test_an_aggregate_over_a_tenant_scoped_model_counts_its_own_tenant(engine) -> None:
    with WriteGuardedSession(engine) as session, tenant_context(TENANT_A):
        assert session.exec(select(func.sum(Share.amount))).one() == 7
        assert session.exec(select(func.count()).select_from(Share)).one() == 1


CORE_ONLY = {
    "a Core column": lambda: select(func.sum(E.c.amount)),
    "select_from the Core table": lambda: select(func.count()).select_from(E),
    "a Core alias": lambda: select(func.count()).select_from(E.alias()),
    "a table() by name": lambda: select(func.sum(column("amount"))).select_from(table("core_reads_entry")),
    "a Core join from a mapped parent": lambda: (
        select(Ledger.label, func.sum(E.c.amount)).join(E, E.c.ledger_id == Ledger.id).group_by(Ledger.label)
    ),
    "a Core scalar subquery under a mapped parent": lambda: select(
        Ledger.label, select(func.sum(E.c.amount)).where(E.c.ledger_id == Ledger.id).scalar_subquery()
    ),
    "a tenant table through Core": lambda: select(func.sum(Share.__table__.c.amount)),  # type: ignore[attr-defined]
}


@pytest.mark.parametrize("shape", sorted(CORE_ONLY))
def test_a_select_that_reads_a_scoped_table_through_core_is_refused(engine, shape: str) -> None:
    with WriteGuardedSession(engine) as session, tenant_context(TENANT_A):
        with pytest.raises(UnscopedReadError, match="through Core") as refused:
            session.exec(CORE_ONLY[shape]()).all()
    # The refusal names the model and the remedy, so the 500's log line is the fix.
    message = str(refused.value)
    assert ("Entry" in message or "Share" in message) and "base_query()" in message


def test_literal_sql_in_a_from_is_refused_because_nothing_can_scope_it(engine) -> None:
    statement = select(func.sum(literal_column("amount"))).select_from(text("core_reads_entry"))
    with WriteGuardedSession(engine) as session, pytest.raises(UnscopedReadError, match="a literal SQL FROM"):
        session.exec(statement).one()


def test_a_many_to_many_through_a_row_scoped_link_table_is_refused(engine) -> None:
    # Unrefused, the ledger would show a tag whose only link is deleted: the hook attaches
    # criteria to mapped entities, and a secondary table is none.
    with WriteGuardedSession(engine) as session:
        ledger = session.get(Ledger, _ledger_id(session))
        with pytest.raises(UnscopedReadError, match="association object"):
            _ = ledger.tags


def test_owner_scope_is_judged_in_the_context_of_the_read(engine, owner_scope) -> None:
    # The first read of the process happens with no actor, where the owner scope is a no-op;
    # a later read under an actor must still be judged under that actor, not that first one.
    with WriteGuardedSession(engine) as session:
        assert session.exec(select(func.count()).select_from(Ledger)).one() == 1
    token = audit_actor_ctx.set(ME)
    try:
        with WriteGuardedSession(engine) as session:
            assert session.exec(select(func.sum(Draft.amount))).one() == 1
            with pytest.raises(UnscopedReadError, match="Draft"):
                session.exec(select(func.sum(Draft.__table__.c.amount))).one()  # type: ignore[attr-defined]
    finally:
        audit_actor_ctx.reset(token)


def test_a_core_read_of_a_table_without_row_scope_is_not_refused(engine) -> None:
    with WriteGuardedSession(engine) as session:
        ledgers = Ledger.__table__  # type: ignore[attr-defined]
        assert session.exec(select(func.count()).select_from(ledgers)).one() == 1
        # Without an actor the owner scope is not installed: nothing to refuse.
        assert session.exec(select(func.sum(Draft.__table__.c.amount))).one() == 501  # type: ignore[attr-defined]


def test_a_bare_session_is_left_alone(engine) -> None:
    # Only the request session scopes and refuses; a deliberate privileged read (a test,
    # a migration, the CLI) uses a plain Session and reads what is there.
    with Session(engine) as session:
        assert session.exec(select(func.sum(E.c.amount))).one() == 1035


def test_the_table_lookup_is_rebuilt_when_a_mapper_is_constructed() -> None:
    from terp.core import scoping

    before, _ = scoping._mapped_tables()
    assert scoping._mapped_tables()[0] is before  # kept while the schema stands still

    class Late(SoftDeleteMixin, BaseTable, table=True):
        __tablename__ = "core_reads_late"

    after, by_name = scoping._mapped_tables()
    assert after is not before
    assert by_name[(None, "core_reads_late")] == [Late]
