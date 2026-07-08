"""``build_crud_router`` (Tier-C sugar, ADR 0023): the generated CRUD routes are secure + complete.

One factory call produces the five canonical routes over a ``BaseService`` + DTOs;
this exercises the full lifecycle (create / list / get / update / delete) plus the
404 and optimistic-concurrency (409) paths, all returning the read DTO.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine

from terp.core import (
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    ModuleSpec,
    Policy,
    build_crud_router,
    create_app,
    get_session,
)


class _Widget(BaseTable, table=True):
    __tablename__ = "crud_widget"
    name: str = Field(max_length=100)


class _WidgetCreate(BaseSchema):
    name: str = Field(max_length=100)


class _WidgetUpdate(BaseUpdateSchema):
    name: str | None = Field(default=None, max_length=100)


class _WidgetRead(BaseSchema):
    id: uuid.UUID
    name: str
    version: int


class _WidgetService(BaseService[_Widget, _WidgetCreate, _WidgetUpdate]):
    model = _Widget


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine: Engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    router = build_crud_router(
        _WidgetService(),
        read_schema=_WidgetRead,
        create_schema=_WidgetCreate,
        update_schema=_WidgetUpdate,
        tags=["widgets"],
    )
    app = create_app(
        [
            ModuleSpec(
                name="widgets",
                router=router,
                policy=Policy.public_write(reason="factory under test"),
            )
        ]
    )

    def _override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override
    try:
        yield TestClient(app)
    finally:
        engine.dispose()


def test_full_crud_lifecycle(client: TestClient) -> None:
    created = client.post("/api/v1/widgets/", json={"name": "one"})
    assert created.status_code == 201
    body = created.json()
    widget_id = body["id"]
    assert body["name"] == "one" and body["version"] == 1

    listing = client.get("/api/v1/widgets/").json()
    assert listing["total"] == 1
    assert [w["name"] for w in listing["items"]] == ["one"]

    got = client.get(f"/api/v1/widgets/{widget_id}")
    assert got.status_code == 200 and got.json()["name"] == "one"

    updated = client.patch(
        f"/api/v1/widgets/{widget_id}", json={"name": "two", "version": 1}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "two" and updated.json()["version"] == 2

    assert client.delete(f"/api/v1/widgets/{widget_id}").status_code == 204
    assert client.get(f"/api/v1/widgets/{widget_id}").status_code == 404


def test_get_missing_is_404(client: TestClient) -> None:
    assert client.get(f"/api/v1/widgets/{uuid.uuid4()}").status_code == 404


def test_stale_update_conflicts_409(client: TestClient) -> None:
    created = client.post("/api/v1/widgets/", json={"name": "x"}).json()
    stale = client.patch(
        f"/api/v1/widgets/{created['id']}", json={"name": "y", "version": 999}
    )
    assert stale.status_code == 409
