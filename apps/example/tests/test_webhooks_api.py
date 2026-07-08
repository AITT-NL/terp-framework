"""End-to-end slice: outbound webhooks on the example app (ADR 0051).

Proves the real composition: an ADMIN registers an owner-scoped webhook subscription (its
signing secret is never returned), SSRF-unsafe targets are refused at the boundary, a
*different* admin cannot modify another's subscription (the ``OwnedMixin`` per-row gate),
and the full delivery loop runs — creating a note emits ``NOTE_CREATED``, the fan-out
enqueues a durable delivery **atomically** with the note write, and the outbox worker signs
and POSTs it (mocked HTTP) off-request, recording a delivery the read-only log surfaces.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from terp.core import Principal, Roles
from terp.core._internal.session_guard import WriteGuardedSession

from terp.capabilities.outbox import OutboxMessage, OutboxWorker
from terp.capabilities.webhooks import (
    PinnedTarget,
    WebhookResponse,
    reset_webhook_sender,
    set_webhook_sender,
)

_SECRET = "examplewebhooksigningsecret"
_TARGET = "https://8.8.8.8/hook"  # a public IP literal (no DNS), allowed by the denylist
_EVENT = "notes.note.created"


class _RecordingSender:
    """A mock outbound sender that records every POST and returns 200."""

    def __init__(self) -> None:
        self.calls: list[tuple[PinnedTarget, bytes, dict[str, str]]] = []

    def __call__(
        self, target: PinnedTarget, body: bytes, headers: dict[str, str]
    ) -> WebhookResponse:
        self.calls.append((target, body, headers))
        return WebhookResponse(status_code=200)


@pytest.fixture(autouse=True)
def _reset_sender() -> Iterator[None]:
    """Restore the default httpx sender after each test (the seam is process-global)."""
    yield
    reset_webhook_sender()


def _admin(client_factory) -> object:
    return client_factory(Principal(id=uuid.uuid4(), role=Roles.ADMIN))


def _create(client, *, target: str = _TARGET, event: str = _EVENT) -> dict:
    return client.post(
        "/api/v1/webhooks/subscriptions",
        json={"target_url": target, "secret": _SECRET, "event": event},
    ).json()


def test_admin_creates_a_subscription_without_leaking_the_secret(client_factory) -> None:
    principal = Principal(id=uuid.uuid4(), role=Roles.ADMIN)
    client = client_factory(principal)
    created = client.post(
        "/api/v1/webhooks/subscriptions",
        json={"target_url": _TARGET, "secret": _SECRET, "event": _EVENT},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert "secret" not in body  # the signing secret never crosses the API boundary
    assert _SECRET not in created.text
    assert body["owner_id"] == str(principal.id)  # the creator is stamped as the owner
    assert body["target_url"] == _TARGET
    assert body["active"] is True


@pytest.mark.parametrize(
    "bad_target",
    [
        "https://127.0.0.1/hook",  # loopback
        "https://169.254.169.254/latest/",  # cloud metadata
        "https://10.0.0.1/hook",  # private
        "http://8.8.8.8/hook",  # not https
    ],
)
def test_create_rejects_an_ssrf_or_insecure_target(client_factory, bad_target: str) -> None:
    response = _admin(client_factory).post(
        "/api/v1/webhooks/subscriptions",
        json={"target_url": bad_target, "secret": _SECRET, "event": _EVENT},
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "webhook_target_invalid"


def test_list_get_update_and_delete(client_factory) -> None:
    admin = _admin(client_factory)
    sid = _create(admin)["id"]

    listing = admin.get("/api/v1/webhooks/subscriptions")
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1

    assert admin.get(f"/api/v1/webhooks/subscriptions/{sid}").status_code == 200

    patched = admin.patch(
        f"/api/v1/webhooks/subscriptions/{sid}", json={"active": False, "version": 1}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["active"] is False
    assert "secret" not in patched.json()

    # An SSRF target is refused on update too (boundary re-validation).
    rejected = admin.patch(
        f"/api/v1/webhooks/subscriptions/{sid}",
        json={"target_url": "https://10.0.0.1/x", "version": 2},
    )
    assert rejected.status_code == 422

    assert admin.delete(f"/api/v1/webhooks/subscriptions/{sid}").status_code == 204
    assert admin.get(f"/api/v1/webhooks/subscriptions/{sid}").status_code == 404


def test_a_non_owner_admin_cannot_modify_a_subscription(client_factory) -> None:
    owner = client_factory(Principal(id=uuid.uuid4(), role=Roles.ADMIN))
    sid = _create(owner)["id"]

    other = client_factory(Principal(id=uuid.uuid4(), role=Roles.ADMIN))
    # A read is not owner-gated; a write is (the OwnedMixin per-row gate, ADR 0029).
    assert other.get(f"/api/v1/webhooks/subscriptions/{sid}").status_code == 200
    patched = other.patch(
        f"/api/v1/webhooks/subscriptions/{sid}", json={"active": False, "version": 1}
    )
    assert patched.status_code == 403
    assert patched.json()["code"] == "permission_denied"
    assert other.delete(f"/api/v1/webhooks/subscriptions/{sid}").status_code == 403


def test_the_webhooks_surface_is_admin_only(client_factory, editor) -> None:
    # ADMIN-only: an EDITOR clears no route, and an anonymous caller is rejected.
    assert client_factory(editor).get("/api/v1/webhooks/subscriptions").status_code == 403
    assert client_factory(None).get("/api/v1/webhooks/subscriptions").status_code in (401, 403)


def test_creating_a_note_delivers_a_signed_webhook(client_factory, db_engine: Engine) -> None:
    admin = client_factory(Principal(id=uuid.uuid4(), role=Roles.ADMIN))
    sid = _create(admin)["id"]

    sender = _RecordingSender()
    set_webhook_sender(sender)

    # Creating a note emits NOTE_CREATED → the fan-out enqueues a durable delivery row
    # atomically with the note write (no dual-write).
    note = admin.post("/api/v1/notes/", json={"title": "hello"})
    assert note.status_code == 201, note.text
    with Session(db_engine) as session:
        assert len(session.exec(select(OutboxMessage)).all()) == 1

    # Drain the outbox: the worker signs + POSTs the delivery off-request (mocked HTTP).
    worker = OutboxWorker(
        lambda: Session(db_engine),
        job_session_factory=lambda: WriteGuardedSession(db_engine),
    )
    result = worker.run(max_cycles=5)
    assert result.dispatched == 1
    assert len(sender.calls) == 1
    target, _body, headers = sender.calls[0]
    assert target.url == _TARGET
    assert target.ip == "8.8.8.8"  # pinned to the validated address
    assert headers["X-Terp-Event"] == _EVENT
    assert headers["X-Terp-Webhook-Timestamp"].isdigit()
    assert headers["X-Terp-Signature"].startswith("sha256=")

    # The delivery is recorded and visible through the read-only log (filterable).
    deliveries = admin.get("/api/v1/webhooks/deliveries").json()
    assert deliveries["total"] == 1
    assert deliveries["items"][0]["outcome"] == "delivered"
    assert deliveries["items"][0]["subscription_id"] == sid
    filtered = admin.get(f"/api/v1/webhooks/deliveries?subscription_id={sid}").json()
    assert filtered["total"] == 1
