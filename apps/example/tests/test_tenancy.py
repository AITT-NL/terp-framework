"""Tenant scoping composes via the kernel's scope-predicate registry — core stays agnostic.

``_Widget`` is tenant-scoped purely by mixing in ``TenantScopedMixin`` and giving
it a ``TenantScopedService``; the kernel ships no tenant column or predicate, and the
tenancy capability registers its row predicate centrally (ADR 0017).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine, select

from terp.capabilities.tenancy import (
    TenantContextError,
    TenantScopedMixin,
    TenantScopedService,
    current_tenant_id,
    tenant_context,
)
from terp.core import BaseSchema, BaseTable, BaseUpdateSchema


class _Widget(BaseTable, TenantScopedMixin, table=True):
    __tablename__ = "tenancy_test_widget"
    name: str = Field(max_length=50)


class _WidgetCreate(BaseSchema):
    name: str


class _WidgetUpdate(BaseUpdateSchema):
    name: str | None = None


class _OverWideWidgetCreate(BaseSchema):
    # Deliberately over-wide (tests are not arch-scanned): a client must not be able
    # to forge any framework-managed column through a tenant-scoped create.
    name: str = Field(max_length=50)
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    version: int = 999
    tenant_id: uuid.UUID = Field(default_factory=uuid.uuid4)


class _WidgetService(TenantScopedService[_Widget, _WidgetCreate, _WidgetUpdate]):
    model = _Widget


widgets = _WidgetService()


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as active:
            yield active
    finally:
        engine.dispose()


def test_reads_are_scoped_to_the_current_tenant(session: Session) -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    with tenant_context(tenant_a):
        widgets.create(session, _WidgetCreate(name="a1"))
    with tenant_context(tenant_b):
        widgets.create(session, _WidgetCreate(name="b1"))
        widgets.create(session, _WidgetCreate(name="b2"))

    with tenant_context(tenant_a):
        rows, total = widgets.list(session, skip=0, limit=100)
        assert total == 1
        assert {w.name for w in rows} == {"a1"}
    with tenant_context(tenant_b):
        rows, total = widgets.list(session, skip=0, limit=100)
        assert total == 2
        assert {w.name for w in rows} == {"b1", "b2"}


def test_tenant_context_nested_scope_restores_prior_tenant() -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    assert current_tenant_id() is None
    with tenant_context(tenant_a):
        assert current_tenant_id() == tenant_a
        with tenant_context(tenant_b):
            assert current_tenant_id() == tenant_b
        assert current_tenant_id() == tenant_a
    assert current_tenant_id() is None


def test_create_stamps_the_current_tenant(session: Session) -> None:
    tenant_a = uuid.uuid4()
    with tenant_context(tenant_a):
        widget = widgets.create(session, _WidgetCreate(name="x"))
    assert widget.tenant_id == tenant_a


def test_a_missing_tenant_reads_nothing(session: Session) -> None:
    tenant_a = uuid.uuid4()
    with tenant_context(tenant_a):
        widgets.create(session, _WidgetCreate(name="a1"))
    # No tenant in context → the scoped read fails closed.
    rows, total = widgets.list(session, skip=0, limit=100)
    assert (rows, total) == ([], 0)


def test_create_without_a_tenant_is_rejected(session: Session) -> None:
    with pytest.raises(TenantContextError):
        widgets.create(session, _WidgetCreate(name="orphan"))


def test_create_ignores_client_supplied_managed_columns(session: Session) -> None:
    # A tenant-scoped create strips framework-managed columns just like BaseService:
    # the client cannot forge the id/version, and the tenant comes from context only.
    real_tenant = uuid.uuid4()
    forged_id, forged_tenant = uuid.uuid4(), uuid.uuid4()
    with tenant_context(real_tenant):
        widget = widgets.create(
            session,
            _OverWideWidgetCreate(
                name="x", id=forged_id, version=999, tenant_id=forged_tenant
            ),
        )
    assert widget.id != forged_id
    assert widget.version == 1
    assert widget.tenant_id == real_tenant


def test_unscoped_query_is_the_explicit_escape_hatch(session: Session) -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    with tenant_context(tenant_a):
        widgets.create(session, _WidgetCreate(name="a1"))
    with tenant_context(tenant_b):
        widgets.create(session, _WidgetCreate(name="b1"))
    # Scoping lives in the registered tenant predicate (applied by base_query); a
    # deliberate raw query over all tenants is the explicit, greppable escape hatch.
    all_rows = session.exec(select(_Widget)).all()
    assert len(all_rows) == 2
