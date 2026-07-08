"""Gate for ``terp-cap-webhooks`` (ADR 0051): the SSRF denylist, the never-leaked signing
secret, HMAC-signed delivery, the atomic event -> enqueue trigger, the worker's signed POST
+ delivery record, and the retry / dead-letter path — all with **mocked HTTP** (no network).

The producer side (the ``@subscribe`` trigger) runs against a real ``BaseService`` write so
the **atomicity** claim is proven: the durable delivery row commits with the business write,
and a rollback drops both. The consumer side (the ``WEBHOOK_DELIVER`` job, drained by the
:class:`OutboxWorker`) runs over a **file** SQLite database (so the worker's bookkeeping
session and each job's own ``run_job`` session are independent connections), with an injected
fake sender — proving the signature, the SSRF re-check, the recorded outcome, and that a
failure retries with backoff and dead-letters after the budget.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import pathlib
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import Engine
from sqlmodel import Field, Session, SQLModel, create_engine, select

from terp.core import (
    BaseSchema,
    BaseTable,
    BaseUpdateSchema,
    EventCatalog,
    EventDefinition,
    EventEnvelope,
    JobCatalog,
    JobDefinition,
    JobEnvelope,
    RetryPolicy,
)
from terp.core.events import configure_events
from terp.core.jobs import configure_jobs
from terp.core._internal.session_guard import WriteGuardedSession

from terp.capabilities.eventbus import (
    EventEmittingService,
    LifecycleEventMap,
    current_event_session,
    dispatch_in_process,
)
from terp.capabilities.outbox import (
    KIND_JOB,
    STATUS_DEAD_LETTERED,
    STATUS_DISPATCHED,
    STATUS_PENDING,
    OutboxJobQueue,
    OutboxMessage,
    OutboxWorker,
)
from terp.capabilities.outbox._serde import job_envelope_to_payload

from terp.capabilities.webhooks import (
    OUTCOME_BLOCKED,
    OUTCOME_DELIVERED,
    OUTCOME_FAILED,
    OUTCOME_SKIPPED,
    WEBHOOK_DELIVER,
    WebhookDelivery,
    WebhookDeliveryPayload,
    WebhookResponse,
    WebhookSubscription,
    WebhookSubscriptionCreate,
    WebhookSubscriptionService,
    WebhookSubscriptionUpdate,
    WebhookTargetError,
    deliver_webhook,
    enqueue_webhook_deliveries,
    PinnedTarget,
    is_denied_address,
    is_sealed_secret,
    reset_webhook_sender,
    resolve_pinned_target,
    seal_secret,
    set_webhook_sender,
    unseal_secret,
    validate_webhook_target,
)
from terp.capabilities.webhooks.schemas import WebhookSubscriptionRead

_PAST = datetime(2020, 1, 1, tzinfo=UTC)  # an availability anchor safely in the past
_SECRET = "topsecretsigningkey0123456789"


# --------------------------------------------------------------------------- #
# Synthetic business model + a service that EMITS an event on create.
# --------------------------------------------------------------------------- #
class _Doc(BaseTable, table=True):
    __tablename__ = "_webhook_doc"
    label: str = Field(max_length=50)


class _DocCreate(BaseSchema):
    label: str = Field(max_length=50)


class _DocUpdate(BaseUpdateSchema):
    label: str | None = Field(default=None, max_length=50)


class _DocCreatedPayload(BaseSchema):
    id: uuid.UUID
    label: str = Field(max_length=50)


_DOC_CREATED = EventDefinition(
    name="webhooks.test.doc.created", payload_schema=_DocCreatedPayload
)


class _DocService(EventEmittingService[_Doc, _DocCreate, _DocUpdate]):
    model = _Doc
    event_map = LifecycleEventMap(created=_DOC_CREATED)


class _FakeSender:
    """A mock outbound sender: records each call and returns / raises a canned result."""

    def __init__(self, *, status_code: int = 200, raises: Exception | None = None) -> None:
        self.status_code = status_code
        self.raises = raises
        self.calls: list[tuple[PinnedTarget, bytes, dict[str, str]]] = []

    def __call__(
        self, target: PinnedTarget, body: bytes, headers: dict[str, str]
    ) -> WebhookResponse:
        self.calls.append((target, body, headers))
        if self.raises is not None:
            raise self.raises
        return WebhookResponse(status_code=self.status_code)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def engine(tmp_path: pathlib.Path) -> Iterator[Engine]:
    """A file-backed SQLite engine (independent connections for worker + run_job)."""
    eng = create_engine(f"sqlite:///{tmp_path / 'webhooks.db'}")
    SQLModel.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture(autouse=True)
def _reset_sender() -> Iterator[None]:
    """Restore the default httpx sender after each test (the seam is process-global)."""
    yield
    reset_webhook_sender()


@pytest.fixture
def subscribe_handler() -> Iterator[Callable[[EventDefinition, Callable[[EventEnvelope], None]], None]]:
    """Subscribe an in-process event handler, cleaning up only the names it adds."""
    from terp.capabilities.eventbus import registry

    added: list[str] = []

    def _sub(event: EventDefinition, handler: Callable[[EventEnvelope], None]) -> None:
        registry.subscribe(event)(handler)
        added.append(event.name)

    yield _sub
    for name in added:
        registry._HANDLERS.pop(name, None)


def _add_subscription(
    engine: Engine,
    *,
    event: str,
    target_url: str = "https://8.8.8.8/hook",
    secret: str = _SECRET,
    active: bool = True,
) -> uuid.UUID:
    """Insert one subscription directly and return its id."""
    subscription = WebhookSubscription(
        target_url=target_url, secret=secret, event=event, active=active
    )
    with Session(engine) as session:
        session.add(subscription)
        session.commit()
        return subscription.id


def _job_row(
    engine: Engine,
    *,
    subscription_id: uuid.UUID,
    event: str = _DOC_CREATED.name,
    data: dict | None = None,
) -> tuple[uuid.UUID, WebhookDeliveryPayload]:
    """Insert a ``kind=job`` outbox row carrying a valid ``WEBHOOK_DELIVER`` envelope."""
    payload = WebhookDeliveryPayload(
        subscription_id=subscription_id,
        delivery_id=uuid.uuid4(),
        event=event,
        data=data if data is not None else {"hello": "world"},
    )
    envelope = JobEnvelope(name=WEBHOOK_DELIVER.name, payload=payload.model_dump(mode="json"))
    message = OutboxMessage(
        kind=KIND_JOB,
        name=WEBHOOK_DELIVER.name,
        payload=job_envelope_to_payload(envelope),
        available_at=_PAST,
    )
    with Session(engine) as session:
        session.add(message)
        session.commit()
        return message.id, payload


def _worker(engine: Engine) -> OutboxWorker:
    return OutboxWorker(
        lambda: Session(engine),
        job_session_factory=lambda: WriteGuardedSession(engine),
    )


# --------------------------------------------------------------------------- #
# (1) SSRF — the top OWASP risk: deny private / loopback / link-local / metadata
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "10.0.0.1",  # RFC 1918
        "172.16.0.1",  # RFC 1918
        "192.168.1.1",  # RFC 1918
        "169.254.169.254",  # cloud metadata (link-local)
        "169.254.0.1",  # link-local
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",  # noqa: S104 - SSRF test vector (unspecified), not a bind address
        "::1",  # IPv6 loopback
        "fd00::1",  # IPv6 unique-local
        "fe80::1",  # IPv6 link-local
        "::ffff:127.0.0.1",  # IPv4-mapped loopback (a classic bypass)
    ],
)
def test_ssrf_denylist_rejects_dangerous_addresses(address: str) -> None:
    assert is_denied_address(address) is True


@pytest.mark.parametrize(
    "address", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2001:4860:4860::8888"]
)
def test_ssrf_denylist_allows_public_addresses(address: str) -> None:
    assert is_denied_address(address) is False


def test_validate_target_requires_https() -> None:
    with pytest.raises(WebhookTargetError):
        validate_webhook_target("http://8.8.8.8/hook")


def test_validate_target_requires_a_host() -> None:
    with pytest.raises(WebhookTargetError):
        validate_webhook_target("https:///hook")


def test_validate_target_rejects_a_private_ip_literal() -> None:
    with pytest.raises(WebhookTargetError):
        validate_webhook_target("https://127.0.0.1/hook")


def test_validate_target_rejects_the_metadata_endpoint() -> None:
    with pytest.raises(WebhookTargetError):
        validate_webhook_target("https://169.254.169.254/latest/meta-data/")


def test_validate_target_allows_a_public_ip_literal() -> None:
    validate_webhook_target("https://8.8.8.8/hook")  # no raise


def test_validate_target_blocks_dns_rebinding_to_a_private_ip() -> None:
    # A host that resolves to a private address (the rebinding attack) is rejected.
    with pytest.raises(WebhookTargetError):
        validate_webhook_target("https://evil.example/hook", resolve=lambda _host: ["10.0.0.5"])


def test_validate_target_allows_a_host_resolving_to_a_public_ip() -> None:
    validate_webhook_target(
        "https://good.example/hook", resolve=lambda _host: ["93.184.216.34"]
    )


# --------------------------------------------------------------------------- #
# (2) The signing secret never leaves the API boundary
# --------------------------------------------------------------------------- #
def test_read_schema_has_no_secret_field() -> None:
    assert "secret" not in WebhookSubscriptionRead.model_fields


def test_read_dto_never_serializes_the_secret(engine: Engine) -> None:
    sub_id = _add_subscription(engine, event="x.y", secret="hunter2hunter2hunter2")
    with Session(engine) as session:
        subscription = session.get(WebhookSubscription, sub_id)
        dumped = WebhookSubscriptionRead.model_validate(subscription).model_dump()
    assert "secret" not in dumped
    assert "hunter2" not in json.dumps(dumped, default=str)


# --------------------------------------------------------------------------- #
# (2b) The signing secret is sealed at rest (ADR 0076)
# --------------------------------------------------------------------------- #
def test_seal_round_trips_and_a_legacy_plaintext_passes_through() -> None:
    sealed = seal_secret(_SECRET)
    assert is_sealed_secret(sealed)
    assert _SECRET not in sealed
    assert unseal_secret(sealed) == _SECRET
    # A row written before the control holds the plaintext: it passes through
    # unchanged so an existing subscription keeps delivering.
    assert not is_sealed_secret(_SECRET)
    assert unseal_secret(_SECRET) == _SECRET


def test_service_create_and_update_persist_only_the_sealed_secret(engine: Engine) -> None:
    service = WebhookSubscriptionService()
    with WriteGuardedSession(engine) as session:
        created = service.create(
            session,
            WebhookSubscriptionCreate(
                target_url="https://8.8.8.8/hook", secret=_SECRET, event="x.y"
            ),
        )
        sub_id, version = created.id, created.version
    with Session(engine) as session:
        stored = session.get(WebhookSubscription, sub_id).secret
    assert is_sealed_secret(stored)
    assert _SECRET not in stored
    assert unseal_secret(stored) == _SECRET

    rotated = "rotatedsigningsecret0123456789"
    with WriteGuardedSession(engine) as session:
        service.update(
            session,
            sub_id,
            WebhookSubscriptionUpdate(secret=rotated, version=version),
        )
    with Session(engine) as session:
        stored = session.get(WebhookSubscription, sub_id).secret
    assert is_sealed_secret(stored)
    assert rotated not in stored
    assert unseal_secret(stored) == rotated


def test_worker_unseals_a_sealed_secret_to_sign_the_delivery(engine: Engine) -> None:
    configure_jobs(JobCatalog([WEBHOOK_DELIVER]), queue=OutboxJobQueue())
    sender = _FakeSender(status_code=200)
    set_webhook_sender(sender)
    sub_id = _add_subscription(
        engine, event=_DOC_CREATED.name, secret=seal_secret(_SECRET)
    )
    _job_row(engine, subscription_id=sub_id, data={"k": "v"})

    assert _worker(engine).drain_once().dispatched == 1
    _target, body, headers = sender.calls[0]
    expected_sig = "sha256=" + hmac.new(
        _SECRET.encode("utf-8"),  # signed with the *plaintext*, unsealed only at signing time
        headers["X-Terp-Webhook-Timestamp"].encode("utf-8") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    assert headers["X-Terp-Signature"] == expected_sig


def test_a_secret_that_no_longer_unseals_fails_the_delivery_terminally(
    engine: Engine,
) -> None:
    from terp.core.config import settings

    configure_jobs(JobCatalog([WEBHOOK_DELIVER]), queue=OutboxJobQueue())
    sender = _FakeSender(status_code=200)
    set_webhook_sender(sender)
    original = settings.SECRET_KEY
    try:
        settings.SECRET_KEY = "webhooks-seal-key-one-0123456789abcdef"
        sealed_elsewhere = seal_secret(_SECRET)
        # Flip the key: the sealed value no longer authenticates (a rotated
        # SECRET_KEY without re-sealing, or a tampered row).
        settings.SECRET_KEY = "webhooks-seal-key-two-0123456789abcdef"
        sub_id = _add_subscription(
            engine, event=_DOC_CREATED.name, secret=sealed_elsewhere
        )
        message_id, _payload = _job_row(engine, subscription_id=sub_id)

        assert _worker(engine).drain_once().dispatched == 1
        assert sender.calls == []  # never signed, never sent
        with Session(engine) as session:
            assert session.get(OutboxMessage, message_id).status == STATUS_DISPATCHED
            delivery = session.exec(select(WebhookDelivery)).one()
        assert delivery.outcome == OUTCOME_FAILED
        assert "unsealed" in delivery.last_error
    finally:
        settings.SECRET_KEY = original


# --------------------------------------------------------------------------- #
# (3) The worker delivers a signed payload and records the outcome
# --------------------------------------------------------------------------- #
def test_worker_posts_a_signed_payload_and_records_a_delivery(engine: Engine) -> None:
    configure_jobs(JobCatalog([WEBHOOK_DELIVER]), queue=OutboxJobQueue())
    sender = _FakeSender(status_code=200)
    set_webhook_sender(sender)
    sub_id = _add_subscription(engine, event=_DOC_CREATED.name, secret=_SECRET)
    data = {"id": str(uuid.uuid4()), "label": "hello"}
    message_id, payload = _job_row(engine, subscription_id=sub_id, data=data)

    result = _worker(engine).drain_once()

    assert result.dispatched == 1
    assert len(sender.calls) == 1
    target, body, headers = sender.calls[0]
    assert target.url == "https://8.8.8.8/hook"
    assert target.ip == "8.8.8.8"  # pinned to the validated address
    expected_body = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    assert body == expected_body
    timestamp = headers["X-Terp-Webhook-Timestamp"]
    assert timestamp.isdigit()  # a unix-seconds stamp bound into the signature
    expected_sig = "sha256=" + hmac.new(
        _SECRET.encode("utf-8"),
        timestamp.encode("utf-8") + b"." + expected_body,
        hashlib.sha256,
    ).hexdigest()
    assert headers["X-Terp-Signature"] == expected_sig
    assert headers["X-Terp-Event"] == _DOC_CREATED.name
    assert headers["X-Terp-Delivery-Id"] == str(payload.delivery_id)
    with Session(engine) as session:
        assert session.get(OutboxMessage, message_id).status == STATUS_DISPATCHED
        delivery = session.exec(select(WebhookDelivery)).one()
    assert delivery.outcome == OUTCOME_DELIVERED
    assert delivery.response_code == 200
    assert delivery.subscription_id == sub_id


# --------------------------------------------------------------------------- #
# (4) Failure path: record + propagate -> retry with backoff -> dead-letter
# --------------------------------------------------------------------------- #
def _fast_catalog() -> JobCatalog:
    """A same-name catalog entry with a tiny budget so dead-letter is reached in two drains."""
    return JobCatalog(
        [
            JobDefinition(
                name=WEBHOOK_DELIVER.name,
                payload_schema=WebhookDeliveryPayload,
                handler=deliver_webhook,
                retry=RetryPolicy(max_attempts=2, backoff_seconds=0.0),
            )
        ]
    )


def test_non_2xx_response_retries_then_dead_letters(engine: Engine) -> None:
    configure_jobs(_fast_catalog(), queue=OutboxJobQueue())
    sender = _FakeSender(status_code=500)
    set_webhook_sender(sender)
    sub_id = _add_subscription(engine, event=_DOC_CREATED.name)
    message_id, _ = _job_row(engine, subscription_id=sub_id)
    worker = _worker(engine)

    first = worker.drain_once()
    assert first.retried == 1
    with Session(engine) as session:
        row = session.get(OutboxMessage, message_id)
        assert row.status == STATUS_PENDING
        assert row.attempts == 1
        assert len(session.exec(select(WebhookDelivery)).all()) == 1

    second = worker.drain_once()
    assert second.dead_lettered == 1
    with Session(engine) as session:
        row = session.get(OutboxMessage, message_id)
        assert row.status == STATUS_DEAD_LETTERED
        assert row.attempts == 2
        deliveries = session.exec(select(WebhookDelivery)).all()
    assert len(deliveries) == 2
    assert all(d.outcome == OUTCOME_FAILED for d in deliveries)
    assert all(d.response_code == 500 for d in deliveries)
    assert len(sender.calls) == 2


def test_network_error_is_recorded_and_retried(engine: Engine) -> None:
    configure_jobs(_fast_catalog(), queue=OutboxJobQueue())
    set_webhook_sender(_FakeSender(raises=RuntimeError("connection refused")))
    sub_id = _add_subscription(engine, event=_DOC_CREATED.name)
    _job_row(engine, subscription_id=sub_id)

    result = _worker(engine).drain_once()

    assert result.retried == 1
    with Session(engine) as session:
        delivery = session.exec(select(WebhookDelivery)).one()
    assert delivery.outcome == OUTCOME_FAILED
    assert delivery.response_code is None
    assert delivery.last_error is not None
    assert "connection refused" in delivery.last_error


# --------------------------------------------------------------------------- #
# (5) Deterministic terminal outcomes are not retried (no wasted attempts)
# --------------------------------------------------------------------------- #
def test_delivery_blocks_an_ssrf_target_without_posting(engine: Engine) -> None:
    configure_jobs(JobCatalog([WEBHOOK_DELIVER]), queue=OutboxJobQueue())
    sender = _FakeSender(status_code=200)
    set_webhook_sender(sender)
    # A subscription stored with a private target (e.g. via DNS rebinding) — blocked at delivery.
    sub_id = _add_subscription(
        engine, event=_DOC_CREATED.name, target_url="https://169.254.169.254/"
    )
    _job_row(engine, subscription_id=sub_id)

    result = _worker(engine).drain_once()

    assert result.dispatched == 1  # terminal (no retry)
    assert sender.calls == []  # never POSTed to the metadata endpoint
    with Session(engine) as session:
        assert session.exec(select(WebhookDelivery)).one().outcome == OUTCOME_BLOCKED


def test_inactive_subscription_is_skipped(engine: Engine) -> None:
    configure_jobs(JobCatalog([WEBHOOK_DELIVER]), queue=OutboxJobQueue())
    sender = _FakeSender(status_code=200)
    set_webhook_sender(sender)
    sub_id = _add_subscription(engine, event=_DOC_CREATED.name, active=False)
    _job_row(engine, subscription_id=sub_id)

    result = _worker(engine).drain_once()

    assert result.dispatched == 1
    assert sender.calls == []
    with Session(engine) as session:
        assert session.exec(select(WebhookDelivery)).one().outcome == OUTCOME_SKIPPED


def test_removed_subscription_is_skipped(engine: Engine) -> None:
    configure_jobs(JobCatalog([WEBHOOK_DELIVER]), queue=OutboxJobQueue())
    set_webhook_sender(_FakeSender(status_code=200))
    _job_row(engine, subscription_id=uuid.uuid4())  # no such subscription

    result = _worker(engine).drain_once()

    assert result.dispatched == 1
    with Session(engine) as session:
        assert session.exec(select(WebhookDelivery)).one().outcome == OUTCOME_SKIPPED


def test_oversized_payload_fails_without_posting(engine: Engine) -> None:
    configure_jobs(JobCatalog([WEBHOOK_DELIVER]), queue=OutboxJobQueue())
    sender = _FakeSender(status_code=200)
    set_webhook_sender(sender)
    sub_id = _add_subscription(engine, event=_DOC_CREATED.name)
    _job_row(engine, subscription_id=sub_id, data={"blob": "x" * (256 * 1024 + 1)})

    result = _worker(engine).drain_once()

    assert result.dispatched == 1  # terminal (an oversized body is deterministic — no retry)
    assert sender.calls == []  # never POSTed the oversized body
    with Session(engine) as session:
        assert session.exec(select(WebhookDelivery)).one().outcome == OUTCOME_FAILED


# --------------------------------------------------------------------------- #
# (5b) The default httpx sender + the real DNS resolver paths
# --------------------------------------------------------------------------- #
def test_default_httpx_sender_pins_the_validated_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    import terp.capabilities.webhooks.delivery as delivery

    captured: dict[str, object] = {}

    class _Resp:
        status_code = 204

    class _FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured["client_kwargs"] = kwargs

        def __enter__(self) -> _FakeClient:
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def build_request(self, method, url, *, content, headers, extensions):  # type: ignore[no-untyped-def]
            return httpx.Request(
                method, url, content=content, headers=headers, extensions=extensions
            )

        def send(self, request: httpx.Request) -> _Resp:
            captured["sent_host"] = request.url.host
            captured["host_header"] = request.headers.get("host")
            captured["sni"] = request.extensions.get("sni_hostname")
            return _Resp()

    monkeypatch.setattr(delivery.httpx, "Client", _FakeClient)
    target = PinnedTarget(url="https://example.com/hook", host="example.com", ip="93.184.216.34")
    response = delivery._httpx_sender(target, b"{}", {"X-Terp-Event": "e"})

    assert response.status_code == 204
    assert captured["client_kwargs"]["follow_redirects"] is False
    assert captured["sent_host"] == "93.184.216.34"  # the socket is pinned to the validated IP
    assert captured["host_header"] == "example.com"  # Host preserved for virtual-host routing
    assert captured["sni"] == "example.com"  # TLS verified against the hostname, not the IP


def test_resolve_pinned_target_pins_a_public_ip_literal() -> None:
    pinned = resolve_pinned_target("https://8.8.8.8/hook")
    assert pinned == PinnedTarget(url="https://8.8.8.8/hook", host="8.8.8.8", ip="8.8.8.8")


def test_resolve_pinned_target_pins_a_resolved_hostname() -> None:
    pinned = resolve_pinned_target(
        "https://good.example/hook", resolve=lambda _host: ["93.184.216.34"]
    )
    assert pinned.host == "good.example"
    assert pinned.ip == "93.184.216.34"


def test_resolve_pinned_target_rejects_a_host_with_any_private_address() -> None:
    # A rebinding host that returns a public AND a private address is rejected outright, so a
    # delivery can never be pinned to the private one.
    with pytest.raises(WebhookTargetError):
        resolve_pinned_target(
            "https://evil.example/hook", resolve=lambda _host: ["93.184.216.34", "10.0.0.5"]
        )


def test_resolve_pinned_target_rejects_a_host_that_resolves_to_nothing() -> None:
    # An empty resolution fails closed (rather than being treated as "no denied address").
    with pytest.raises(WebhookTargetError):
        resolve_pinned_target("https://void.example/hook", resolve=lambda _host: [])


def test_validate_target_resolves_a_hostname_via_the_default_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import terp.capabilities.webhooks.ssrf as ssrf

    monkeypatch.setattr(
        ssrf.socket,
        "getaddrinfo",
        lambda _host, _port: [(0, 0, 0, "", ("93.184.216.34", 0))],
    )
    validate_webhook_target("https://good.example/hook")  # no raise


def test_validate_target_rejects_an_unresolvable_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket as _socket

    import terp.capabilities.webhooks.ssrf as ssrf

    def _boom(_host: str, _port: object) -> list[object]:
        raise _socket.gaierror("name resolution failed")

    monkeypatch.setattr(ssrf.socket, "getaddrinfo", _boom)
    with pytest.raises(WebhookTargetError):
        validate_webhook_target("https://nope.example/hook")


# --------------------------------------------------------------------------- #
# (6) The trigger: an event enqueues a delivery atomically with the business write
# --------------------------------------------------------------------------- #
def _wire_trigger(
    subscribe_handler: Callable[[EventDefinition, Callable[[EventEnvelope], None]], None],
) -> None:
    configure_jobs(JobCatalog([WEBHOOK_DELIVER]), queue=OutboxJobQueue())
    configure_events(EventCatalog([_DOC_CREATED]), dispatcher=dispatch_in_process)
    subscribe_handler(
        _DOC_CREATED,
        lambda envelope: enqueue_webhook_deliveries(current_event_session(), envelope),
    )


def test_event_enqueues_a_delivery_atomically_with_the_write(
    engine: Engine, subscribe_handler: Callable[..., None]
) -> None:
    _wire_trigger(subscribe_handler)
    _add_subscription(engine, event=_DOC_CREATED.name)

    with WriteGuardedSession(engine) as session:
        _DocService().create(session, _DocCreate(label="business"))

    with Session(engine) as session:
        assert len(session.exec(select(_Doc)).all()) == 1
        rows = session.exec(select(OutboxMessage)).all()
    assert len(rows) == 1  # one durable delivery row, committed atomically with the doc
    assert rows[0].kind == KIND_JOB
    assert rows[0].name == WEBHOOK_DELIVER.name


def test_no_matching_subscription_enqueues_nothing(
    engine: Engine, subscribe_handler: Callable[..., None]
) -> None:
    _wire_trigger(subscribe_handler)
    _add_subscription(engine, event="some.other.event")  # different event

    with WriteGuardedSession(engine) as session:
        _DocService().create(session, _DocCreate(label="business"))

    with Session(engine) as session:
        assert len(session.exec(select(_Doc)).all()) == 1
        assert session.exec(select(OutboxMessage)).all() == []


def test_rollback_drops_the_enqueued_delivery(
    engine: Engine, subscribe_handler: Callable[..., None]
) -> None:
    _wire_trigger(subscribe_handler)
    _add_subscription(engine, event=_DOC_CREATED.name)

    class _Boom(RuntimeError):
        pass

    class _FailingDocService(_DocService):
        def _after_write(self, session, entity, action):  # type: ignore[no-untyped-def]
            super()._after_write(session, entity, action)  # emits -> enqueues
            raise _Boom()

    with WriteGuardedSession(engine) as session:
        with pytest.raises(_Boom):
            _FailingDocService().create(session, _DocCreate(label="x"))
        session.rollback()

    with Session(engine) as session:
        assert session.exec(select(_Doc)).all() == []  # business write rolled back
        assert session.exec(select(OutboxMessage)).all() == []  # ... and so did the delivery
