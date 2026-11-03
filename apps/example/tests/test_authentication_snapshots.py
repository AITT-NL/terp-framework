"""Authentication transitions preserve the authority that was actually verified."""
from __future__ import annotations

import uuid
from contextvars import Context
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from terp.capabilities.auth import (
    AUTH_OPERATIONS, AuthenticatedPrincipal, build_login_module, decode_access_token,
    refresh_token_digest, resolve_token_version,
)
from terp.capabilities.identity import IdentityService, RefreshToken, RefreshTokenService, User
from terp.capabilities.users import UserAdminUpdate, UsersService
from terp.core import (
    AuthenticationError, ControlPlane, ModuleSpec, OperationCatalog, Policy, Principal,
    Roles, create_app, get_session,
)
from terp.core._internal.session_guard import WriteGuardedSession

_PASSWORD = "correct horse battery"
_COOKIE = "terp_refresh"


def _client(engine, identity, refresh, *, authenticate=None, issuer=None, rotator=None):
    login = build_login_module(
        authenticate or identity.authenticate,
        token_version_resolver=identity.token_version_for,
        refresh_issuer=issuer or refresh.issue,
        refresh_rotator=rotator or refresh.rotate,
        refresh_revoker=refresh.revoke_presented,
        principal_resolver=identity.principal_for_id,
        revoke_sessions=UsersService(refresh.revoke_all_for_user).revoke_sessions,
    )
    router = APIRouter()

    @router.get("/check", response_model=dict)
    def administrative_data():
        return {"administrative": True}

    application = create_app(
        [login, ModuleSpec(name="admin_probe", router=router,
                           policy=Policy(read=Roles.ADMIN, write=Roles.ADMIN))],
        principal_provider=identity.principal_provider(), require_token_revocation=True,
        control_plane=ControlPlane(operations=OperationCatalog(operations=AUTH_OPERATIONS)),
    )

    def sessions():
        with WriteGuardedSession(engine) as session:
            yield session

    application.dependency_overrides[get_session] = sessions
    return TestClient(application)


@pytest.mark.parametrize("change", ["demotion", "password_reset"])
def test_security_change_between_authentication_and_mint_refuses_login(db_engine, make_user, change):
    make_user("other-admin@example.test", _PASSWORD, Roles.ADMIN)
    user_id = make_user("changing@example.test", _PASSWORD, Roles.ADMIN)
    identity, refresh = IdentityService(), RefreshTokenService()

    def authenticate(session, email, password):
        principal = identity.authenticate(session, email, password)
        assert isinstance(principal, AuthenticatedPrincipal)
        with Session(db_engine) as admin_session:
            service = UsersService(refresh.revoke_all_for_user)
            if change == "demotion":
                row = admin_session.get(User, user_id)
                service.update(admin_session, user_id, UserAdminUpdate(
                    version=row.version, role=int(Roles.VIEWER)))
            else:
                service.reset_password(admin_session, user_id, "replacement correct passphrase")
        return principal

    response = _client(db_engine, identity, refresh, authenticate=authenticate).post(
        "/api/v1/auth/login", json={"email": "changing@example.test", "password": _PASSWORD})
    assert response.status_code == 401
    assert _COOKIE not in response.cookies
    with Session(db_engine) as session:
        assert session.exec(select(RefreshToken)).all() == []


def test_revocation_before_refresh_family_issue_refuses_stale_authentication(db_engine, make_user):
    user_id = make_user("family@example.test", _PASSWORD)
    identity, refresh = IdentityService(), RefreshTokenService()

    def issue(session, subject, *, token_version):
        with Session(db_engine) as admin_session:
            UsersService(refresh.revoke_all_for_user).revoke_sessions(admin_session, user_id)
        return refresh.issue(session, subject, token_version=token_version)

    response = _client(db_engine, identity, refresh, issuer=issue).post(
        "/api/v1/auth/login", json={"email": "family@example.test", "password": _PASSWORD})
    assert response.status_code == 401
    assert _COOKIE not in response.cookies


def test_family_created_after_epoch_check_cannot_reopen_revoked_session(
    db_engine, make_user, monkeypatch
):
    user_id = make_user("late-family@example.test", _PASSWORD, Roles.ADMIN)
    identity, refresh = IdentityService(), RefreshTokenService()
    original = refresh._epoch_is_current

    def change_after_check(session, subject, token_version):
        result = original(session, subject, token_version)
        def revoke_in_another_operation():
            with Session(db_engine) as admin_session:
                UsersService(refresh.revoke_all_for_user).revoke_sessions(admin_session, user_id)
                assert admin_session.get(User, user_id).token_version == 1
        # Another request does not inherit this refresh issue's write-unit context.
        Context().run(revoke_in_another_operation)
        return result

    monkeypatch.setattr(refresh, "_epoch_is_current", change_after_check)
    client = _client(db_engine, identity, refresh)
    response = client.post("/api/v1/auth/login", json={
        "email": "late-family@example.test", "password": _PASSWORD})
    assert response.status_code == 200
    token = response.json()["access_token"]
    assert decode_access_token(token).token_version == 0
    assert client.get("/api/v1/admin_probe/check", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    monkeypatch.setattr(refresh, "_epoch_is_current", original)
    assert client.post("/api/v1/auth/refresh").status_code == 401


@pytest.mark.parametrize("legacy", [False, True])
def test_revocation_between_rotation_and_principal_resolution_refuses_refresh(db_engine, make_user, legacy):
    user_id = make_user("rotation@example.test", _PASSWORD)
    identity, refresh = IdentityService(), RefreshTokenService()

    def rotate(session, raw):
        result = refresh.rotate(session, raw)
        assert result.token_version == 0
        with Session(db_engine) as admin_session:
            UsersService(refresh.revoke_all_for_user).revoke_sessions(admin_session, user_id)
        return result

    client = _client(db_engine, identity, refresh, rotator=rotate)
    assert client.post("/api/v1/auth/login", json={
        "email": "rotation@example.test", "password": _PASSWORD}).status_code == 200
    if legacy:
        with Session(db_engine) as session:
            row = session.exec(select(RefreshToken)).one()
            row.token_version = None  # A family that predates the additive migration.
            session.add(row)
            session.commit()
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_refresh_refuses_a_custom_store_that_omits_the_authenticated_epoch(db_engine, make_user):
    from dataclasses import replace

    make_user("missing-epoch@example.test", _PASSWORD)
    identity, refresh = IdentityService(), RefreshTokenService()
    def rotate(session, raw):
        return replace(refresh.rotate(session, raw), token_version=None)
    client = _client(db_engine, identity, refresh, rotator=rotate)
    assert client.post("/api/v1/auth/login", json={
        "email": "missing-epoch@example.test", "password": _PASSWORD}).status_code == 200
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_legacy_family_for_a_missing_subject_cannot_rotate(db_session):
    refresh = RefreshTokenService()
    raw = refresh.issue(db_session, uuid.uuid4())
    assert refresh.rotate(db_session, raw) is None


def test_identity_disappearing_after_rotation_is_refused(db_engine, make_user, monkeypatch):
    make_user("missing-principal@example.test", _PASSWORD)
    identity, refresh = IdentityService(), RefreshTokenService()
    monkeypatch.setattr(identity, "principal_for_id", lambda session, subject: None)
    client = _client(db_engine, identity, refresh)
    assert client.post("/api/v1/auth/login", json={
        "email": "missing-principal@example.test", "password": _PASSWORD}).status_code == 200
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_a_late_successor_cannot_outlive_a_revoked_family(db_session, make_user):
    user_id = make_user("late-successor@example.test", _PASSWORD)
    refresh = RefreshTokenService()
    raw = refresh.issue(db_session, user_id, token_version=0)
    ancestor = db_session.exec(select(RefreshToken).where(
        RefreshToken.token_hash == refresh_token_digest(raw))).one()
    family_id, expires = ancestor.family_id, ancestor.family_expires_at.replace(tzinfo=UTC)
    refresh.revoke_presented(db_session, raw)
    # Residue of a concurrent rotation whose INSERT completed after logout's SELECT:
    # exercise the same mint helper with the captured family and epoch, then commit.
    late = refresh._mint(db_session, user_id, family_id, expires, datetime.now(UTC), 0)
    db_session.commit()
    inserted = db_session.exec(select(RefreshToken).where(
        RefreshToken.token_hash == refresh_token_digest(late))).one()
    assert inserted.revoked_at is None
    assert refresh.rotate(db_session, late) is None
    db_session.refresh(inserted)
    assert inserted.revoked_at is not None


def test_logout_with_an_unknown_cookie_is_idempotent(app_db):
    client = TestClient(app_db)
    client.cookies.set(_COOKIE, "unknown-session")
    assert client.post("/api/v1/auth/logout").status_code == 204


@pytest.mark.parametrize("state", ["current", "spent", "expired"])
def test_cookie_only_logout_revokes_its_family_without_issuing_or_revoking_others(
    app_db, make_user, db_session, state
):
    make_user("logout-family@example.test", _PASSWORD)
    make_user("unrelated@example.test", _PASSWORD)

    def login(email):
        client = TestClient(app_db)
        response = client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
        assert response.status_code == 200
        return client

    browser = login("logout-family@example.test")
    raw = browser.cookies[_COOKIE]
    if state != "current":
        assert browser.post("/api/v1/auth/refresh").status_code == 200
    successor = browser.cookies[_COOKIE]
    if state == "expired":
        row = db_session.exec(select(RefreshToken).where(
            RefreshToken.token_hash == refresh_token_digest(raw))).one()
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db_session.add(row)
        db_session.commit()

    separate_family = login("logout-family@example.test")
    other_user = login("unrelated@example.test")
    rows_before = len(db_session.exec(select(RefreshToken)).all())
    logout = TestClient(app_db)
    logout.cookies.set(_COOKIE, raw)
    response = logout.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert len(db_session.exec(select(RefreshToken)).all()) == rows_before
    for credential in {raw, successor}:
        replay = TestClient(app_db)
        replay.cookies.set(_COOKIE, credential)
        assert replay.post("/api/v1/auth/refresh").status_code == 401
    assert separate_family.post("/api/v1/auth/refresh").status_code == 200
    assert other_user.post("/api/v1/auth/refresh").status_code == 200
    assert logout.post("/api/v1/auth/logout").status_code == 204


def test_snapshot_contract_refuses_missing_or_invalid_epochs(db_session):
    principal = Principal(id=uuid.uuid4(), role=Roles.EDITOR)
    assert resolve_token_version(db_session, principal, None) == 0
    with pytest.raises(AuthenticationError):
        resolve_token_version(db_session, principal, lambda session, caller: 4)
    with pytest.raises(AuthenticationError):
        IdentityService().token_version_for(db_session, principal)
    for invalid in (-1, True, "1"):
        with pytest.raises(ValueError, match="non-negative integer"):
            AuthenticatedPrincipal(id=principal.id, role=principal.role, token_version=invalid)
    snapshot = AuthenticatedPrincipal(id=principal.id, role=principal.role, token_version=4)
    assert resolve_token_version(db_session, snapshot, None) == 4
    with pytest.raises(AuthenticationError):
        IdentityService().token_version_for(db_session, snapshot)
