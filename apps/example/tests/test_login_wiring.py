"""H7: the bundled identity/login is role-model-agnostic and can sign a tenant claim.

``IdentityService.authenticate`` resolves a user's stored rank through the app's
``PermissionModel`` (not the fixed 3-tier ``Roles`` enum), so a consumer-defined
role authenticates instead of 500ing; and ``build_login_module`` accepts a
``tenant_resolver`` so a multi-tenant app's login signs the ``tenant`` claim through
the same sanctioned seam ``TenantMiddleware`` reads (ADR 0022).
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

from terp.capabilities.auth import build_login_module, decode_access_token, hash_password
from terp.capabilities.identity import IdentityService, User
from terp.core import PermissionModel, Principal, Role, create_app, get_session

_VIEWER = Role("viewer", rank=10)
_EDITOR = Role("editor", rank=20)
_LEAD = Role("lead", rank=25)  # a consumer-defined tier outside the default ladder
_ADMIN = Role("admin", rank=30)


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


def _make_user(session: Session, *, email: str, password: str, rank: int) -> uuid.UUID:
    user = User(email=email, hashed_password=hash_password(password), role=rank)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user.id


# --- H7a: the role is resolved through the PermissionModel ------------------- #
def test_authenticate_resolves_a_custom_rank_via_the_permission_model(engine: Engine) -> None:
    model = PermissionModel(roles=(_VIEWER, _EDITOR, _LEAD, _ADMIN))
    with Session(engine) as session:
        _make_user(session, email="lead@example.com", password="pw", rank=25)
        principal = IdentityService(model).authenticate(session, "lead@example.com", "pw")
    assert principal is not None
    assert principal.role == _LEAD  # name "lead", rank 25 — not coerced to a fixed tier


def test_default_model_fails_closed_on_a_rank_it_does_not_define(engine: Engine) -> None:
    with Session(engine) as session:
        _make_user(session, email="lead@example.com", password="pw", rank=25)
        # The default 3-tier model has no rank 25 → no token is minted for an unmodeled role.
        with pytest.raises(ValueError):
            IdentityService().authenticate(session, "lead@example.com", "pw")


def test_authenticate_still_rejects_a_bad_password(engine: Engine) -> None:
    with Session(engine) as session:
        _make_user(session, email="e@example.com", password="right", rank=20)
        assert IdentityService().authenticate(session, "e@example.com", "wrong") is None


# --- H7b: login signs the resolved tenant ------------------------------------ #
def _login_app(engine: Engine, *, subject: uuid.UUID, tenant_resolver=None) -> FastAPI:
    def _authenticate(session: Session, email: str, password: str) -> Principal | None:
        return Principal(id=subject, role=_EDITOR) if password == "ok" else None

    app = create_app([build_login_module(_authenticate, tenant_resolver=tenant_resolver)])

    def _session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session_override
    return app


def test_login_signs_the_resolved_tenant(engine: Engine) -> None:
    subject, tenant = uuid.uuid4(), uuid.uuid4()
    app = _login_app(engine, subject=subject, tenant_resolver=lambda session, principal: tenant)
    response = TestClient(app).post(
        "/api/v1/auth/login", json={"email": "x@example.com", "password": "ok"}
    )
    claims = decode_access_token(response.json()["access_token"])
    assert claims.subject == subject
    assert claims.tenant == tenant


def test_login_without_a_resolver_signs_no_tenant(engine: Engine) -> None:
    app = _login_app(engine, subject=uuid.uuid4())
    response = TestClient(app).post(
        "/api/v1/auth/login", json={"email": "x@example.com", "password": "ok"}
    )
    assert decode_access_token(response.json()["access_token"]).tenant is None


# --- ADR 0054: refresh-token wiring is all-or-nothing (fail-closed) ---------- #
def _authenticate_stub(session: Session, email: str, password: str) -> Principal | None:
    return None


def test_half_wired_refresh_seams_raise_at_construction() -> None:
    # Only one of the three refresh seams supplied — a token issued at login that nothing can
    # rotate — is a fail-closed misconfiguration caught at construction, not in production.
    with pytest.raises(ValueError, match="half-wired"):
        build_login_module(_authenticate_stub, refresh_issuer=lambda session, user_id: "t")


def test_require_refresh_without_the_seams_raises() -> None:
    with pytest.raises(ValueError, match="require_refresh"):
        build_login_module(_authenticate_stub, require_refresh=True)


def _full_refresh_seams() -> dict:
    return {
        "refresh_issuer": lambda session, user_id: "t",
        "refresh_rotator": lambda session, raw: None,
        "principal_resolver": lambda session, user_id: None,
    }


def test_refresh_seams_without_revoke_sessions_raise_at_construction() -> None:
    # Without a server-side revoker, /logout would only drop the cookie while the refresh
    # family stayed live in the store — a logout that does not log out. Fail closed.
    with pytest.raises(ValueError, match="revoke_sessions"):
        build_login_module(_authenticate_stub, **_full_refresh_seams())


def test_refresh_cookie_path_must_match_the_module_mount_prefix() -> None:
    # A path-scoped cookie the browser never sends to /refresh would make refresh silently
    # never work: a module name that diverges from REFRESH_COOKIE_PATH is refused.
    with pytest.raises(ValueError, match="REFRESH_COOKIE_PATH"):
        build_login_module(
            _authenticate_stub,
            name="sso",
            revoke_sessions=lambda session, user_id: None,
            **_full_refresh_seams(),
        )
