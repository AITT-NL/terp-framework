"""Capability writes flow through the audited chokepoint (behavioral regression for C1).

Tenant-scoped creates and RBAC grant/revoke previously wrote raw to the session and
emitted **no** audit record. They now route through ``BaseService._save`` /
``_remove``, so each lands an audit record. This asserts the runtime behavior; the
build-time guarantee that no capability bypasses the chokepoint lives in
``test_capability_arch.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine

from terp.core import BaseSchema, BaseTable, BaseUpdateSchema
from terp.core.audit import AuditAction, AuditRecord, set_audit_sink

from terp.capabilities.access import AccessService
from terp.capabilities.access.models import Grant  # noqa: F401  (register table)
from terp.capabilities.tenancy import (
    TenantScopedMixin,
    TenantScopedService,
    tenant_context,
)


class _ScopedThing(BaseTable, TenantScopedMixin, table=True):
    __tablename__ = "audited_scoped_thing"
    name: str = Field(max_length=50)


class _ScopedThingCreate(BaseSchema):
    name: str


class _ScopedThingUpdate(BaseUpdateSchema):
    name: str | None = None


class _ScopedThingService(
    TenantScopedService[_ScopedThing, _ScopedThingCreate, _ScopedThingUpdate]
):
    model = _ScopedThing


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


def _capture_audit() -> list[AuditRecord]:
    """Install a capturing audit sink and return the list it appends to."""
    records: list[AuditRecord] = []
    set_audit_sink(lambda _session, record, _policy: records.append(record))
    return records


def test_tenant_scoped_create_is_audited(session: Session) -> None:
    records = _capture_audit()
    with tenant_context(uuid.uuid4()):
        _ScopedThingService().create(session, _ScopedThingCreate(name="w"))
    assert [record.action for record in records] == [AuditAction.CREATED]
    assert records[0].target_type == "_ScopedThing"


def test_access_grant_and_revoke_are_audited(session: Session) -> None:
    records = _capture_audit()
    service = AccessService()
    subject = uuid.uuid4()
    service.grant(session, subject, "billing:write")
    service.revoke(session, subject, "billing:write")
    assert [record.action for record in records] == [
        AuditAction.CREATED,
        AuditAction.DELETED,
    ]
    assert all(record.target_type == "Grant" for record in records)


def test_idempotent_grant_is_audited_once(session: Session) -> None:
    records = _capture_audit()
    service = AccessService()
    subject = uuid.uuid4()
    service.grant(session, subject, "billing:write")
    service.grant(session, subject, "billing:write")  # re-grant: returns existing
    assert [record.action for record in records] == [AuditAction.CREATED]
