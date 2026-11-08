"""The request session scopes every aggregate it can, and refuses the reads it cannot (ADR 0204).

Since 0.36.0 the ORM execution hook attaches soft-delete and the registered row predicates as
loader criteria to every mapped entity a statement reaches, so an aggregate over a scope-trait
model is scoped even when it skipped ``base_query()``. Nothing held that in a test until now:
these pin each aggregate shape, on SQLite and on PostgreSQL, for soft-delete, tenant and owner
scope.

What the hook cannot scope is a SELECT that reads a scoped table through Core: a column of
``Model.__table__``, ``select_from(Model.__table__)``, a Core join, subquery or scalar subquery
over it, a Core alias or sample, a copy of the table, ``table("name")`` in any case or schema,
or a many-to-many whose link table is row-scoped. The criteria attach to a mapped entity, and a
mapped entity elsewhere in the statement does not cover that SELECT. Literal SQL, wherever the
statement writes it, and a FROM element the session does not know cannot be read at all. Each
is refused before it runs, with :class:`UnscopedReadError`, rather than answered unscoped. An
entity named in a column property, a loader option or a VALUES row is found there and scoped.
"""

# No `from __future__ import annotations`: SQLModel reads the relationship annotations below
# at class creation, and a string there is a generic it cannot resolve.
import datetime
import re
import uuid
from collections.abc import Callable, Iterator
from typing import NamedTuple

import pytest
from sqlalchemy import Integer, MetaData, column, exists, func, literal_column, table, text, values
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import (
    aliased,
    column_property,
    joinedload,
    relationship,
    selectinload,
    subqueryload,
    with_loader_criteria,
)
from sqlalchemy.sql.selectable import FromClause
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


class Shout(SoftDeleteMixin, BaseTable, table=True):
    """A table named in capitals; never created, since every read of it here is refused."""

    __tablename__ = "CORE_READS_SHOUT"


E = Entry.__table__  # type: ignore[attr-defined]


class Tally(BaseTable, table=True):
    """A model whose column property sums its ledger's entries, naming Entry as an entity."""

    __tablename__ = "core_reads_tally"
    ledger_id: uuid.UUID = Ref("core_reads_ledger.id", on_delete=OnDelete.CASCADE)


Tally.entry_total = column_property(  # type: ignore[attr-defined]
    select(func.coalesce(func.sum(Entry.amount), 0))
    .where(Entry.ledger_id == Tally.ledger_id)
    .correlate_except(Entry)
    .scalar_subquery()
)


class RawTally(BaseTable, table=True):
    """The same sum, through the entries' Core table."""

    __tablename__ = "core_reads_raw_tally"
    ledger_id: uuid.UUID = Ref("core_reads_ledger.id", on_delete=OnDelete.CASCADE)


RawTally.raw_total = column_property(  # type: ignore[attr-defined]
    select(func.coalesce(func.sum(E.c.amount), 0)).where(E.c.ledger_id == RawTally.ledger_id).scalar_subquery()
)


_TABLES = [model.__table__ for model in (Ledger, Entry, Tag, Link, Share, Draft, Tally, RawTally)]  # type: ignore[attr-defined]
TENANT_A, TENANT_B = uuid.uuid4(), uuid.uuid4()
ME, OTHER = uuid.uuid4(), uuid.uuid4()


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
                Tally(ledger_id=ledger.id),
                RawTally(ledger_id=ledger.id),
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
    # A literal that is only a name reads what the FROM it names reads: the scoped entity.
    "a literal column that is a name": lambda s: s.exec(
        select(func.sum(literal_column("amount"))).select_from(Entry)
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
    "a literal column that is a name": 35,
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
        by_name = select(Entry.kind).group_by(Entry.kind).order_by(text("kind"))
        assert session.exec(by_name).all() == ["fee", "refund"]


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
    "a table() in another case": lambda: select(func.sum(column("amount"))).select_from(table("CORE_READS_ENTRY")),
    "a capitals table() in lower case": lambda: select(func.count()).select_from(table("core_reads_shout")),
    "a table() under a schema": lambda: select(func.sum(column("amount"))).select_from(
        table("core_reads_entry", schema="public")
    ),
    "a copy of the table in another MetaData": lambda: select(func.count()).select_from(E.to_metadata(MetaData())),
    "a sample of the table": lambda: select(func.count()).select_from(E.tablesample(func.random())),
    "a subquery of the Core table": lambda: select(func.count()).select_from(select(E).subquery()),
    "the Core table in a parenthesised join": lambda: select(func.count()).select_from(
        Ledger.__table__.join(  # type: ignore[attr-defined]
            E.join(Link.__table__, Link.__table__.c.ledger_id == E.c.ledger_id),  # type: ignore[attr-defined]
            E.c.ledger_id == Ledger.__table__.c.id,  # type: ignore[attr-defined]
        )
    ),
}


@pytest.mark.parametrize("shape", sorted(CORE_ONLY))
def test_a_select_that_reads_a_scoped_table_through_core_is_refused(engine, shape: str) -> None:
    with WriteGuardedSession(engine) as session, tenant_context(TENANT_A):
        with pytest.raises(UnscopedReadError, match="through Core") as refused:
            session.exec(CORE_ONLY[shape]()).all()
    # The refusal names the model and the remedy, so the 500's log line is the fix.
    message = str(refused.value)
    assert re.search(r"\b(Entry|Share|Shout) through Core", message) and "base_query()" in message


LEAK = "(SELECT sum(amount) FROM core_reads_entry)"
UNION = "UNION ALL SELECT amount FROM core_reads_entry"
LITERAL_SQL = {
    "text() in a FROM": lambda: select(func.sum(literal_column("amount"))).select_from(text("core_reads_entry")),
    "a literal column": lambda: select(literal_column(LEAK)),
    "a text() subquery in a FROM": lambda: select(func.count()).select_from(
        text("SELECT amount FROM core_reads_entry").columns(column("amount")).subquery()
    ),
    "text() in a WHERE": lambda: select(func.count(Ledger.id)).where(text(f"EXISTS {LEAK}")),
    "a prefix": lambda: select(Entry.amount).prefix_with(f"{LEAK} AS leak,"),
    "a suffix": lambda: select(Entry.amount).suffix_with(UNION),
    "a statement hint": lambda: select(Entry.amount).with_statement_hint(UNION),
    "a FROM hint": lambda: select(Entry.amount).with_hint(Entry, UNION),
    "a VALUES row": lambda: select(column("x")).select_from(
        values(column("x"), name="v").data([(literal_column(LEAK),)])
    ),
}


@pytest.mark.parametrize("shape", sorted(LITERAL_SQL))
def test_literal_sql_is_refused_wherever_the_statement_writes_it(engine, shape: str) -> None:
    # SQLAlchemy's own walk skips a prefix, a suffix, a hint and a VALUES row, though each is
    # written into the SQL: every one of these read the deleted entry before it was refused.
    with WriteGuardedSession(engine) as session, pytest.raises(UnscopedReadError, match="literal SQL"):
        session.exec(LITERAL_SQL[shape]()).all()


def _sum_in_a_values_row(amount):
    total = select(func.sum(amount)).scalar_subquery()
    return select(column("x")).select_from(values(column("x", Integer), name="v").data([(total,)]).cte("rows"))


def _tags_with_a_link(tag_id):
    return select(Tag).options(with_loader_criteria(Tag, Tag.id.in_(select(tag_id))))


class Elsewhere(NamedTuple):
    """A read that names a scoped model only outside the statement's own clauses."""

    through_the_entity: Callable[[], object]
    answer: Callable[[list], object]
    scoped: object
    through_core: Callable[[], object]
    refusal: str


# Each names its model nowhere else, so only the session finding it there scopes it. The
# deleted entry is 1000 of the 1035 the entries add up to, and the tag's only link is deleted.
ELSEWHERE = {
    "a column property": Elsewhere(
        lambda: select(Tally), lambda rows: rows[0].entry_total, 35,
        lambda: select(RawTally), "Entry through Core, in the column property RawTally.raw_total",
    ),
    "a VALUES row": Elsewhere(
        lambda: _sum_in_a_values_row(Entry.amount), lambda rows: rows[0], 35,
        lambda: _sum_in_a_values_row(E.c.amount), "Entry through Core, in a VALUES list",
    ),
    "a loader option": Elsewhere(
        lambda: _tags_with_a_link(Link.tag_id), len, 0,
        lambda: _tags_with_a_link(Link.__table__.c.tag_id), "Link through Core, in a loader option",  # type: ignore[attr-defined]
    ),
}


@pytest.mark.parametrize("place", sorted(ELSEWHERE))
def test_a_scoped_model_named_only_outside_the_statement_s_clauses_is_scoped(engine, place: str) -> None:
    read = ELSEWHERE[place]
    with WriteGuardedSession(engine) as session:
        assert read.answer(session.exec(read.through_the_entity()).all()) == read.scoped


@pytest.mark.parametrize("place", sorted(ELSEWHERE))
def test_a_scoped_table_read_through_core_there_is_refused_saying_where(engine, place: str) -> None:
    read = ELSEWHERE[place]
    with WriteGuardedSession(engine) as session:
        with pytest.raises(UnscopedReadError, match=re.escape(read.refusal)):
            session.exec(read.through_core()).all()


@pytest.mark.parametrize("loader", [joinedload, selectinload])
def test_a_relationship_s_criteria_in_a_loader_option_is_refused(engine, loader) -> None:
    # A joined load writes the criteria into the parent's own SELECT, which only the option holds.
    statement = select(Ledger).options(loader(Ledger.entries.and_(Entry.id.in_(select(E.c.id)))))
    refused = "Entry through Core, in a loader option"
    with WriteGuardedSession(engine) as session, pytest.raises(UnscopedReadError, match=refused):
        session.exec(statement).unique().all()


def test_a_values_list_and_a_function_s_rows_read_no_table(engine, terp_db_url: str) -> None:
    rows = values(column("x", Integer), name="v").data([(1,), (2,)]).cte("rows")  # SQLite needs it named
    if terp_db_url.startswith("sqlite"):
        series = func.json_each("[1, 2]").table_valued("value")
    else:
        series = func.generate_series(1, 2).table_valued("value")
    with WriteGuardedSession(engine) as session:
        assert sorted(session.exec(select(column("x")).select_from(rows)).all()) == [1, 2]
        assert session.exec(select(func.count()).select_from(series)).one() == 2


class _Elsewhere(FromClause):
    """A FROM element of an app's own making: it reads whatever it compiles to."""

    __visit_name__ = "core_reads_elsewhere"
    inherit_cache = False
    named_with_column = False

    @property
    def _from_objects(self) -> list[FromClause]:
        return [self]


@compiles(_Elsewhere)
def _compile_elsewhere(element: _Elsewhere, compiler: object, **kw: object) -> str:
    return "core_reads_entry"


def test_a_from_element_the_session_does_not_know_is_refused(engine) -> None:
    statement = select(func.sum(literal_column("amount"))).select_from(_Elsewhere())
    with Session(engine) as session:
        assert session.exec(statement).one() == 1035  # every row, the deleted one too
    known = r"a FROM element it does not know \(_Elsewhere\)"
    with WriteGuardedSession(engine) as session, pytest.raises(UnscopedReadError, match=known):
        session.exec(statement).one()


def test_a_many_to_many_through_a_row_scoped_link_table_is_refused(engine) -> None:
    # Unrefused, the ledger would show a tag whose only link is deleted: the hook attaches
    # criteria to mapped entities, and a secondary table is none.
    with WriteGuardedSession(engine) as session:
        ledger = session.get(Ledger, _ledger_id(session))
        with pytest.raises(UnscopedReadError, match="association object"):
            _ = ledger.tags


def test_owner_scope_is_judged_in_the_context_of_the_read(engine, owner_scope) -> None:
    # The same Core read, first with no actor, where the owner scope is a no-op and the read
    # passes, then under an actor: a judgement kept from the first would let the second through.
    core_read = select(func.sum(Draft.__table__.c.amount))  # type: ignore[attr-defined]
    with WriteGuardedSession(engine) as session:
        assert session.exec(core_read).one() == 501
    token = audit_actor_ctx.set(ME)
    try:
        with WriteGuardedSession(engine) as session:
            assert session.exec(select(func.sum(Draft.amount))).one() == 1
            with pytest.raises(UnscopedReadError, match="Draft through Core"):
                session.exec(core_read).one()
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
    assert by_name["core_reads_late"] == [Late]
