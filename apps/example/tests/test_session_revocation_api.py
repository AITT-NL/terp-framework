"""End-to-end (ADR 0031): a token dies mid-session, and bad logins lock the account.

Drives the *shipped* example composition (``main.build()`` wires the revocable
``principal_provider`` + ``require_token_revocation=True`` + the login throttle), so it
proves the whole path over real HTTP: a still-unexpired token stops working the moment
its user is deactivated, demoted, password-reset, or logged out, and repeated failed
logins lock the account fail-closed.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from terp.capabilities.identity import User
from terp.capabilities.users import UserAdminUpdate, UsersService
from terp.core import Roles


def _login(app_db: FastAPI, email: str, password: str) -> TestClient:
    client = TestClient(app_db)
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return client


def test_a_token_keeps_working_until_a_revoking_change(app_db: FastAPI, make_user) -> None:
    make_user("steady@example.com", "correct horse battery", Roles.EDITOR)
    client = _login(app_db, "steady@example.com", "correct horse battery")
    # The per-request revocation check is satisfied, so a normal session just works.
    assert client.get("/api/v1/notes/").status_code == 200
    assert client.get("/api/v1/notes/").status_code == 200


def test_deactivation_kills_the_token_mid_session(app_db: FastAPI, make_user, db_session) -> None:
    uid = make_user("victim@example.com", "correct horse battery", Roles.EDITOR)
    client = _login(app_db, "victim@example.com", "correct horse battery")
    assert client.get("/api/v1/notes/").status_code == 200

    UsersService().set_active(db_session, uid, active=False)

    # The mid-session is_active re-check rejects the still-unexpired token at once.
    assert client.get("/api/v1/notes/").status_code == 401


def test_role_change_kills_the_token_mid_session(app_db: FastAPI, make_user, db_session) -> None:
    uid = make_user("demote@example.com", "correct horse battery", Roles.EDITOR)
    client = _login(app_db, "demote@example.com", "correct horse battery")
    assert client.post("/api/v1/notes/", json={"title": "before"}).status_code == 201

    user = db_session.get(User, uid)
    UsersService().update(
        db_session, uid, UserAdminUpdate(role=int(Roles.VIEWER), version=user.version)
    )

    # The epoch moved, so the old editor token no longer authenticates (re-login required).
    assert client.get("/api/v1/notes/").status_code == 401


def test_password_reset_kills_the_token_mid_session(app_db: FastAPI, make_user, db_session) -> None:
    uid = make_user("reset@example.com", "correct horse battery old", Roles.EDITOR)
    client = _login(app_db, "reset@example.com", "correct horse battery old")
    assert client.get("/api/v1/notes/").status_code == 200

    UsersService().reset_password(db_session, uid, "correct horse battery new")

    # A session on the old credential cannot survive the reset.
    assert client.get("/api/v1/notes/").status_code == 401


def test_logout_revokes_the_callers_sessions(app_db: FastAPI, make_user) -> None:
    make_user("bye@example.com", "correct horse battery", Roles.EDITOR)
    client = _login(app_db, "bye@example.com", "correct horse battery")
    assert client.get("/api/v1/notes/").status_code == 200

    assert client.post("/api/v1/auth/logout").status_code == 204
    # The token is dead after logout; a re-login is required.
    assert client.get("/api/v1/notes/").status_code == 401
    # Logout is idempotent: an already-revoked token logs out as a no-op 204.
    assert client.post("/api/v1/auth/logout").status_code == 204


def test_relogin_after_a_revoking_change_succeeds(app_db: FastAPI, make_user, db_session) -> None:
    uid = make_user("again@example.com", "correct horse battery", Roles.EDITOR)
    client = _login(app_db, "again@example.com", "correct horse battery")
    UsersService().reset_password(db_session, uid, "correct horse battery two")  # bumps the epoch
    assert client.get("/api/v1/notes/").status_code == 401

    # Logging in again mints a token at the *new* epoch, which is accepted.
    fresh = _login(app_db, "again@example.com", "correct horse battery two")
    assert fresh.get("/api/v1/notes/").status_code == 200


def test_repeated_bad_logins_lock_the_account(app_db: FastAPI, make_user) -> None:
    make_user("target@example.com", "correct horse battery", Roles.EDITOR)
    client = TestClient(app_db)

    for _ in range(5):
        bad = client.post(
            "/api/v1/auth/login",
            json={"email": "target@example.com", "password": "wrong"},
        )
        assert bad.status_code == 401

    # Now locked: even the correct password is refused (fail-closed) with a typed 429.
    locked = client.post(
        "/api/v1/auth/login",
        json={"email": "target@example.com", "password": "correct horse battery"},
    )
    assert locked.status_code == 429
    assert locked.json()["code"] == "account_locked"
