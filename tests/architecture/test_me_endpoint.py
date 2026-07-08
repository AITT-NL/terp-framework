"""Unit/branch coverage for the who-am-I (`/me`) endpoint (ADR 0044).

The example end-to-end slice (`apps/example/tests/test_auth_api.py`) proves the wired,
authenticated happy path. These framework-level tests cover the branches that slice does
not reach: the router's own unauthenticated guard (mounted bare, so the deny-by-default
*module* guard is not in front of it), the module builder's shape, and the identity
resolver's missing-subject path.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from terp.core import (
    AuthenticationError,
    Principal,
    Roles,
    get_principal,
    get_session,
)
from terp.core.app import register_error_handlers

from terp.capabilities.auth import CurrentUser, build_me_module, build_me_router
from terp.capabilities.identity import IdentityService
from terp.capabilities.identity.models import User


def _resolver(_session: object, principal: Principal) -> CurrentUser:
    """A store-free stand-in for the wired resolver (echoes the principal)."""
    return CurrentUser(
        id=principal.id,
        email="caller@example.test",
        role_rank=principal.role.rank,
        role_name=principal.role.name,
    )


def _bare_app() -> FastAPI:
    """The `/me` router mounted with no deny-by-default module guard in front of it."""
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(build_me_router(_resolver), prefix="/me")
    # The handler takes a SessionDep that the store-free resolver ignores; override the
    # session seam so the unit test needs no database.
    app.dependency_overrides[get_session] = lambda: None
    return app


def test_me_router_returns_the_resolved_caller() -> None:
    app = _bare_app()
    principal = Principal(id=uuid.uuid4(), role=Roles.EDITOR)
    app.dependency_overrides[get_principal] = lambda: principal

    body = TestClient(app).get("/me/").json()

    assert body == {
        "id": str(principal.id),
        "email": "caller@example.test",
        "role_rank": 20,
        "role_name": "editor",
    }


def test_me_router_rejects_an_anonymous_caller() -> None:
    # No principal override: the default get_principal seam yields None, so the route's
    # own check answers with a clean 401 envelope (never an AttributeError).
    response = TestClient(_bare_app()).get("/me/")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_build_me_module_is_named_and_authenticated() -> None:
    module = build_me_module(_resolver)

    assert module.name == "me"
    assert module.router is not None
    assert module.policy is not None
    assert not module.policy.is_public
    assert module.policy.read_requirement.min_rank == int(Roles.VIEWER)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as open_session:
            yield open_session
    finally:
        SQLModel.metadata.drop_all(engine)
        engine.dispose()


def test_current_user_reports_the_live_stored_identity(session: Session) -> None:
    user = User(
        email="stored@example.test",
        hashed_password="not-a-login-fixture",
        role=int(Roles.ADMIN),
        is_active=True,
        token_version=0,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    # The token principal claims VIEWER, but `/me` resolves the role from the STORE, so it
    # reports the live ADMIN — proof the response is the live record, not token claims.
    result = IdentityService().current_user(
        session, Principal(id=user.id, role=Roles.VIEWER)
    )

    assert result == CurrentUser(
        id=user.id,
        email="stored@example.test",
        role_rank=int(Roles.ADMIN),
        role_name="admin",
    )


def test_current_user_rejects_a_vanished_subject(session: Session) -> None:
    with pytest.raises(AuthenticationError):
        IdentityService().current_user(
            session, Principal(id=uuid.uuid4(), role=Roles.VIEWER)
        )
