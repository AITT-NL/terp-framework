"""Fixtures for the example-app end-to-end slice.

Exercises the real composition over an in-memory SQLite database: it overrides
the ``terp.core.db.get_session`` seam and authenticates by minting real JWT
access tokens via the auth capability.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from terp.core import Principal, Roles, get_session, settings
from terp.core._internal.session_guard import WriteGuardedSession

from terp.capabilities.auth import create_access_token

from app import auth as app_auth
from app.auth import login_throttle
from app.main import build

# Tests sign JWTs; use a realistic-length secret so pyjwt does not warn about a
# short HMAC key (the dev default is intentionally short and production-guarded).
settings.SECRET_KEY = "terp-example-test-secret-key-0123456789abcdef"


@pytest.fixture(autouse=True)
def _reset_login_throttle() -> Iterator[None]:
    """Clear the process-global login-throttle counters between e2e cases.

    ``app.auth.login_throttle`` is a module-level singleton (the login module is), so a
    lockout in one test would otherwise bleed into the next; reset it after each test.
    """
    yield
    login_throttle.reset()


@pytest.fixture
def db_engine() -> Iterator[Engine]:
    """An isolated in-memory engine with every table created."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Register every table on the shared metadata before creating them.
    import app.modules.journals.models  # noqa: F401
    import app.modules.notes.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.tasks.models  # noqa: F401
    import terp.capabilities.access.models  # noqa: F401
    import terp.capabilities.audit.models  # noqa: F401
    import terp.capabilities.files.models  # noqa: F401
    import terp.capabilities.groups.models  # noqa: F401
    import terp.capabilities.identity.models  # noqa: F401
    import terp.capabilities.outbox.models  # noqa: F401
    import terp.capabilities.webhooks.models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    try:
        yield engine
    finally:
        SQLModel.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def app_db(db_engine: Engine) -> Iterator[FastAPI]:
    """A freshly composed app bound to *db_engine*."""
    application = build()

    def _session_override() -> Iterator[Session]:
        with WriteGuardedSession(db_engine) as session:
            yield session

    application.dependency_overrides[get_session] = _session_override
    original_realtime_factory = app_auth.realtime_session_factory
    app_auth.realtime_session_factory = _session_override
    try:
        yield application
    finally:
        app_auth.realtime_session_factory = original_realtime_factory
        application.dependency_overrides.clear()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    with Session(db_engine) as session:
        yield session


@pytest.fixture
def make_user(db_session: Session):
    """Create a persisted user (via the users capability) for a test."""
    from terp.capabilities.users import UserProvision, UsersService

    service = UsersService()

    def _make(email: str, password: str, role: Roles = Roles.EDITOR) -> uuid.UUID:
        user = service.create(
            db_session, UserProvision(email=email, password=password, role=role)
        )
        return user.id

    return _make


def _ensure_backing_user(
    session: Session, subject: uuid.UUID, *, store_role: Roles = Roles.VIEWER
) -> None:
    """Persist a minimal active user for *subject* so the revocable provider accepts it.

    The shipped app uses the revocable ``get_principal`` (ADR 0031): every request
    re-checks that the bearer's subject is a real, active user at the current token
    epoch. A synthetic principal therefore needs a backing row. It is stored as a **low
    role** by default so the acting principal never perturbs the last-admin invariant the
    ``users`` tests exercise — authorization comes from the *token* rank, the admin count
    from the *stored* role, and the two are deliberately independent in Terp.
    """
    from terp.capabilities.identity.models import User

    if session.get(User, subject) is not None:
        return
    session.add(
        User(
            id=subject,
            email=f"principal-{subject}@backing.test",
            hashed_password="not-a-login-fixture",
            role=int(store_role),
            is_active=True,
            token_version=0,
        )
    )
    session.commit()


@pytest.fixture
def editor() -> Principal:
    return Principal(id=uuid.uuid4(), role=Roles.EDITOR)


@pytest.fixture
def viewer() -> Principal:
    return Principal(id=uuid.uuid4(), role=Roles.VIEWER)


@pytest.fixture
def client_factory(app_db: FastAPI, db_session: Session):
    """Return a builder for a TestClient authenticated as *principal* (or None).

    A persisted, active user backs each principal so the revocable provider (ADR 0031)
    accepts the minted token (it re-checks the subject exists, is active, and the token
    epoch matches).
    """

    def _make(principal: Principal | None) -> TestClient:
        client = TestClient(app_db)
        if principal is not None:
            _ensure_backing_user(db_session, principal.id)
            token = create_access_token(subject=principal.id, role=principal.role)
            client.headers["Authorization"] = f"Bearer {token}"
        return client

    return _make


@pytest.fixture
def token_client(app_db: FastAPI, db_session: Session):
    """Build a TestClient whose bearer carries a given role / tenant / token epoch.

    The general companion to ``client_factory`` for suites that need a tenant claim, a
    specific subject, or a specific token epoch. By default it backs the subject with a
    real active user (so the revocable provider accepts it); pass ``back_user=False`` for
    a subject that is already persisted, or to test an *unbacked* subject (rejected).
    """

    def _make(
        *,
        role: Roles = Roles.EDITOR,
        subject: uuid.UUID | None = None,
        tenant: uuid.UUID | None = None,
        token_version: int = 0,
        back_user: bool = True,
    ) -> TestClient:
        subject = subject if subject is not None else uuid.uuid4()
        if back_user:
            _ensure_backing_user(db_session, subject)
        token = create_access_token(
            subject=subject, role=role, tenant=tenant, token_version=token_version
        )
        client = TestClient(app_db)
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    return _make
