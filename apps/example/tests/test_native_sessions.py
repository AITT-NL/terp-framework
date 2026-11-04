"""A native session keeps what ADR 0193 holds for the cookie carrier (ADR 0195).

The body carrier rotates in the same refresh families as the cookie, so it is held to the
same sequence guarantees as ``test_authentication_snapshots.py`` holds the cookie to: a
refresh is refused when the family's epoch no longer matches the subject's, when a custom
store returns no epoch, or when the identity is gone after the rotation; and signing out with
the refresh token alone revokes its whole family server-side, without minting a successor and
without touching another family.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from terp.capabilities.auth import AUTH_OPERATIONS, NativeClients, build_login_module, refresh_token_digest
from terp.capabilities.identity import IdentityService, RefreshToken, RefreshTokenService
from terp.capabilities.users import UsersService
from terp.core import ControlPlane, OperationCatalog, create_app, get_session
from terp.core._internal.session_guard import WriteGuardedSession

_PASSWORD = "correct horse battery"
_LOGIN = "/api/v1/auth/native/login"
_REFRESH = "/api/v1/auth/native/refresh"
_LOGOUT = "/api/v1/auth/native/logout"


def _client(engine, identity, refresh, *, rotator=None) -> TestClient:
    """The login module with native clients over real identity and refresh stores."""
    login = build_login_module(
        identity.authenticate,
        token_version_resolver=identity.token_version_for,
        refresh_issuer=refresh.issue,
        refresh_rotator=rotator or refresh.rotate,
        refresh_revoker=refresh.revoke_presented,
        principal_resolver=identity.principal_for_id,
        revoke_sessions=UsersService(refresh.revoke_all_for_user).revoke_sessions,
        native_clients=NativeClients(reason="a mobile app keeps its refresh token in the keychain"),
    )
    application = create_app(
        [login],
        principal_provider=identity.principal_provider(),
        require_token_revocation=True,
        control_plane=ControlPlane(operations=OperationCatalog(operations=AUTH_OPERATIONS)),
    )

    def sessions():
        with WriteGuardedSession(engine) as session:
            yield session

    application.dependency_overrides[get_session] = sessions
    return TestClient(application)


def _sign_in(client: TestClient, email: str) -> str:
    response = client.post(_LOGIN, json={"email": email, "password": _PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["refresh_token"]


# --- the authenticated snapshot ---------------------------------------------- #
def test_a_revocation_between_rotation_and_resolution_refuses_the_native_refresh(db_engine, make_user) -> None:
    user_id = make_user("native-rotation@example.test", _PASSWORD)
    identity, refresh = IdentityService(), RefreshTokenService()

    def rotate(session, raw):
        result = refresh.rotate(session, raw)
        assert result is not None and result.token_version == 0
        with Session(db_engine) as admin_session:
            UsersService(refresh.revoke_all_for_user).revoke_sessions(admin_session, user_id)
        return result

    client = _client(db_engine, identity, refresh, rotator=rotate)
    token = _sign_in(client, "native-rotation@example.test")
    refused = client.post(_REFRESH, json={"refresh_token": token})
    assert refused.status_code == 401
    assert "access_token" not in refused.json(), "no access token is minted"


def test_a_store_that_omits_the_epoch_refuses_the_native_refresh(db_engine, make_user) -> None:
    make_user("native-missing-epoch@example.test", _PASSWORD)
    identity, refresh = IdentityService(), RefreshTokenService()
    client = _client(
        db_engine, identity, refresh, rotator=lambda session, raw: replace(refresh.rotate(session, raw), token_version=None)
    )
    token = _sign_in(client, "native-missing-epoch@example.test")
    assert client.post(_REFRESH, json={"refresh_token": token}).status_code == 401


def test_an_identity_gone_after_rotation_refuses_the_native_refresh(db_engine, make_user, monkeypatch) -> None:
    make_user("native-missing-principal@example.test", _PASSWORD)
    identity, refresh = IdentityService(), RefreshTokenService()
    # The module captures the resolver when it is built, so it is replaced first; sign-in
    # does not use it, and the refresh finds no principal behind a rotation that succeeded.
    monkeypatch.setattr(identity, "principal_for_id", lambda session, subject: None)
    client = _client(db_engine, identity, refresh)
    token = _sign_in(client, "native-missing-principal@example.test")
    assert client.post(_REFRESH, json={"refresh_token": token}).status_code == 401


def test_an_unchanged_native_session_still_refreshes(db_engine, make_user) -> None:
    """The control for the three refusals above: nothing changed, and the refresh works."""
    make_user("native-control@example.test", _PASSWORD)
    client = _client(db_engine, IdentityService(), RefreshTokenService())
    token = _sign_in(client, "native-control@example.test")
    refreshed = client.post(_REFRESH, json={"refresh_token": token})
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["refresh_token"] != token


# --- signing out with the refresh token alone -------------------------------- #
@pytest.mark.parametrize("state", ["current", "spent", "expired"])
def test_native_logout_revokes_its_family_without_issuing_or_revoking_others(
    app_db: FastAPI, make_user, db_session: Session, state: str
) -> None:
    make_user("native-logout@example.test", _PASSWORD)
    make_user("native-unrelated@example.test", _PASSWORD)
    phone = TestClient(app_db)
    raw = _sign_in(phone, "native-logout@example.test")
    successor = raw
    if state != "current":
        refreshed = phone.post(_REFRESH, json={"refresh_token": raw})
        assert refreshed.status_code == 200
        successor = refreshed.json()["refresh_token"]
    if state == "expired":
        row = db_session.exec(select(RefreshToken).where(RefreshToken.token_hash == refresh_token_digest(raw))).one()
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db_session.add(row)
        db_session.commit()

    second_device = _sign_in(TestClient(app_db), "native-logout@example.test")
    other_user = _sign_in(TestClient(app_db), "native-unrelated@example.test")
    rows_before = len(db_session.exec(select(RefreshToken)).all())

    # No bearer: the refresh token is the only credential the client presents.
    response = TestClient(app_db).post(_LOGOUT, json={"refresh_token": raw})
    assert response.status_code == 204
    assert "set-cookie" not in response.headers
    assert len(db_session.exec(select(RefreshToken)).all()) == rows_before, "signing out mints nothing"
    for credential in {raw, successor}:
        assert TestClient(app_db).post(_REFRESH, json={"refresh_token": credential}).status_code == 401
    # Controls: another device of the same person, and another person, keep their sessions.
    assert TestClient(app_db).post(_REFRESH, json={"refresh_token": second_device}).status_code == 200
    assert TestClient(app_db).post(_REFRESH, json={"refresh_token": other_user}).status_code == 200
    assert TestClient(app_db).post(_LOGOUT, json={"refresh_token": raw}).status_code == 204, "idempotent"


def test_native_logout_with_an_unknown_token_is_a_no_op(app_db: FastAPI) -> None:
    assert TestClient(app_db).post(_LOGOUT, json={"refresh_token": "not-a-real-refresh-token"}).status_code == 204


def test_native_logout_refuses_a_browser_and_leaves_the_session_live(app_db: FastAPI, make_user) -> None:
    make_user("native-logout-tab@example.test", _PASSWORD)
    token = _sign_in(TestClient(app_db), "native-logout-tab@example.test")
    refused = TestClient(app_db).post(
        _LOGOUT, json={"refresh_token": token}, headers={"Origin": "https://app.example.test"}
    )
    assert refused.status_code == 403 and refused.json()["code"] == "native_client_only"
    assert TestClient(app_db).post(_REFRESH, json={"refresh_token": token}).status_code == 200
