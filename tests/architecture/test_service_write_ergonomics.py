"""Two write-chokepoint guarantees a module used to have to discover the hard way.

**JSON columns.** A typed value object stored in a JSON column is the natural shape
for a document a module validates once and stores whole. Dumping the input schema in
pydantic's *python* mode left a ``UUID`` / ``datetime`` / ``Enum`` inside that document
as a Python object, and it died at ``flush`` with ``TypeError: Object of type UUID is
not JSON serializable`` — a message naming neither the field nor the fix (a
``PlainSerializer`` annotation the guide never mentioned). The chokepoint knows the
column types, so it dumps exactly the JSON-backed fields in ``json`` mode.

**Append-only tables.** A ledger row, an immutable revision, a captured snapshot: the
immutability guarantee used to live in *not mounting an update route* — a guarantee
made of absent code, which evaporates the day someone adds one. ``append_only = True``
states it on the service, and the chokepoint refuses every post-insert write.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import JSON
from sqlmodel import Field, Session, SQLModel, create_engine

from terp.core import BaseSchema, BaseService, BaseTable, BaseUpdateSchema
from terp.core.audit import AuditAction
from terp.core.errors import ConflictError


class _Doc(BaseTable, table=True):
    __tablename__ = "write_ergonomics_doc"

    name: str = Field(max_length=50)
    document: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)


class _DocCreate(BaseSchema):
    name: str
    document: dict[str, Any]


class _DocUpdate(BaseUpdateSchema):
    document: dict[str, Any] | None = None


class _DocService(BaseService[_Doc, _DocCreate, _DocUpdate]):
    model = _Doc


class _Revision(BaseTable, table=True):
    __tablename__ = "write_ergonomics_revision"

    label: str = Field(max_length=50)


class _RevisionCreate(BaseSchema):
    label: str


class _RevisionUpdate(BaseUpdateSchema):
    label: str | None = None


class _RevisionService(BaseService[_Revision, _RevisionCreate, _RevisionUpdate]):
    model = _Revision
    append_only = True


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as active:
        yield active
    engine.dispose()


def test_uuid_inside_a_json_column_survives_create(session: Session) -> None:
    """The failure that cost a module a ``PlainSerializer`` workaround: an id in a document."""
    identifier = uuid.uuid4()
    row = _DocService().create(
        session, _DocCreate(name="mapping", document={"source_id": identifier})
    )
    assert row.document["source_id"] == str(identifier)


def test_datetime_inside_a_json_column_survives_update(session: Session) -> None:
    service = _DocService()
    row = service.create(session, _DocCreate(name="mapping", document={}))
    moment = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    updated = service.update(
        session, row.id, _DocUpdate(version=row.version, document={"at": moment})
    )
    assert isinstance(updated.document["at"], str)


def test_non_json_columns_keep_their_native_python_value(session: Session) -> None:
    """Only JSON-backed fields switch modes — a plain column still gets its Python value."""
    payload = _DocService()._dump(_DocCreate(name="mapping", document={}))
    assert payload["name"] == "mapping"


def test_append_only_service_refuses_update(session: Session) -> None:
    service = _RevisionService()
    row = service.create(session, _RevisionCreate(label="v1"))
    with pytest.raises(ConflictError):
        service.update(session, row.id, _RevisionUpdate(version=row.version, label="v2"))


def test_append_only_service_refuses_delete(session: Session) -> None:
    service = _RevisionService()
    row = service.create(session, _RevisionCreate(label="v1"))
    with pytest.raises(ConflictError):
        service.delete(session, row.id)


def test_append_only_refusal_reaches_a_bespoke_save(session: Session) -> None:
    """The guarantee is at the chokepoint, so a hand-written mutation cannot slip past."""
    service = _RevisionService()
    row = service.create(session, _RevisionCreate(label="v1"))
    row.label = "v2"
    with pytest.raises(ConflictError):
        service._save(session, row, AuditAction.UPDATED)
