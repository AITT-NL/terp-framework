"""HTTP regression tests for row scope and rejected writes that share a session."""

import uuid
from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy.orm import aliased, relationship, selectinload, joinedload
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Relationship, Session, SQLModel, create_engine, select
from starlette.middleware import Middleware

from terp.core import (
    EDITOR,
    AuditAction,
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    ModuleSpec,
    OwnedMixin,
    PermissionDeniedError,
    Policy,
    Principal,
    Ref,
    OnDelete,
    SessionDep,
    SoftDeleteMixin,
    create_app,
)
from terp.core.audit import bind_audit_actor
from terp.core.db import get_session
from terp.core._internal.session_guard import WriteGuardedSession
from terp.capabilities.audit import AuditEvent, persist_audit
from terp.capabilities.tenancy import (
    TenantScopedMixin,
    TenantScopedService,
    tenant_context,
)
from terp.capabilities.tenancy.middleware import TenantMiddleware


class Doc(BaseTable, OwnedMixin, SoftDeleteMixin, table=True):
    __tablename__ = "isolation_document"
    label: str = Field(max_length=50)


class Create(BaseSchema):
    label: str = Field(max_length=50)


class Update(BaseUpdateSchema):
    label: str | None = Field(default=None, max_length=50)


class Documents(BaseService[Doc, Create, Update]):
    model = Doc


class Item(BaseTable, TenantScopedMixin, SoftDeleteMixin, table=True):
    __tablename__ = "isolation_item"
    category_id: uuid.UUID = Ref("isolation_category.id", on_delete=OnDelete.RESTRICT)
    label: str = Field(max_length=50)


class Category(BaseTable, table=True):
    __tablename__ = "isolation_category"
    label: str = Field(max_length=50)
    items: list[Item] = Relationship(sa_relationship=relationship(Item))


class ItemCreate(Create):
    category_id: uuid.UUID


class Items(TenantScopedService[Item, ItemCreate, Update]):
    model = Item


class Categories(BaseService[Category, Create, Update]):
    model = Category


class CategoryRead(BaseSchema):
    items: list[str] = Field(max_length=20)


@pytest.fixture
def engine():
    value = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(value)
    yield value
    value.dispose()


def guarded_factory(engine):
    def sessions() -> Iterator[Session]:
        with WriteGuardedSession(engine) as session:
            yield session

    return sessions


def test_relevant_static_rules_accept_relationship_service_reads(tmp_path):
    from terp.arch.rules.traits import (
        check_reads_use_base_query,
        check_no_manual_scope_filtering,
        check_tenant_scoped_models_use_scoped_service,
    )
    from terp.arch.rules.persistence import check_mutations_emit_audit

    source = """
from terp.core import BaseTable, BaseService, BaseSchema, BaseUpdateSchema, Ref, OnDelete
from terp.capabilities.tenancy import TenantScopedMixin, TenantScopedService
from sqlmodel import Field, Relationship, Session
from sqlalchemy.orm import selectinload
import uuid
class Item(BaseTable, TenantScopedMixin, SoftDeleteMixin, table=True):
    category_id: uuid.UUID = Ref("category.id", on_delete=OnDelete.RESTRICT)
    label: str = Field(max_length=50)
class Category(BaseTable, table=True):
    items: list[Item] = Relationship()
class Items(TenantScopedService[Item, BaseSchema, BaseUpdateSchema]):
    model = Item
class Categories(BaseService[Category, BaseSchema, BaseUpdateSchema]):
    model = Category
    def lazy_labels(self, session: Session, category_id: uuid.UUID):
        return [item.label for item in self.get(session, category_id).items]
    def eager_labels(self, session: Session):
        query = self.base_query().options(selectinload(Category.items))
        return [item.label for parent in session.exec(query) for item in parent.items]
"""
    (tmp_path / "service.py").write_text(source)
    for check in (
        check_reads_use_base_query,
        check_no_manual_scope_filtering,
        check_tenant_scoped_models_use_scoped_service,
        check_mutations_emit_audit,
    ):
        assert check(tmp_path) == [], check.__name__


def test_denied_delete_cannot_commit_with_later_authorized_http_write(engine):
    owner, caller = uuid.uuid4(), uuid.uuid4()
    with WriteGuardedSession(engine) as session, bind_audit_actor(owner):
        victim_id = Documents().create(session, Create(label="victim")).id
    with WriteGuardedSession(engine) as session, bind_audit_actor(caller):
        own_id = Documents().create(session, Create(label="own")).id
    router = APIRouter()

    @router.post("/batch", response_model=dict[str, bool])
    def batch(session: SessionDep, victim: uuid.UUID, own: uuid.UUID):
        try:
            Documents().delete(session, victim)
        except PermissionDeniedError:
            denied = True
        else:
            denied = False
        row = Documents().get(session, own)
        Documents().update(
            session, own, Update(version=row.version, label="allowed update")
        )
        return {"delete_denied": denied}

    app = create_app(
        [ModuleSpec(name="isolation", router=router, policy=Policy.default())],
        principal_provider=lambda: Principal(id=caller, role=EDITOR),
        audit_sink=persist_audit,
    )
    app.dependency_overrides[get_session] = guarded_factory(engine)
    response = TestClient(app).post(
        "/api/v1/isolation/batch", params={"victim": str(victim_id), "own": str(own_id)}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"delete_denied": True}
    with Session(engine) as session:
        victim = session.get(Doc, victim_id)
        assert victim.deleted_at is None
        assert session.get(Doc, own_id).label == "allowed update"
        records = session.exec(select(AuditEvent)).all()
    assert any(
        record.target_id == str(own_id) and record.action == AuditAction.UPDATED.value
        for record in records
    ), "the allowed update must commit its audit event"
    assert all(record.target_id != str(victim_id) for record in records)


@pytest.mark.parametrize("loading", ["lazy", "selectin", "joined"])
@pytest.mark.parametrize("has_tenant", [True, False])
def test_relationship_http_response_keeps_tenant_scope(engine, loading, has_tenant):
    tenant_a, tenant_b, caller = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with WriteGuardedSession(engine) as session:
        category_id = Categories().create(session, Create(label="shared category")).id
    with WriteGuardedSession(engine) as session, tenant_context(tenant_a):
        Items().create(session, ItemCreate(category_id=category_id, label="tenant A"))
        hidden = Items().create(
            session, ItemCreate(category_id=category_id, label="deleted A")
        )
        Items().delete(session, hidden.id)
    with WriteGuardedSession(engine) as session, tenant_context(tenant_b):
        Items().create(
            session, ItemCreate(category_id=category_id, label="tenant B private value")
        )
    router = APIRouter()

    @router.get("/category", response_model=CategoryRead)
    def category(session: SessionDep):
        own, total = Items().list(session, skip=0, limit=20)
        assert [item.label for item in own] == (["tenant A"] if has_tenant else [])
        if loading == "lazy":
            parent = Categories().get(session, category_id)
        else:
            loader = selectinload if loading == "selectin" else joinedload
            query = (
                Categories()
                .base_query()
                .where(Category.id == category_id)
                .options(loader(Category.items))
            )
            parent = session.exec(query).unique().one()
        return CategoryRead(items=[item.label for item in parent.items])

    app = create_app(
        [ModuleSpec(name="isolation", router=router, policy=Policy.default())],
        principal_provider=lambda: Principal(id=caller, role=EDITOR),
        middleware=[
            Middleware(
                TenantMiddleware,
                resolve_tenant=lambda request: tenant_a if has_tenant else None,
            )
        ],
    )
    app.dependency_overrides[get_session] = guarded_factory(engine)
    response = TestClient(app).get("/api/v1/isolation/category")
    assert response.status_code == 200, response.text
    assert response.json() == {"items": ["tenant A"] if has_tenant else []}


def test_aliased_and_multi_entity_queries_keep_scope(engine):
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    with WriteGuardedSession(engine) as session:
        category_id = Categories().create(session, Create(label="shared")).id
    for tenant, label in ((tenant_a, "visible"), (tenant_b, "private")):
        with WriteGuardedSession(engine) as session, tenant_context(tenant):
            Items().create(session, ItemCreate(category_id=category_id, label=label))
    with WriteGuardedSession(engine) as session, tenant_context(tenant_a):
        child = aliased(Item)
        query = select(Category, child).join(child, Category.id == child.category_id)
        assert [item.label for parent, item in session.exec(query)] == ["visible"]
        assert [row[0].label for row in session.execute(select(child))] == ["visible"]
        assert len(session.exec(select(aliased(Category))).all()) == 1
        # Selecting only the shared parent must not reveal whether a hidden
        # child's private value matched a filter on an unprojected alias.
        hidden_match = (
            select(Category)
            .join(child, Category.id == child.category_id)
            .where(child.label == "private")
        )
        assert session.exec(hidden_match).all() == []


def test_lazy_relationship_cannot_retain_authority_after_context_changes(engine):
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    with WriteGuardedSession(engine) as session:
        category_id = Categories().create(session, Create(label="shared")).id
    for tenant, label in ((tenant_a, "first"), (tenant_b, "second")):
        with WriteGuardedSession(engine) as session, tenant_context(tenant):
            Items().create(session, ItemCreate(category_id=category_id, label=label))
    with WriteGuardedSession(engine) as session:
        with tenant_context(tenant_a):
            parent = Categories().get(session, category_id)
        # A session never widens a loaded object's original authority. The later
        # lazy load must also enforce the current scope and cannot return A's row.
        with tenant_context(tenant_b):
            assert parent.items == []
    with WriteGuardedSession(engine) as session, tenant_context(tenant_b):
        assert [
            item.label for item in Categories().get(session, category_id).items
        ] == ["second"]


@pytest.mark.parametrize("action", [AuditAction.CREATED, AuditAction.UPDATED])
def test_rejected_bespoke_save_leaves_no_dirty_owned_row(engine, action):
    owner, caller = uuid.uuid4(), uuid.uuid4()
    with WriteGuardedSession(engine) as session, bind_audit_actor(owner):
        target_id = Documents().create(session, Create(label="unchanged")).id
    with WriteGuardedSession(engine) as session, bind_audit_actor(caller):
        target = Documents().get(session, target_id)
        target.label = "unauthorized change"
        with pytest.raises(
            ValueError if action is AuditAction.CREATED else PermissionDeniedError
        ):
            Documents()._save(session, target, action)
        allowed_id = Documents().create(session, Create(label="allowed write")).id
    with Session(engine) as session:
        target = session.get(Doc, target_id)
        assert target.label == "unchanged"
        assert target.owner_id == owner
        allowed = session.get(Doc, allowed_id)
        assert allowed is not None and allowed.label == "allowed write"
        assert allowed.owner_id == caller


def test_non_framework_mapped_entities_keep_their_ordinary_read_behavior(engine):
    from sqlalchemy import Column, Integer, Table
    from sqlalchemy.orm import registry

    mapping = registry()
    table = Table(
        "plain_read_control", mapping.metadata, Column("id", Integer, primary_key=True)
    )

    class Plain:
        pass

    mapping.map_imperatively(Plain, table)
    table.create(engine)
    try:
        with engine.begin() as connection:
            connection.execute(table.insert().values(id=1))
        with WriteGuardedSession(engine) as session:
            assert [row.id for row in session.exec(select(Plain))] == [1]
            assert [row.id for row in session.exec(select(aliased(Plain)))] == [1]
    finally:
        mapping.dispose()
