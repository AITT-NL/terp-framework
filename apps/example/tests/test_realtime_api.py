"""End-to-end realtime ticket mint/redeem over real login + revocation."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import realtime as realtime_channels
from terp.capabilities.realtime import get_ticket_store
from terp.capabilities.users import UsersService


def _login(app: FastAPI, email: str, password: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return client


def test_real_login_mints_principal_scoped_single_use_ticket(
    app_db: FastAPI, make_user
) -> None:
    subject = make_user("live@example.com", "correct horse battery")
    client = _login(app_db, "live@example.com", "correct horse battery")
    response = client.post(
        "/api/v1/realtime/tickets",
        json={
            "channel": realtime_channels.PERSONAL_UPDATES.name,
            "transport": "websocket",
        },
    )
    assert response.status_code == 201, response.text
    raw = response.json()["ticket"]
    ticket = get_ticket_store().consume(
        raw,
        channel=realtime_channels.PERSONAL_UPDATES.name,
        transport="websocket",
    )
    assert ticket is not None
    assert ticket.principal.id == subject
    assert ticket.audience == str(subject)
    assert ticket.credential  # retained server-side only; never returned in the response
    assert response.json().keys() == {
        "ticket",
        "expires_in",
        "channel",
        "transport",
    }
    assert (
        get_ticket_store().consume(
            raw,
            channel=realtime_channels.PERSONAL_UPDATES.name,
            transport="websocket",
        )
        is None
    )


def test_revoked_login_token_cannot_mint_a_realtime_ticket(
    app_db: FastAPI, make_user, db_session
) -> None:
    subject = make_user("revoked-live@example.com", "correct horse battery")
    client = _login(app_db, "revoked-live@example.com", "correct horse battery")
    UsersService().revoke_sessions(db_session, subject)
    response = client.post(
        "/api/v1/realtime/tickets",
        json={"channel": "system.notices", "transport": "sse"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_unknown_channel_and_wrong_transport_fail_closed(
    app_db: FastAPI, make_user
) -> None:
    make_user("closed-live@example.com", "correct horse battery")
    client = _login(app_db, "closed-live@example.com", "correct horse battery")
    for body in (
        {"channel": "made.up", "transport": "sse"},
        {"channel": "system.notices", "transport": "websocket"},
    ):
        response = client.post("/api/v1/realtime/tickets", json=body)
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"
