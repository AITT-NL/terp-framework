"""End-to-end auth: real Argon2 + JWT login over the persisted identity store."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from terp.core import Roles


def test_login_issues_a_usable_token(app_db: FastAPI, make_user) -> None:
    make_user("editor@example.com", "correct horse battery", Roles.EDITOR)
    client = TestClient(app_db)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "editor@example.com", "password": "correct horse battery"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["token_type"] == "bearer"
    token = response.json()["access_token"]

    client.headers["Authorization"] = f"Bearer {token}"
    created = client.post("/api/v1/notes/", json={"title": "via real login"})
    assert created.status_code == 201


def test_login_rejects_a_bad_password(app_db: FastAPI, make_user) -> None:
    make_user("user@example.com", "correct horse battery", Roles.EDITOR)
    client = TestClient(app_db)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "wrong-pass"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_login_rejects_an_unknown_user(app_db: FastAPI) -> None:
    client = TestClient(app_db)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "whatever"},
    )
    assert response.status_code == 401


def test_a_tampered_token_is_unauthenticated(app_db: FastAPI) -> None:
    client = TestClient(app_db)
    client.headers["Authorization"] = "Bearer not-a-real-jwt"
    assert client.get("/api/v1/notes/").status_code == 401


def test_me_returns_the_authenticated_user(app_db: FastAPI, make_user) -> None:
    user_id = make_user("editor@example.com", "correct horse battery", Roles.EDITOR)
    client = TestClient(app_db)
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "editor@example.com", "password": "correct horse battery"},
    )
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    me = client.get("/api/v1/me/")

    assert me.status_code == 200, me.text
    assert me.json() == {
        "id": str(user_id),
        "email": "editor@example.com",
        "role_rank": int(Roles.EDITOR),
        "role_name": "editor",
    }


def test_me_requires_authentication(app_db: FastAPI) -> None:
    assert TestClient(app_db).get("/api/v1/me/").status_code == 401
