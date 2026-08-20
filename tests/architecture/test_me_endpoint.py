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
from terp.core.permissions import (
    project_permissions,
    register_permission_projector,
    registered_permission_projectors,
    reset_permission_projectors,
)

from terp.capabilities.auth import CurrentUser, build_me_module, build_me_router
from terp.capabilities.identity import IdentityService
from terp.capabilities.identity.models import User


@pytest.fixture(autouse=True)
def _isolate_permission_projectors() -> Iterator[None]:
    """Snapshot the projector registry, and put it back afterwards.

    Clearing it outright would disarm the access capability's own import-time
    registration for whatever runs next — a capability registration is meant to outlive a
    composed app (see :mod:`terp.core.runtime`), so a test that wipes it does damage it
    cannot see.
    """
    before = registered_permission_projectors()
    yield
    reset_permission_projectors()
    for projector in before:
        register_permission_projector(projector)


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
        # Empty, not absent: this resolver projects nothing, and an app that mounts no
        # grant capability has no named permissions to hold (ADR 0096).
        "permissions": [],
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


def test_current_user_projects_the_callers_named_grants(session: Session) -> None:
    """The gap this closes: rank alone could not tell a UI what the server would refuse.

    A screen whose write needs ``definitions.publish`` had nothing to ask — it hid by rank
    as a proxy and handled the 403 anyway. ``/me`` now carries the same names the guard
    enforces, through a registered projector rather than an import of the grant capability.
    """
    user = User(
        email="granted@example.test",
        hashed_password="not-a-login-fixture",
        role=int(Roles.EDITOR),
        is_active=True,
        token_version=0,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    register_permission_projector(lambda _session, subject: ["b.write", "a.read"])
    try:
        result = IdentityService().current_user(
            session, Principal(id=user.id, role=Roles.EDITOR)
        )
    finally:
        reset_permission_projectors()

    # Sorted and deduplicated, so the payload is stable across requests.
    assert result.permissions == ("a.read", "b.write")


def test_permissions_from_several_projectors_are_unioned(session: Session) -> None:
    subject = uuid.uuid4()
    register_permission_projector(lambda _session, _subject: ["grants.one"])
    register_permission_projector(lambda _session, _subject: ["licence.two", "grants.one"])
    try:
        assert project_permissions(session, subject) == ("grants.one", "licence.two")
    finally:
        reset_permission_projectors()


def test_an_app_with_no_projector_reports_no_permissions(session: Session) -> None:
    # The honest answer for an app that mounts no grant capability: it has no named
    # permissions, so there is nothing for a UI to gate on beyond role rank.
    reset_permission_projectors()
    assert project_permissions(session, uuid.uuid4()) == ()
