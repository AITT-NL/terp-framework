"""End-to-end (ADR 0195): a native client's refresh token in the body, over the shipped example.

The full example declares ``NativeClients``, so ``main.build()`` mounts ``/native/login`` and
``/native/refresh`` beside the cookie routes. These tests prove the three things that make
that safe: the native session is the same family as a cookie session (rotation, reuse
detection, revocation), a browser is refused before any credential is read so no page can be
handed a token its script could read, and an app that does not opt in has neither route.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from terp.capabilities.auth import NativeClients, build_login_module
from terp.core import Roles

_COOKIE = "terp_refresh"
_LOGIN = "/api/v1/auth/native/login"
_REFRESH = "/api/v1/auth/native/refresh"
_PASSWORD = "correct horse battery"


def _native_login(app_db: FastAPI, email: str) -> dict[str, str]:
    response = TestClient(app_db).post(_LOGIN, json={"email": email, "password": _PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _refresh(app_db: FastAPI, token: str, **headers: str) -> httpx.Response:
    return TestClient(app_db).post(_REFRESH, json={"refresh_token": token}, headers=headers)


# --- the native session ------------------------------------------------------ #
def test_native_login_answers_both_tokens_in_the_body_and_sets_no_cookie(app_db: FastAPI, make_user) -> None:
    make_user("phone@example.com", _PASSWORD, Roles.EDITOR)
    response = TestClient(app_db).post(_LOGIN, json={"email": "phone@example.com", "password": _PASSWORD})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["refresh_token"] and body["access_token"]
    assert "set-cookie" not in response.headers, "a native session never rides a cookie"
    assert response.headers["cache-control"] == "no-store", "a token response is never cached"
    api = TestClient(app_db, headers={"Authorization": f"Bearer {body['access_token']}"})
    assert api.get("/api/v1/notes/").status_code == 200


def test_native_refresh_rotates_the_token_it_was_given(app_db: FastAPI, make_user) -> None:
    make_user("rotate@example.com", _PASSWORD, Roles.EDITOR)
    first = _native_login(app_db, "rotate@example.com")
    refreshed = _refresh(app_db, first["refresh_token"])
    assert refreshed.status_code == 200, refreshed.text
    second = refreshed.json()
    assert second["refresh_token"] != first["refresh_token"], "every refresh rotates"
    assert "set-cookie" not in refreshed.headers
    api = TestClient(app_db, headers={"Authorization": f"Bearer {second['access_token']}"})
    assert api.get("/api/v1/notes/").status_code == 200


def test_a_replayed_body_token_revokes_the_whole_family(app_db: FastAPI, make_user, monkeypatch, caplog) -> None:
    from terp.core import settings

    # Grace 0: any replay of a spent token is theft (no benign-race window in this test).
    monkeypatch.setattr(settings, "REFRESH_ROTATION_GRACE_SECONDS", 0)
    make_user("stolen@example.com", _PASSWORD, Roles.EDITOR)
    stolen = _native_login(app_db, "stolen@example.com")["refresh_token"]
    successor = _refresh(app_db, stolen).json()["refresh_token"]

    with caplog.at_level("WARNING", logger="terp.capabilities.identity.refresh"):
        assert _refresh(app_db, stolen).status_code == 401
    assert any("refresh_token_reuse_detected" in record.getMessage() for record in caplog.records)
    assert _refresh(app_db, successor).status_code == 401, "the whole family is dead, successor included"


def test_an_unknown_body_token_is_unauthenticated(app_db: FastAPI) -> None:
    assert _refresh(app_db, "not-a-real-refresh-token").status_code == 401


def test_logout_with_the_bearer_ends_the_native_session(app_db: FastAPI, make_user) -> None:
    make_user("bye@example.com", _PASSWORD, Roles.EDITOR)
    session = _native_login(app_db, "bye@example.com")
    out = TestClient(app_db, headers={"Authorization": f"Bearer {session['access_token']}"})
    assert out.post("/api/v1/auth/logout").status_code == 204
    assert _refresh(app_db, session["refresh_token"]).status_code == 401


def test_native_refresh_rechecks_the_subject_is_still_active(app_db: FastAPI, make_user, db_session) -> None:
    uid = make_user("inactive@example.com", _PASSWORD, Roles.EDITOR)
    token = _native_login(app_db, "inactive@example.com")["refresh_token"]

    # The token row is live but the subject went inactive without its sessions being revoked:
    # the rotation succeeds and the route must still refuse to mint from it.
    from terp.capabilities.identity import User

    user = db_session.get(User, uid)
    assert user is not None
    user.is_active = False
    db_session.add(user)
    db_session.commit()
    assert _refresh(app_db, token).status_code == 401


# --- a browser is refused ---------------------------------------------------- #
@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://app.example.test"},
        {"Sec-Fetch-Site": "same-origin"},
        {"Sec-Fetch-Mode": "cors"},
        {"Sec-Fetch-Dest": "empty"},
    ],
)
def test_a_request_with_browser_provenance_is_refused_on_both_routes(
    app_db: FastAPI, make_user, headers: dict[str, str]
) -> None:
    make_user("tab@example.com", _PASSWORD, Roles.EDITOR)
    login = TestClient(app_db).post(
        _LOGIN, json={"email": "tab@example.com", "password": _PASSWORD}, headers=headers
    )
    assert login.status_code == 403
    assert login.json()["code"] == "native_client_only"
    assert "refresh_token" not in login.text
    token = _native_login(app_db, "tab@example.com")["refresh_token"]
    refused = _refresh(app_db, token, **headers)
    assert refused.status_code == 403 and refused.json()["code"] == "native_client_only"
    assert _refresh(app_db, token).status_code == 200, "a refused request spends nothing"


def test_the_refusal_comes_before_the_password_is_read(app_db: FastAPI, make_user) -> None:
    make_user("order@example.com", _PASSWORD, Roles.EDITOR)
    response = TestClient(app_db).post(
        _LOGIN,
        json={"email": "order@example.com", "password": "wrong"},
        headers={"Origin": "https://app.example.test"},
    )
    assert response.status_code == 403, "a browser learns nothing about the credential"


def test_a_request_presenting_the_cookie_and_a_body_token_is_refused(app_db: FastAPI, make_user) -> None:
    make_user("both@example.com", _PASSWORD, Roles.EDITOR)
    browser = TestClient(app_db)
    assert browser.post(
        "/api/v1/auth/login", json={"email": "both@example.com", "password": _PASSWORD}
    ).status_code == 200
    assert browser.cookies.get(_COOKIE), "the cookie session exists"
    token = _native_login(app_db, "both@example.com")["refresh_token"]
    response = browser.post(_REFRESH, json={"refresh_token": token})
    assert response.status_code == 403 and response.json()["code"] == "native_client_only"
    # The cookie route never reads a body token: it answers from the cookie alone.
    assert browser.post("/api/v1/auth/refresh", json={"refresh_token": "ignored"}).status_code == 200


# --- the declaration --------------------------------------------------------- #
def test_an_app_that_does_not_opt_in_has_none_of_the_routes() -> None:
    from app.main import build_base_profile

    base = TestClient(build_base_profile())
    assert base.post(_LOGIN, json={"email": "a@example.com", "password": "x"}).status_code == 404
    assert base.post(_REFRESH, json={"refresh_token": "x"}).status_code == 404
    assert base.post("/api/v1/auth/native/logout", json={"refresh_token": "x"}).status_code == 404


@pytest.mark.parametrize("reason", ["", "   "])
def test_native_clients_need_a_reason(reason: str) -> None:
    with pytest.raises(ValueError, match="requires a non-empty justification"):
        NativeClients(reason=reason)


def test_native_clients_without_the_refresh_seams_are_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="native clients need the refresh seams"):
        build_login_module(
            lambda _session, _email, _password: None,
            native_clients=NativeClients(reason="a mobile app"),
        )


# --- no credential is ever stored for replay --------------------------------- #
@pytest.mark.parametrize("path", ["/api/v1/auth/login", _LOGIN])
def test_a_sign_in_route_refuses_an_idempotency_key(app_db: FastAPI, make_user, path: str) -> None:
    make_user("keyed@example.com", _PASSWORD, Roles.EDITOR)
    response = TestClient(app_db).post(
        path,
        json={"email": "keyed@example.com", "password": _PASSWORD},
        headers={"Idempotency-Key": "sign-in-1"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "idempotency_not_supported"
    assert "set-cookie" not in response.headers and "token" not in response.json()


def test_the_cookie_refresh_refuses_an_idempotency_key(app_db: FastAPI, make_user) -> None:
    make_user("cookie-keyed@example.com", _PASSWORD, Roles.EDITOR)
    browser = TestClient(app_db)
    assert browser.post(
        "/api/v1/auth/login", json={"email": "cookie-keyed@example.com", "password": _PASSWORD}
    ).status_code == 200
    keyed = browser.post("/api/v1/auth/refresh", headers={"Idempotency-Key": "refresh-1"})
    assert keyed.status_code == 400 and keyed.json()["code"] == "idempotency_not_supported"
    assert browser.post("/api/v1/auth/refresh").status_code == 200, "the cookie still works without one"


def test_a_captured_refresh_request_cannot_be_replayed_past_its_rotation(
    app_db: FastAPI, make_user, monkeypatch
) -> None:
    """The replay the idempotency store would otherwise serve: a spent token resent with its
    original key. Refused at the route, nothing is stored, so the stolen request yields no
    successor and the reuse detection still sees the replay."""
    from terp.core import settings

    monkeypatch.setattr(settings, "REFRESH_ROTATION_GRACE_SECONDS", 0)
    make_user("captured@example.com", _PASSWORD, Roles.EDITOR)
    spent = _native_login(app_db, "captured@example.com")["refresh_token"]
    captured = {"Idempotency-Key": "refresh-captured"}
    first = _refresh(app_db, spent, **captured)
    assert first.status_code == 400 and "refresh_token" not in first.text
    successor = _refresh(app_db, spent).json()["refresh_token"]
    replayed = _refresh(app_db, spent, **captured)
    assert replayed.status_code == 400 and successor not in replayed.text
    assert _refresh(app_db, spent).status_code == 401, "the replay of the spent token is seen"
    assert _refresh(app_db, successor).status_code == 401, "and the family it belonged to is dead"
