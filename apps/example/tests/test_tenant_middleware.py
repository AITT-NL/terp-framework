"""End-to-end: the JWT ``tenant`` claim + ``TenantMiddleware`` bind request scope.

Proves the full chain the tenancy capability promised (ADR 0001, Decision 8's
deferral): auth signs a ``tenant`` claim into the token, the pure-ASGI
``TenantMiddleware`` resolves it per request and binds ``tenant_context``, and a
``TenantScopedService`` mounted on the real ``create_app`` then isolates rows by
tenant over HTTP — with the kernel still tenancy-agnostic.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine
from starlette.middleware import Middleware

from terp.capabilities.auth import (
    create_access_token,
    decode_access_token,
    get_principal,
    tenant_from_bearer,
)
from terp.capabilities.tenancy import (
    TenantMiddleware,
    TenantScopedMixin,
    TenantScopedService,
    current_tenant_id,
)
from terp.core import (
    BaseSchema,
    BaseTable,
    BaseUpdateSchema,
    ModuleSpec,
    Page,
    Policy,
    Roles,
    SessionDep,
    create_app,
    get_session,
)


# --- a tenant-scoped module, defined exactly as a client would --------------- #
class _Doc(BaseTable, TenantScopedMixin, table=True):
    __tablename__ = "tenant_mw_doc"
    title: str = Field(max_length=100)


class _DocCreate(BaseSchema):
    title: str = Field(max_length=100)


class _DocUpdate(BaseUpdateSchema):
    title: str | None = None


class _DocService(TenantScopedService[_Doc, _DocCreate, _DocUpdate]):
    model = _Doc


docs = _DocService()

_router = APIRouter(tags=["docs"])


@_router.get("/tenant", response_model=str)
async def read_bound_tenant() -> str:
    """Echo the tenant the middleware bound for this request (``"None"`` if unset)."""
    return str(current_tenant_id())


@_router.post("/", response_model=str)
async def create_doc(data: _DocCreate, session: SessionDep) -> str:
    return docs.create(session, data).title


@_router.get("/", response_model=Page[str])
async def list_docs(session: SessionDep) -> Page[str]:
    rows, total = docs.list(session, skip=0, limit=100)
    return Page[str](items=sorted(row.title for row in rows), total=total, skip=0, limit=100)


# --- fixtures ---------------------------------------------------------------- #
@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def app(engine: Engine) -> FastAPI:
    spec = ModuleSpec(
        name="docs",
        router=_router,
        policy=Policy.public_write(reason="scope under test is the tenant claim, not authz"),
    )
    application = create_app(
        [spec],
        principal_provider=get_principal,
        middleware=[Middleware(TenantMiddleware, resolve_tenant=tenant_from_bearer)],
    )

    def _session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    application.dependency_overrides[get_session] = _session_override
    return application


def _token(tenant: uuid.UUID | None) -> str:
    return create_access_token(subject=uuid.uuid4(), role=Roles.EDITOR, tenant=tenant)


def _client(app: FastAPI, tenant: uuid.UUID | None) -> TestClient:
    client = TestClient(app)
    if tenant is not None:
        client.headers["Authorization"] = f"Bearer {_token(tenant)}"
    return client


# --- the token claim --------------------------------------------------------- #
def test_access_token_carries_an_optional_tenant_claim() -> None:
    tenant, subject = uuid.uuid4(), uuid.uuid4()
    claims = decode_access_token(create_access_token(subject=subject, role=Roles.EDITOR, tenant=tenant))
    assert claims.subject == subject
    assert claims.tenant == tenant


def test_a_token_without_a_tenant_decodes_to_none() -> None:
    claims = decode_access_token(create_access_token(subject=uuid.uuid4(), role=Roles.VIEWER))
    assert claims.tenant is None


# --- the middleware ---------------------------------------------------------- #
def test_middleware_binds_the_tenant_from_the_token(app: FastAPI) -> None:
    tenant = uuid.uuid4()
    response = _client(app, tenant).get("/api/v1/docs/tenant")
    assert response.status_code == 200
    assert response.json() == str(tenant)


def test_middleware_leaves_the_tenant_unset_without_a_token(app: FastAPI) -> None:
    response = _client(app, None).get("/api/v1/docs/tenant")
    assert response.json() == "None"


def test_tenant_is_not_leaked_between_requests(app: FastAPI) -> None:
    tenant = uuid.uuid4()
    assert _client(app, tenant).get("/api/v1/docs/tenant").json() == str(tenant)
    # A subsequent request without a token must not see the prior tenant.
    assert _client(app, None).get("/api/v1/docs/tenant").json() == "None"


# --- the full chain: token claim → middleware → scoped service over HTTP ------ #
def test_scoped_service_isolates_rows_by_token_tenant(app: FastAPI) -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    client_a, client_b = _client(app, tenant_a), _client(app, tenant_b)

    assert client_a.post("/api/v1/docs/", json={"title": "a1"}).status_code == 200
    assert client_b.post("/api/v1/docs/", json={"title": "b1"}).status_code == 200
    assert client_b.post("/api/v1/docs/", json={"title": "b2"}).status_code == 200

    assert client_a.get("/api/v1/docs/").json()["items"] == ["a1"]
    assert client_b.get("/api/v1/docs/").json()["items"] == ["b1", "b2"]


def test_a_tokenless_write_is_rejected_fail_closed(app: FastAPI) -> None:
    # No tenant in context → the scoped create raises TenantContextError (HTTP 500).
    response = _client(app, None).post("/api/v1/docs/", json={"title": "orphan"})
    assert response.status_code == 500
    assert response.json()["code"] == "tenant_context_missing"
