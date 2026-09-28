"""Module code asks who is calling through one dependency (ADR 0162).

A ``Principal`` is enough for the guard and nothing a person would recognise. ``CallerDep``
names the caller the way the platform addresses a subject — a user's email, a service
account's name — from the live row, through a composed app so the guard, the principal seam
and the request's session are the real ones.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import Field
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from terp.core import (
    BaseSchema,
    ModuleSpec,
    Policy,
    Principal,
    Roles,
    create_app,
    get_session,
    route_policy,
)

from terp.capabilities.identity import CallerDep
from terp.capabilities.identity.models import ServiceAccount, User


class Named(BaseSchema):
    id: uuid.UUID
    name: str = Field(max_length=320)


_SHARED_ID = uuid.uuid4()
"""One id held by a user AND a service account, so the table a lookup reads is visible."""

_DEACTIVATED_USER, _DEACTIVATED_ACCOUNT, _EXPIRED_ACCOUNT = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _account(account_id: uuid.UUID, name: str, **fields: object) -> ServiceAccount:
    return ServiceAccount(
        id=account_id,
        name=name,
        client_id=f"client-{name}",
        hashed_secret="x" * 60,  # never verified here
        role=int(Roles.EDITOR),
        **fields,
    )


@pytest.fixture
def engine() -> Iterator[object]:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(id=_SHARED_ID, email="ops@example.test", role=int(Roles.EDITOR)))
        session.add(_account(_SHARED_ID, "nightly-sync"))
        session.add(
            User(id=_DEACTIVATED_USER, email="gone@example.test", role=int(Roles.EDITOR), is_active=False)
        )
        session.add(_account(_DEACTIVATED_ACCOUNT, "retired-sync", is_active=False))
        # Naive, as SQLite hands it back: the expiry rule has to normalise it to compare.
        session.add(
            _account(
                _EXPIRED_ACCOUNT,
                "lapsed-sync",
                expires_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
                - datetime.timedelta(minutes=1),
            )
        )
        session.commit()
    yield engine
    engine.dispose()


def _client(engine: object, principal: Principal | None) -> TestClient:
    router = APIRouter()

    @router.get("/", response_model=Named)
    def who(caller: CallerDep) -> Named:
        return Named(id=caller.id, name=caller.name)

    @router.get("/open", response_model=Named)
    @route_policy(Policy.public(reason="a test route reached without a token"))
    def who_openly(caller: CallerDep) -> Named:
        return Named(id=caller.id, name=caller.name)

    def _session() -> Iterator[Session]:
        with Session(engine) as session:  # type: ignore[arg-type]
            yield session

    app = create_app(
        [ModuleSpec(name="who", router=router, policy=Policy.default())],
        principal_provider=lambda: principal,
    )
    app.dependency_overrides[get_session] = _session
    return TestClient(app, raise_server_exceptions=False)


def test_a_user_is_named_by_email(engine: object) -> None:
    principal = Principal(id=_SHARED_ID, role=Roles.VIEWER)
    response = _client(engine, principal).get("/api/v1/who/")
    assert response.status_code == 200, response.text
    assert response.json() == {"id": str(_SHARED_ID), "name": "ops@example.test"}


def test_a_service_account_is_named_by_its_own_name_not_a_users(engine: object) -> None:
    """The kind decides the table: the same id belongs to a user, and must not be read as one."""
    principal = Principal(id=_SHARED_ID, role=Roles.VIEWER, kind="service")
    response = _client(engine, principal).get("/api/v1/who/")
    assert response.status_code == 200, response.text
    assert response.json() == {"id": str(_SHARED_ID), "name": "nightly-sync"}


@pytest.mark.parametrize("kind", ["user", "service"])
def test_a_subject_whose_row_is_gone_is_unauthenticated(engine: object, kind: str) -> None:
    """A token for a removed subject is refused, not named by an id nobody can read."""
    principal = Principal(id=uuid.uuid4(), role=Roles.VIEWER, kind=kind)
    response = _client(engine, principal).get("/api/v1/who/")
    assert response.status_code == 401, response.text


@pytest.mark.parametrize(
    ("subject", "kind"),
    [
        (_DEACTIVATED_USER, "user"),
        (_DEACTIVATED_ACCOUNT, "service"),
        (_EXPIRED_ACCOUNT, "service"),
    ],
    ids=["deactivated user", "deactivated service account", "expired service account"],
)
def test_an_account_that_can_no_longer_act_is_unauthenticated(
    engine: object, subject: uuid.UUID, kind: str
) -> None:
    """A provider that does not check the store lets its token through; the name is not given."""
    principal = Principal(id=subject, role=Roles.VIEWER, kind=kind)
    response = _client(engine, principal).get("/api/v1/who/")
    assert response.status_code == 401, response.text


def test_a_public_route_without_a_principal_is_unauthenticated(engine: object) -> None:
    """The guard admits anyone to a public route; asking for the caller there still refuses."""
    response = _client(engine, None).get("/api/v1/who/open")
    assert response.status_code == 401, response.text
