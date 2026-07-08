"""Runtime layer of the response-model data-leak guard (ADR 0020).

``create_app`` refuses to boot when any mounted route serializes a ``table=True``
ORM model as its ``response_model`` -- directly or wrapped in ``Page[...]`` /
``list[...]`` -- so a persisted column such as a password hash can never leak
through the API boundary. This is the fail-closed *runtime* control; it pairs
with the build-time ``terp.arch`` ``response_model_not_table_model`` rule
(``tests/architecture/test_arch_harness.py``).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import APIRouter, FastAPI
from sqlmodel import Field

from terp.core import BaseSchema, BaseTable, ModuleSpec, Page, Policy, create_app
from terp.core.app import BootError


class _Secret(BaseTable, table=True):
    """A persisted model carrying a column that must never be serialized out."""

    __tablename__ = "rmg_secret"

    hashed_password: str = Field(max_length=128)


class _SecretRead(BaseSchema):
    """The safe read DTO: it lists only non-sensitive fields."""

    id: uuid.UUID


def _spec(router: APIRouter) -> ModuleSpec:
    return ModuleSpec(name="rmg", router=router, policy=Policy.default())


def test_boot_rejects_table_model_wrapped_in_page() -> None:
    router = APIRouter()

    @router.get("/", response_model=Page[_Secret])
    def list_secrets() -> Page[_Secret]: ...

    with pytest.raises(BootError, match="_Secret"):
        create_app([_spec(router)])


def test_boot_rejects_a_bare_table_model() -> None:
    router = APIRouter()

    @router.get("/{secret_id}", response_model=_Secret)
    def get_secret(secret_id: uuid.UUID) -> _Secret: ...

    with pytest.raises(BootError, match="response_model"):
        create_app([_spec(router)])


def test_boot_rejects_a_table_model_in_a_list() -> None:
    router = APIRouter()

    @router.get("/", response_model=list[_Secret])
    def list_secrets() -> list[_Secret]: ...

    with pytest.raises(BootError, match="_Secret"):
        create_app([_spec(router)])


def test_boot_rejects_a_table_model_on_a_nested_router() -> None:
    # A route declared on an *included* sub-router must still be guarded -- FastAPI
    # keeps it as a nested _IncludedRouter, not a flat entry in router.routes.
    inner = APIRouter()

    @inner.get("/inner", response_model=_Secret)
    def inner_route() -> _Secret: ...

    outer = APIRouter()
    outer.include_router(inner, prefix="/sub")

    with pytest.raises(BootError, match="_Secret"):
        create_app([_spec(outer)])


def test_boot_accepts_a_read_dto() -> None:
    router = APIRouter()

    @router.get("/", response_model=Page[_SecretRead])
    def list_secrets() -> Page[_SecretRead]: ...

    @router.delete("/{secret_id}", status_code=204)
    def remove(secret_id: uuid.UUID) -> None: ...

    app = create_app([_spec(router)])
    assert isinstance(app, FastAPI)
