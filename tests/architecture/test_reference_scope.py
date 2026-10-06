"""A reference a write sets must point at a row its writer can read (ADR 0178).

The row scope filtered reads and nothing else. A write could aim a reference at another
tenant's row, or at a soft-deleted one, and the foreign key let it through, because a
foreign key checks existence, never scope. These tests hold the write chokepoint to the
same scope the reads already obey, and hold the refusal to the one property that keeps
it from becoming an oracle: it reads exactly like the database refusing a missing row.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Column, ForeignKeyConstraint, Table, UniqueConstraint, Uuid, event
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine

from terp.capabilities.tenancy import TenantScopedMixin, TenantScopedService, tenant_context
from terp.core import (
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    ConflictError,
    OnDelete,
    Ref,
    SoftDeleteMixin,
)
from terp.core.scoping import refuse_out_of_scope_references

_REFUSAL = "This write conflicts with a unique or referential constraint."


class _Node(BaseTable, TenantScopedMixin, table=True):
    __tablename__ = "refscope_node"
    name: str = Field(max_length=50)


class _Edge(BaseTable, TenantScopedMixin, table=True):
    __tablename__ = "refscope_edge"
    source_id: uuid.UUID = Ref("refscope_node.id", on_delete=OnDelete.CASCADE)
    target_id: uuid.UUID | None = Ref("refscope_node.id", on_delete=OnDelete.SET_NULL, default=None)


class _Bookmark(BaseTable, table=True):
    """Not tenant-scoped itself: a writer outside the tenancy still meets its scope."""

    __tablename__ = "refscope_bookmark"
    node_id: uuid.UUID = Ref("refscope_node.id", on_delete=OnDelete.CASCADE)


class _Product(BaseTable, SoftDeleteMixin, table=True):
    __tablename__ = "refscope_product"
    name: str = Field(max_length=50)


class _Line(BaseTable, table=True):
    __tablename__ = "refscope_line"
    product_id: uuid.UUID = Ref("refscope_product.id", on_delete=OnDelete.RESTRICT)
    note: str = Field(max_length=50, default="")


class _Category(BaseTable, table=True):
    __tablename__ = "refscope_category"
    name: str = Field(max_length=50)


class _Item(BaseTable, table=True):
    __tablename__ = "refscope_item"
    category_id: uuid.UUID = Ref("refscope_category.id", on_delete=OnDelete.RESTRICT)


# A table no model maps, and a two-column foreign key: both are left to the database.
_RAW = Table("refscope_raw", SQLModel.metadata, Column("id", Uuid, primary_key=True))


class _Pair(BaseTable, SoftDeleteMixin, table=True):
    __tablename__ = "refscope_pair"
    __table_args__ = (UniqueConstraint("left", "right"),)
    left: str = Field(max_length=10)
    right: str = Field(max_length=10)


class _Odd(BaseTable, table=True):
    __tablename__ = "refscope_odd"
    __table_args__ = (
        ForeignKeyConstraint(["pair_left", "pair_right"], ["refscope_pair.left", "refscope_pair.right"]),
    )
    raw_id: uuid.UUID | None = Ref("refscope_raw.id", on_delete=OnDelete.RESTRICT, default=None)
    pair_left: str | None = Field(default=None, max_length=10)
    pair_right: str | None = Field(default=None, max_length=10)


class _NodeCreate(BaseSchema):
    name: str


class _EdgeCreate(BaseSchema):
    source_id: uuid.UUID
    target_id: uuid.UUID | None = None


class _EdgeUpdate(BaseUpdateSchema):
    target_id: uuid.UUID | None = None


class _BookmarkCreate(BaseSchema):
    node_id: uuid.UUID


class _ProductCreate(BaseSchema):
    name: str


class _LineCreate(BaseSchema):
    product_id: uuid.UUID
    note: str = ""


class _LineUpdate(BaseUpdateSchema):
    note: str | None = None


class _CategoryCreate(BaseSchema):
    name: str


class _ItemCreate(BaseSchema):
    category_id: uuid.UUID


class _PairCreate(BaseSchema):
    left: str
    right: str


class _OddCreate(BaseSchema):
    raw_id: uuid.UUID | None = None
    pair_left: str | None = None
    pair_right: str | None = None


class _Nodes(TenantScopedService[_Node, _NodeCreate, BaseUpdateSchema]):
    model = _Node


class _Edges(TenantScopedService[_Edge, _EdgeCreate, _EdgeUpdate]):
    model = _Edge


class _Bookmarks(BaseService[_Bookmark, _BookmarkCreate, BaseUpdateSchema]):
    model = _Bookmark


class _Products(BaseService[_Product, _ProductCreate, BaseUpdateSchema]):
    model = _Product


class _Lines(BaseService[_Line, _LineCreate, _LineUpdate]):
    model = _Line


class _Categories(BaseService[_Category, _CategoryCreate, BaseUpdateSchema]):
    model = _Category


class _Items(BaseService[_Item, _ItemCreate, BaseUpdateSchema]):
    model = _Item


class _Pairs(BaseService[_Pair, _PairCreate, BaseUpdateSchema]):
    model = _Pair


class _Odds(BaseService[_Odd, _OddCreate, BaseUpdateSchema]):
    model = _Odd


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(connection, _record) -> None:  # type: ignore[no-untyped-def]
        connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as active:
            yield active
    finally:
        engine.dispose()


def _node(session: Session, tenant: uuid.UUID, name: str) -> _Node:
    with tenant_context(tenant):
        return _Nodes().create(session, _NodeCreate(name=name))


def test_a_reference_into_another_tenant_fails_as_a_missing_one_does(session: Session) -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    a1 = _node(session, tenant_a, "a1")
    b1 = _node(session, tenant_b, "b1")

    with tenant_context(tenant_a):
        assert _Edges().create(session, _EdgeCreate(source_id=a1.id)).source_id == a1.id
        with pytest.raises(ConflictError) as across:
            _Edges().create(session, _EdgeCreate(source_id=b1.id))
        with pytest.raises(ConflictError) as missing:
            _Edges().create(session, _EdgeCreate(source_id=uuid.uuid4()))

    assert across.value.message == missing.value.message == _REFUSAL
    assert across.value.log_context == {
        "reason": "reference_out_of_scope",
        "reference": "refscope_edge.source_id",
        "target": "refscope_node.id",
    }
    # The database refuses a missing target of an unscoped model in the same words.
    with pytest.raises(ConflictError) as database:
        _Items().create(session, _ItemCreate(category_id=uuid.uuid4()))
    assert database.value.message == _REFUSAL
    assert "integrity_error" in database.value.log_context


def test_an_update_cannot_repoint_a_reference_across_tenants(session: Session) -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    a1, a2 = _node(session, tenant_a, "a1"), _node(session, tenant_a, "a2")
    b1 = _node(session, tenant_b, "b1")

    with tenant_context(tenant_a):
        edge = _Edges().create(session, _EdgeCreate(source_id=a1.id))
        with pytest.raises(ConflictError):
            _Edges().update(session, edge.id, _EdgeUpdate(version=edge.version, target_id=b1.id))
        session.expire_all()
        unchanged = _Edges().get(session, edge.id)
        assert unchanged.target_id is None  # the refused change was rolled back

        moved = _Edges().update(
            session, edge.id, _EdgeUpdate(version=unchanged.version, target_id=a2.id)
        )
        assert moved.target_id == a2.id


def test_a_writer_outside_the_tenancy_still_meets_the_targets_scope(session: Session) -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    a1 = _node(session, tenant_a, "a1")
    b1 = _node(session, tenant_b, "b1")

    with tenant_context(tenant_a):
        assert _Bookmarks().create(session, _BookmarkCreate(node_id=a1.id)).node_id == a1.id
        with pytest.raises(ConflictError):
            _Bookmarks().create(session, _BookmarkCreate(node_id=b1.id))
    with pytest.raises(ConflictError):  # no tenant at all sees no tenant's rows
        _Bookmarks().create(session, _BookmarkCreate(node_id=a1.id))


def test_an_untouched_pointer_to_a_soft_deleted_row_does_not_block_an_edit(session: Session) -> None:
    product = _Products().create(session, _ProductCreate(name="kettle"))
    line = _Lines().create(session, _LineCreate(product_id=product.id))
    _Products().delete(session, product.id)

    edited = _Lines().update(session, line.id, _LineUpdate(version=line.version, note="kept"))
    assert edited.note == "kept"
    with pytest.raises(ConflictError):  # a new pointer at it is a pointer at nothing
        _Lines().create(session, _LineCreate(product_id=product.id))


def test_an_unscoped_target_is_left_to_the_database(session: Session) -> None:
    category = _Categories().create(session, _CategoryCreate(name="tools"))
    statements: list[str] = []

    def _record(_conn, _cursor, statement, *_args) -> None:  # type: ignore[no-untyped-def]
        statements.append(statement)

    event.listen(session.get_bind(), "before_cursor_execute", _record)
    try:
        _Items().create(session, _ItemCreate(category_id=category.id))
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", _record)
    assert not any(
        statement.lstrip().upper().startswith("SELECT") and "refscope_category" in statement
        for statement in statements
    )


def test_unmapped_targets_and_multi_column_keys_are_left_to_the_database(session: Session) -> None:
    raw_id = uuid.uuid4()
    with session.get_bind().begin() as connection:
        connection.execute(_RAW.insert().values(id=raw_id))
    # The pair's target is soft-deleted, so a single-column reference to it would be
    # refused; a two-column one is not read by the check at all.
    pair = _Pairs().create(session, _PairCreate(left="a", right="b"))
    _Pairs().delete(session, pair.id)
    odd = _Odds().create(session, _OddCreate(raw_id=raw_id, pair_left="a", pair_right="b"))
    assert (odd.raw_id, odd.pair_left) == (raw_id, "a")


def test_a_non_mapped_stand_in_carries_no_reference(session: Session) -> None:
    assert refuse_out_of_scope_references(session, object(), created=True) is None
