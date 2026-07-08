"""BaseService strips framework-managed columns from inbound input (M6, over-posting).

``create`` / ``update`` copy a schema's fields onto the model, so a client that
smuggles a managed column (``id`` / ``version`` / ``tenant_id`` / actor stamps)
through an over-wide payload must not be able to set it. The runtime strip is the
fail-closed half of the control whose build-time half is the
``input_schemas_exclude_managed_columns`` arch rule; synthetic over-wide schemas
(which the rule forbids in real app code, but ``tests/`` is not arch-scanned) drive
the strip directly so the fail-closed path is proven, not merely asserted.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine

from terp.core import BaseSchema, BaseService, BaseTable, BaseUpdateSchema
from terp.core.base_service import _MANAGED_INPUT_COLUMNS


class _Widget(BaseTable, table=True):
    __tablename__ = "_overpost_widget"
    label: str = Field(max_length=50)


class _OverWideCreate(BaseSchema):
    # Deliberately over-wide: a client must not be able to forge these.
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    version: int = 999
    label: str = Field(max_length=50)


class _OverWideUpdate(BaseUpdateSchema):
    id: uuid.UUID | None = None
    label: str | None = Field(default=None, max_length=50)


class _WidgetService(BaseService[_Widget, _OverWideCreate, _OverWideUpdate]):
    model = _Widget


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


def test_managed_input_columns_is_the_framework_column_set() -> None:
    # The runtime strip set is the contract; pin it so a drift is a visible change.
    assert _MANAGED_INPUT_COLUMNS == frozenset(
        {
            "id",
            "created_at",
            "updated_at",
            "version",
            "deleted_at",
            "tenant_id",
            "created_by_id",
            "modified_by_id",
            "owner_id",
            "token_version",
        }
    )


def test_without_managed_columns_keeps_only_domain_fields() -> None:
    safe = BaseService._without_managed_columns(
        {
            "id": uuid.uuid4(),
            "version": 7,
            "tenant_id": uuid.uuid4(),
            "token_version": 9,
            "label": "x",
        }
    )
    assert safe == {"label": "x"}


def test_create_ignores_client_supplied_managed_columns(session: Session) -> None:
    forged_id = uuid.uuid4()
    widget = _WidgetService().create(
        session, _OverWideCreate(id=forged_id, version=999, label="x")
    )
    # The client's id / version were stripped; the framework assigned its own.
    assert widget.id != forged_id
    assert widget.version == 1
    assert widget.label == "x"


def test_update_ignores_client_supplied_managed_columns(session: Session) -> None:
    widget = _WidgetService().create(session, _OverWideCreate(label="seed"))
    original_id = widget.id
    updated = _WidgetService().update(
        session,
        original_id,
        _OverWideUpdate(id=uuid.uuid4(), version=widget.version, label="renamed"),
    )
    # The id is immutable through update; only the domain field changed.
    assert updated.id == original_id
    assert updated.label == "renamed"
