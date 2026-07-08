"""Unit gate for the actor-stamping model trait (ADR 0012).

Drives :class:`~terp.core.BaseService` against synthetic models over a real
in-memory engine to prove the auto-fill: a :class:`~terp.core.ActorStampedMixin`
row gets ``created_by_id`` on insert and ``modified_by_id`` on every write (a
soft-delete records *who* deleted), the actor comes from the request-scoped
``audit_actor_ctx``, an unbound actor leaves the stamps ``None`` (best-effort),
and a non-stamped model is untouched — the fail-closed/edge paths the end-to-end
reference tests do not all reach, so the framework holds 100% line coverage.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine

from terp.core import (
    ActorStampedMixin,
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    NotFoundError,
    SoftDeleteMixin,
)
from terp.core.audit import bind_audit_actor


class _Doc(BaseTable, ActorStampedMixin, table=True):
    __tablename__ = "_actor_doc"
    label: str = Field(max_length=50)


class _SoftDoc(BaseTable, SoftDeleteMixin, ActorStampedMixin, table=True):
    __tablename__ = "_actor_soft_doc"
    label: str = Field(max_length=50)


class _Plain(BaseTable, table=True):
    __tablename__ = "_actor_plain"
    label: str = Field(max_length=50)


class _DocCreate(BaseSchema):
    label: str = Field(max_length=50)


class _DocUpdate(BaseUpdateSchema):
    label: str | None = Field(default=None, max_length=50)


class _DocService(BaseService[_Doc, _DocCreate, _DocUpdate]):
    model = _Doc


class _SoftDocService(BaseService[_SoftDoc, _DocCreate, _DocUpdate]):
    model = _SoftDoc


class _PlainService(BaseService[_Plain, _DocCreate, _DocUpdate]):
    model = _Plain


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as active:
            yield active
    finally:
        engine.dispose()


def test_create_stamps_creator_and_modifier(session: Session) -> None:
    actor = uuid.uuid4()
    with bind_audit_actor(actor):
        doc = _DocService().create(session, _DocCreate(label="x"))
    # On insert both stamps carry the acting principal.
    assert doc.created_by_id == actor
    assert doc.modified_by_id == actor


def test_update_advances_only_the_modifier(session: Session) -> None:
    creator, editor = uuid.uuid4(), uuid.uuid4()
    service = _DocService()
    with bind_audit_actor(creator):
        doc = service.create(session, _DocCreate(label="x"))
    with bind_audit_actor(editor):
        updated = service.update(session, doc.id, _DocUpdate(label="y", version=doc.version))
    # created_by is immutable; modified_by tracks the latest writer.
    assert updated.created_by_id == creator
    assert updated.modified_by_id == editor


def test_soft_delete_records_who_deleted(session: Session) -> None:
    creator, remover = uuid.uuid4(), uuid.uuid4()
    service = _SoftDocService()
    with bind_audit_actor(creator):
        doc = service.create(session, _DocCreate(label="x"))
    with bind_audit_actor(remover):
        service.delete(session, doc.id)

    # The soft-deleted row vanishes from reads but retains its provenance, and the
    # soft-delete (routed through _save) recorded who performed it.
    with pytest.raises(NotFoundError):
        service.get(session, doc.id)
    row = session.get(_SoftDoc, doc.id)
    assert row is not None
    assert row.deleted_at is not None
    assert row.created_by_id == creator
    assert row.modified_by_id == remover


def test_unbound_actor_leaves_stamps_none(session: Session) -> None:
    # Outside a request (no actor bound) stamping is best-effort: None, not an error.
    doc = _DocService().create(session, _DocCreate(label="x"))
    assert doc.created_by_id is None
    assert doc.modified_by_id is None


def test_non_stamped_model_is_untouched(session: Session) -> None:
    # A model that does not compose the mixin has no stamp columns and is skipped.
    with bind_audit_actor(uuid.uuid4()):
        plain = _PlainService().create(session, _DocCreate(label="x"))
    assert not hasattr(plain, "created_by_id")
    assert not hasattr(plain, "modified_by_id")
