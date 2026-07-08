"""End-to-end (ADR 0054): rotating refresh tokens over the shipped example composition.

Drives ``main.build()`` (which wires the refresh seams + ``require_refresh=True``), so it
proves the whole path over real HTTP: login sets an httpOnly refresh cookie, ``/refresh``
rotates it for a fresh access token, a replayed (spent) token trips reuse-detection and
kills the family, and logout / deactivate / password-reset revoke the refresh tokens too —
so a revoked session cannot refresh its way back in.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from terp.capabilities.identity import RefreshToken, RefreshTokenService
from terp.capabilities.users import UsersService
from terp.core import Roles

_COOKIE = "terp_refresh"


def _login(app_db: FastAPI, email: str, password: str) -> TestClient:
    client = TestClient(app_db)
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return client


# --- login + refresh happy path --------------------------------------------- #
def test_login_sets_an_httponly_refresh_cookie(app_db: FastAPI, make_user) -> None:
    make_user("cookie@example.com", "correct horse battery", Roles.EDITOR)
    client = TestClient(app_db)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "cookie@example.com", "password": "correct horse battery"},
    )
    assert response.status_code == 200
    assert response.cookies.get(_COOKIE)  # the rotating refresh token rides a cookie
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "path=/api/v1/auth" in set_cookie


def test_refresh_rotates_for_a_fresh_access_token(app_db: FastAPI, make_user) -> None:
    make_user("rot@example.com", "correct horse battery", Roles.EDITOR)
    client = _login(app_db, "rot@example.com", "correct horse battery")

    refreshed = client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["token_type"] == "bearer"
    # The new access token authenticates a real request.
    client.headers["Authorization"] = f"Bearer {refreshed.json()['access_token']}"
    assert client.get("/api/v1/notes/").status_code == 200


def test_refresh_without_a_cookie_is_unauthenticated(app_db: FastAPI) -> None:
    assert TestClient(app_db).post("/api/v1/auth/refresh").status_code == 401


def test_refresh_with_an_unknown_cookie_is_unauthenticated(app_db: FastAPI) -> None:
    client = TestClient(app_db)
    client.cookies.set(_COOKIE, "not-a-real-refresh-token")
    assert client.post("/api/v1/auth/refresh").status_code == 401


# --- rotation + reuse-detection --------------------------------------------- #
def test_a_replayed_refresh_token_revokes_the_whole_family(
    app_db: FastAPI, make_user, monkeypatch, caplog
) -> None:
    from terp.core import settings

    # Grace 0: any replay of a spent token is theft (no benign-race window in this test).
    monkeypatch.setattr(settings, "REFRESH_ROTATION_GRACE_SECONDS", 0)
    make_user("theft@example.com", "correct horse battery", Roles.EDITOR)
    client = _login(app_db, "theft@example.com", "correct horse battery")
    stolen = client.cookies[_COOKIE]

    # The legitimate client rotates once (spending `stolen`, receiving a successor).
    first = client.post("/api/v1/auth/refresh")
    assert first.status_code == 200
    successor = client.cookies[_COOKIE]
    assert successor != stolen

    # Replaying the spent token is the theft signal: it is refused AND kills the family,
    # and the security event is surfaced to operators via a structured warning.
    attacker = TestClient(app_db)
    attacker.cookies.set(_COOKIE, stolen)
    with caplog.at_level("WARNING", logger="terp.capabilities.identity.refresh"):
        assert attacker.post("/api/v1/auth/refresh").status_code == 401
    assert any("refresh_token_reuse_detected" in r.getMessage() for r in caplog.records)

    # The legitimate successor is now dead too — the whole family was revoked.
    legit = TestClient(app_db)
    legit.cookies.set(_COOKIE, successor)
    assert legit.post("/api/v1/auth/refresh").status_code == 401


def test_a_racing_rotation_within_the_grace_window_is_benign(
    app_db: FastAPI, make_user
) -> None:
    # Two tabs sharing the cookie jar (or a client retry after a lost response) present the
    # same token twice in quick succession. Within REFRESH_ROTATION_GRACE_SECONDS that is a
    # benign race, not theft: both rotations succeed and the family stays alive.
    make_user("tabs@example.com", "correct horse battery", Roles.EDITOR)
    client = _login(app_db, "tabs@example.com", "correct horse battery")
    shared = client.cookies[_COOKIE]

    first = client.post("/api/v1/auth/refresh")
    assert first.status_code == 200

    other_tab = TestClient(app_db)
    other_tab.cookies.set(_COOKIE, shared)
    second = other_tab.post("/api/v1/auth/refresh")
    assert second.status_code == 200  # honoured, not a family kill

    # Both successors remain live: each tab can keep refreshing independently.
    assert client.post("/api/v1/auth/refresh").status_code == 200
    assert other_tab.post("/api/v1/auth/refresh").status_code == 200


# --- revocation ties in ------------------------------------------------------ #
def test_logout_clears_the_cookie_and_kills_refresh(app_db: FastAPI, make_user) -> None:
    make_user("out@example.com", "correct horse battery", Roles.EDITOR)
    client = _login(app_db, "out@example.com", "correct horse battery")
    cookie = client.cookies[_COOKIE]

    assert client.post("/api/v1/auth/logout").status_code == 204

    # The refresh token is dead after logout — a re-login is required, not a silent refresh.
    replay = TestClient(app_db)
    replay.cookies.set(_COOKIE, cookie)
    assert replay.post("/api/v1/auth/refresh").status_code == 401


def test_deactivation_kills_refresh(app_db: FastAPI, make_user, db_session) -> None:
    uid = make_user("gone@example.com", "correct horse battery", Roles.EDITOR)
    client = _login(app_db, "gone@example.com", "correct horse battery")
    cookie = client.cookies[_COOKIE]

    # Deactivate through the app-wired service (the same one /logout uses): it revokes the
    # refresh families alongside the access-token epoch.
    UsersService(refresh_revoker=RefreshTokenService().revoke_all_for_user).set_active(
        db_session, uid, active=False
    )

    replay = TestClient(app_db)
    replay.cookies.set(_COOKIE, cookie)
    assert replay.post("/api/v1/auth/refresh").status_code == 401


def test_admin_password_reset_kills_refresh_over_the_api(app_db: FastAPI, make_user) -> None:
    admin_id = make_user("admin@example.com", "correct horse battery", Roles.ADMIN)
    victim_id = make_user("victim@example.com", "correct horse battery", Roles.EDITOR)
    victim = _login(app_db, "victim@example.com", "correct horse battery")
    cookie = victim.cookies[_COOKIE]

    admin = _login(app_db, "admin@example.com", "correct horse battery")
    reset = admin.post(
        f"/api/v1/users/{victim_id}/reset-password",
        json={"password": "a brand new correct passphrase"},
    )
    assert reset.status_code == 200, reset.text

    # The victim's refresh cookie is dead after the admin reset (a compromise-response path).
    replay = TestClient(app_db)
    replay.cookies.set(_COOKIE, cookie)
    assert replay.post("/api/v1/auth/refresh").status_code == 401
    assert admin_id != victim_id  # (distinct users; keeps the last-admin invariant satisfied)


def test_refresh_rechecks_the_subject_is_still_active(app_db: FastAPI, make_user, db_session) -> None:
    uid = make_user("race@example.com", "correct horse battery", Roles.EDITOR)
    client = _login(app_db, "race@example.com", "correct horse battery")

    # Simulate a race/partial wiring: the refresh token row is still live, but the subject
    # itself has gone inactive. `/refresh` must rebuild an ACTIVE principal from the store,
    # so it refuses instead of minting a fresh access token from a live cookie alone.
    from terp.capabilities.identity import User

    user = db_session.get(User, uid)
    assert user is not None
    user.is_active = False
    db_session.add(user)
    db_session.commit()

    assert client.post("/api/v1/auth/refresh").status_code == 401


# --- service-level expiry (idle + absolute family cap) ----------------------- #
def _row_for(session: Session, raw_digest_of: str) -> RefreshToken:
    from terp.capabilities.auth import refresh_token_digest

    row = session.exec(
        select(RefreshToken).where(RefreshToken.token_hash == refresh_token_digest(raw_digest_of))
    ).first()
    assert row is not None
    return row


def test_rotate_refuses_an_idle_expired_token(db_session: Session) -> None:
    service = RefreshTokenService()
    raw = service.issue(db_session, uuid.uuid4())
    row = _row_for(db_session, raw)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)  # idle window elapsed
    db_session.add(row)
    db_session.commit()

    assert service.rotate(db_session, raw) is None


def test_rotate_refuses_a_token_past_the_family_absolute_cap(db_session: Session) -> None:
    service = RefreshTokenService()
    raw = service.issue(db_session, uuid.uuid4())
    row = _row_for(db_session, raw)
    row.family_expires_at = datetime.now(UTC) - timedelta(seconds=1)  # absolute cap reached
    db_session.add(row)
    db_session.commit()

    assert service.rotate(db_session, raw) is None


def test_purge_expired_deletes_only_dead_families(db_session: Session) -> None:
    service = RefreshTokenService()
    dead_raw = service.issue(db_session, uuid.uuid4())
    live_raw = service.issue(db_session, uuid.uuid4())

    dead = _row_for(db_session, dead_raw)
    dead.family_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.add(dead)
    db_session.commit()
    dead_hash = dead.token_hash

    assert service.purge_expired(db_session) == 1

    # The dead family's row is gone; the live family is untouched and still rotates.
    remaining = db_session.exec(select(RefreshToken)).all()
    assert dead_hash not in {row.token_hash for row in remaining}
    assert service.rotate(db_session, live_raw) is not None


def test_refresh_revoker_failure_rolls_back_the_user_epoch(db_session: Session, make_user) -> None:
    uid = make_user("atomic@example.com", "correct horse battery", Roles.EDITOR)

    def broken_revoker(session: Session, user_id: uuid.UUID) -> None:
        raise RuntimeError("refresh store unavailable")

    service = UsersService(refresh_revoker=broken_revoker)
    try:
        service.reset_password(db_session, uid, "new correct horse battery")
    except RuntimeError as exc:
        assert str(exc) == "refresh store unavailable"
    else:  # pragma: no cover - defensive guard; the assertion above is the expected path
        raise AssertionError("broken refresh revoker should abort the user update")

    db_session.rollback()
    from terp.capabilities.identity import User

    user = db_session.get(User, uid)
    assert user is not None
    assert user.token_version == 0
