"""A queued mail rests sealed (ADR 0199): its outbox row holds a Message-ID and one sealed value.

With the durable outbox wired, a mail's job payload is a row of ``outbox_message``, and the
outbox keeps every row it has dispatched. These tests read that row as a reader of the
database would, as the text the column holds, and hold it to what the ADR claims:

* no address, no subject, no text and no token from a self-service link rests in it, and the
  worker still sends exactly the message that was queued;
* the plaintext form is never written, whichever path enqueues it, and a row a release
  before 0.36.1 stored in it is no longer read: nothing is sent from it, and it dead-letters
  with the remedy;
* a mail sealed under a key that is now only a decrypt fallback delivers, and one that no
  configured key opens is never sent: it fails with the remedy, retries and dead-letters;
* the sealed value's cap is derived from the message's own caps and Fernet's expansion, and
  the largest message there can be fits it.

Every absence is paired with a control that shows the same probe sees what is there.
"""

from __future__ import annotations

import json
import math
import re
import secrets
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from terp.core import InMemoryThrottleStore, InProcessJobQueue, JobCatalog, JobEnvelope, enqueue, get_principal
from terp.core import encrypt_config, settings
from terp.core.app import register_error_handlers
from terp.core.db import get_session
from terp.core.jobs import configure_jobs
from terp.core._internal.session_guard import WriteGuardedSession

from terp.capabilities.auth import hash_password
from terp.capabilities.identity import RefreshTokenService, User
from terp.capabilities.mail import (
    MAIL_SEND,
    MAX_RECIPIENTS,
    CapturingMailTransport,
    MailMessage,
    MailPlaintextRetiredError,
    MailSealError,
    MailSettings,
    configure_mail,
    reset_mail,
    send_mail,
)
from terp.capabilities.mail import delivery
from terp.capabilities.mail.delivery import MAX_SEALED_LENGTH, MailJobPayload
from terp.capabilities.mail.message import MAX_SUBJECT_LENGTH, MAX_TEXT_LENGTH, build_email
from terp.capabilities.mail.settings import MAX_ADDRESS_LENGTH, parse_sender
from terp.capabilities.outbox import STATUS_DEAD_LETTERED, STATUS_PENDING, OutboxJobQueue, OutboxWorker
from terp.capabilities.users import SelfService, UsersService, build_accounts_module

_OLD = secrets.token_urlsafe(32)
_NEW = secrets.token_urlsafe(32)
_SENDER = "Orders <noreply@example.test>"
_SENT_AT = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
_MESSAGE: dict[str, Any] = {
    "to": ["customer@example.test", "second@example.test"],
    "subject": "Your order has shipped",
    "text": "    Order 1042 is on its way.\n\nKind regards,\nThe team\n\n",
    "reply_to": "sales@example.test",
}
#: Everything of the message a reader of the database must not find.
_READABLE = (*_MESSAGE["to"], _MESSAGE["reply_to"], _MESSAGE["subject"], "Order 1042", "Kind regards")


@pytest.fixture(autouse=True)
def _old_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test seals under the old key and stamps a fixed date; none keeps its relay."""
    monkeypatch.setattr(settings, "SECRET_KEY", _OLD)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", [])
    monkeypatch.setattr(settings, "SECRET_KEY_DECRYPT_FALLBACKS", [])
    monkeypatch.setattr(delivery, "_utc_now", lambda: _SENT_AT)
    yield
    reset_mail()


def _rotate(monkeypatch: pytest.MonkeyPatch, *, keep_the_old_key: bool) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", _NEW)
    monkeypatch.setattr(settings, "SECRET_KEY_DECRYPT_FALLBACKS", [_OLD] if keep_the_old_key else [])


@pytest.fixture
def engine(tmp_path: Any) -> Iterator[Any]:
    eng = create_engine(f"sqlite:///{tmp_path / 'sealed.db'}")
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def relay(engine: Any) -> Iterator[CapturingMailTransport]:
    """The durable outbox and a capturing relay: a send is a row until the worker drains it."""
    captured = CapturingMailTransport()
    configure_jobs(JobCatalog([MAIL_SEND]), queue=OutboxJobQueue(), system_actor_id=uuid.uuid4())
    configure_mail(MailSettings(sender=_SENDER, host="smtp.example.test"), transport=captured)
    yield captured


class _Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC) + timedelta(seconds=1)

    def __call__(self) -> datetime:
        return self.now


def _worker(engine: Any, clock: _Clock) -> OutboxWorker:
    return OutboxWorker(
        lambda: Session(engine), job_session_factory=lambda: WriteGuardedSession(engine), clock=clock
    )


def _at_rest(engine: Any) -> list[tuple[str, str, int, str | None]]:
    """Each outbox row as the database holds it: the payload's text, status, attempts, error."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT CAST(payload AS TEXT), status, attempts, last_error FROM outbox_message")
        ).all()
    return [tuple(row) for row in rows]  # type: ignore[misc]


def _strings(value: Any) -> Iterator[str]:
    """Every string in a parsed document, keys included, so an escaped one is read as well."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _readable(stored: str, secret: str) -> bool:
    return secret in stored or any(secret in value for value in _strings(json.loads(stored)))


def _as_built(message: MailMessage, message_id: str) -> bytes:
    """The message exactly as the relay is handed it, built from the original."""
    return build_email(message, sender=parse_sender(_SENDER), message_id=message_id, sent_at=_SENT_AT).as_bytes()


# --------------------------------------------------------------------------- #
# what rests in the outbox
# --------------------------------------------------------------------------- #
def test_a_queued_mail_rests_with_nothing_of_the_message_readable(engine: Any, relay: CapturingMailTransport) -> None:
    message = MailMessage(**_MESSAGE)
    with WriteGuardedSession(engine) as session:
        message_id = send_mail(session, message)

    ((stored, status, _attempts, _error),) = _at_rest(engine)
    assert status == STATUS_PENDING and relay.sent == []
    assert _readable(stored, message_id), "control: the probe reads the row the send wrote"
    assert set(json.loads(stored)["payload"]) == {"message_id", "sealed"}
    assert [secret for secret in _READABLE if _readable(stored, secret)] == []

    _worker(engine, _Clock()).drain_once()
    (email,) = relay.sent
    assert email.as_bytes() == _as_built(message, message_id), "the relay gets exactly what was queued"
    ((after, *_),) = _at_rest(engine)
    assert [secret for secret in _READABLE if _readable(after, secret)] == [], "a dispatched row keeps it sealed"


def _accounts_client(engine: Any) -> TestClient:
    users = UsersService(refresh_revoker=RefreshTokenService().revoke_all_for_user)
    module = build_accounts_module(
        SelfService(
            reason="members open their own accounts",
            users=users,
            throttle_store=InMemoryThrottleStore(),
            link_base="https://app.example.test",
        )
    )
    app = FastAPI()
    register_error_handlers(app)
    assert module.router is not None
    app.include_router(module.router, prefix="/api/v1/accounts")

    def _session() -> Iterator[Session]:
        with WriteGuardedSession(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_principal] = lambda: None
    return TestClient(app, raise_server_exceptions=False)


def test_a_self_service_link_never_rests_in_the_outbox_and_still_works(
    engine: Any, relay: CapturingMailTransport
) -> None:
    with Session(engine) as session:
        session.add(User(email="member@example.test", hashed_password=hash_password("an old long passphrase")))
        session.commit()
    client = _accounts_client(engine)
    assert client.post("/api/v1/accounts/sign-up", json={"email": "new@example.test"}).status_code == 202
    assert client.post("/api/v1/accounts/password-reset", json={"email": "member@example.test"}).status_code == 202

    _worker(engine, _Clock()).drain_once()
    links = {sent["To"]: re.search(r"#token=(\S+)", sent.get_content()) for sent in relay.sent}
    assert set(links) == {"new@example.test", "member@example.test"} and all(links.values())
    tokens = [match.group(1) for match in links.values() if match is not None]
    rows = [stored for stored, *_ in _at_rest(engine)]
    assert len(rows) == 2
    assert all(token in sent.get_content() for sent, token in zip(relay.sent, tokens, strict=True)), "control"
    for stored in rows:
        assert [secret for secret in (*tokens, *links) if _readable(stored, secret)] == []

    # The token that rested sealed is the live credential the link carries.
    sign_up = links["new@example.test"]
    assert sign_up is not None
    opened = client.post(
        "/api/v1/accounts/verify", json={"token": sign_up.group(1), "password": "a new long passphrase"}
    )
    assert opened.status_code == 201


def test_a_token_row_that_fails_to_write_takes_its_mail_with_it(
    engine: Any, relay: CapturingMailTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A self-service mail is queued inside its token row's write unit (ADR 0196): with the
    durable outbox the two commit together, and a row the database refuses queues no mail."""
    from sqlmodel import select

    from terp.capabilities.identity import AccountToken
    from terp.capabilities.users import accounts

    def rows() -> tuple[int, int]:
        with Session(engine) as session:
            return len(_at_rest(engine)), len(session.exec(select(AccountToken)).all())

    client = _accounts_client(engine)
    # Every request below seals the same token, so the token row of the second one to be
    # written is refused by the digest's unique index, after its mail was queued.
    monkeypatch.setattr(accounts, "seal_account_token", lambda purpose, claims, *, ttl: "enc:v1:the-same-token")
    # Control: a request commits its token row and its mail together.
    assert client.post("/api/v1/accounts/sign-up", json={"email": "first@example.test"}).status_code == 202
    assert rows() == (1, 1)

    refused = client.post("/api/v1/accounts/sign-up", json={"email": "second@example.test"})
    assert refused.status_code == 409
    assert rows() == (1, 1), "the refused row's mail rolled back with it"
    refused = client.post("/api/v1/accounts/password-reset", json={"email": "third@example.test"})
    assert refused.status_code == 409 and rows() == (1, 1)


# --------------------------------------------------------------------------- #
# the plaintext form: taken from a caller, never written, no longer read from a row
# --------------------------------------------------------------------------- #
def _legacy(message_id: str = "<legacy@example.test>") -> dict[str, Any]:
    """The payload a release before 0.36.1 queued: the message's fields, in plaintext."""
    return {**MailMessage(**_MESSAGE).model_dump(), "message_id": message_id}


def test_a_row_an_earlier_release_queued_in_plaintext_is_no_longer_read(
    engine: Any, relay: CapturingMailTransport
) -> None:
    """ADR 0199 retired this reader in 0.37.0 on paper, and the code kept it until 0.39.0."""
    legacy = _legacy()
    with pytest.raises(MailPlaintextRetiredError):
        MailJobPayload.model_validate(legacy).message()
    with WriteGuardedSession(engine) as session:  # the row exactly as 0.36.0 wrote it
        OutboxJobQueue().enqueue(session, JobEnvelope(MAIL_SEND.name, legacy, legacy["message_id"]))
    ((stored, *_),) = _at_rest(engine)
    assert _readable(stored, "customer@example.test"), "control: the probe sees plaintext where it is"

    clock = _Clock()
    worker = _worker(engine, clock)
    worker.drain_once()
    ((_stored, status, attempts, error),) = _at_rest(engine)
    assert (status, attempts, relay.sent) == (STATUS_PENDING, 1, [])
    assert error is not None and error.startswith("MailPlaintextRetiredError: ")
    assert "Send it again" in error and "customer@example.test" not in error, "the remedy, not the mail"
    for _ in range(MAIL_SEND.retry.max_attempts - 1):
        clock.now += timedelta(seconds=MAIL_SEND.retry.max_backoff_seconds + 1)
        worker.drain_once()
    ((_stored, status, _attempts, _error),) = _at_rest(engine)
    assert (status, relay.sent) == (STATUS_DEAD_LETTERED, [])


def test_the_retired_plaintext_error_is_a_500_that_says_what_to_do() -> None:
    error = MailPlaintextRetiredError()
    assert (error.status_code, error.code) == (500, "mail_plaintext_retired")
    assert "before 0.36.1" in error.message and "Send it again" in error.message


def test_the_plaintext_form_is_never_written_whatever_enqueues_it(engine: Any, relay: CapturingMailTransport) -> None:
    legacy = _legacy()
    # A caller that skips send_mail and enqueues the plaintext form itself.
    with WriteGuardedSession(engine) as session:
        enqueue(session, job=MAIL_SEND, payload=legacy, idempotency_key=legacy["message_id"])
    ((stored, *_),) = _at_rest(engine)
    assert set(json.loads(stored)["payload"]) == {"message_id", "sealed"}
    assert [secret for secret in _READABLE if _readable(stored, secret)] == []
    # A payload read in plaintext serializes sealed, in both modes.
    read = MailJobPayload.model_validate(legacy)
    assert read.plaintext == MailMessage(**_MESSAGE)
    for dumped in (read.model_dump(), read.model_dump(mode="json")):
        assert set(dumped) == {"message_id", "sealed"} and dumped["sealed"].startswith("enc:v1:")

    _worker(engine, _Clock()).drain_once()
    (email,) = relay.sent
    assert email.as_bytes() == _as_built(MailMessage(**_MESSAGE), legacy["message_id"])


@pytest.mark.parametrize(
    "form",
    [
        pytest.param(lambda legacy, sealed: {"message_id": legacy["message_id"]}, id="neither"),
        pytest.param(lambda legacy, sealed: {**legacy, "sealed": sealed}, id="both"),
        pytest.param(
            lambda legacy, sealed: {**legacy, "plaintext": {k: legacy[k] for k in _MESSAGE}}, id="both-plaintexts"
        ),
        pytest.param(
            lambda legacy, sealed: {"message_id": legacy["message_id"], "sealed": sealed, "plaintext": _MESSAGE},
            id="sealed-and-gathered",
        ),
    ],
)
def test_a_payload_in_both_forms_or_neither_is_refused_without_repeating_it(form: Any) -> None:
    legacy = _legacy()
    sealed = MailJobPayload.model_validate(legacy).model_dump()["sealed"]
    with pytest.raises(ValidationError) as refused:
        MailJobPayload.model_validate(form(legacy, sealed))
    assert "exactly one of the two" in str(refused.value)
    assert [secret for secret in _READABLE if secret in str(refused.value)] == []
    # Control: each form alone is accepted, and the sealed one opens to the message.
    assert MailJobPayload.model_validate(legacy).plaintext == MailMessage(**_MESSAGE)
    assert MailJobPayload.model_validate({"message_id": legacy["message_id"], "sealed": sealed}).message() == (
        MailMessage(**_MESSAGE)
    )


def test_a_payload_read_from_attributes_carries_the_sealed_form_or_is_refused() -> None:
    """The plaintext form is gathered from a mapping, which is what a stored row is."""
    from types import SimpleNamespace

    sealed = MailJobPayload.model_validate(_legacy()).model_dump()["sealed"]
    read = MailJobPayload.model_validate(SimpleNamespace(message_id="<x@example.test>", sealed=sealed))
    assert read.message() == MailMessage(**_MESSAGE)
    with pytest.raises(ValidationError, match="exactly one of the two"):
        MailJobPayload.model_validate(SimpleNamespace(**_legacy()))


class _Observed(InProcessJobQueue):
    """The inline queue, keeping each envelope's payload as the handler is handed it."""

    def __init__(self, engine: Any) -> None:
        super().__init__(session_factory=lambda: WriteGuardedSession(engine))
        self.payloads: list[dict[str, Any]] = []

    def enqueue(self, session: Session, envelope: JobEnvelope) -> str:
        self.payloads.append(dict(envelope.payload))
        return super().enqueue(session, envelope)


def test_the_inline_queue_seals_and_opens_the_same_way(engine: Any) -> None:
    queue = _Observed(engine)
    configure_jobs(JobCatalog([MAIL_SEND]), queue=queue)
    captured = CapturingMailTransport()
    configure_mail(MailSettings(sender=_SENDER, host="smtp.example.test"), transport=captured)
    message = MailMessage(**_MESSAGE)
    with WriteGuardedSession(engine) as session:
        message_id = send_mail(session, message)
    (payload,) = queue.payloads
    assert set(payload) == {"message_id", "sealed"}
    assert [secret for secret in _READABLE if _readable(json.dumps(payload), secret)] == []
    (email,) = captured.sent
    assert email.as_bytes() == _as_built(message, message_id)


# --------------------------------------------------------------------------- #
# a rotation: the fallback opens it, no key at all never sends it
# --------------------------------------------------------------------------- #
def test_a_mail_sealed_under_a_key_now_only_a_decrypt_fallback_delivers(
    engine: Any, relay: CapturingMailTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    from terp.core import SealState, check_sealed_value

    message = MailMessage(**_MESSAGE)
    with WriteGuardedSession(engine) as session:
        message_id = send_mail(session, message)
    _rotate(monkeypatch, keep_the_old_key=True)
    ((stored, *_),) = _at_rest(engine)
    sealed = json.loads(stored)["payload"]["sealed"]
    assert check_sealed_value(sealed).state is SealState.FALLBACK, "control: only the fallback opens it"

    _worker(engine, _Clock()).drain_once()
    (email,) = relay.sent
    assert email.as_bytes() == _as_built(message, message_id)


def _unopenable(how: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A queued payload that no configured key opens, three ways."""
    sealed = MailJobPayload.model_validate(_legacy()).model_dump()["sealed"]
    if how == "retired-key":
        _rotate(monkeypatch, keep_the_old_key=False)
    elif how == "tampered":
        sealed = sealed[:-8] + ("A" if sealed[-8] != "A" else "B") + sealed[-7:]
    else:  # sealed by another domain, under the same key
        sealed = encrypt_config(MailMessage(**_MESSAGE).model_dump_json())
    return {"message_id": "<unopenable@example.test>", "sealed": sealed}


@pytest.mark.parametrize("how", ["retired-key", "tampered", "another-domain"])
def test_a_mail_no_configured_key_opens_is_never_sent_and_dead_letters(
    engine: Any, relay: CapturingMailTransport, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    payload = _unopenable(how, monkeypatch)
    with pytest.raises(MailSealError):
        MailJobPayload.model_validate(payload).message()
    with WriteGuardedSession(engine) as session:
        OutboxJobQueue().enqueue(session, JobEnvelope(MAIL_SEND.name, payload, payload["message_id"]))

    clock = _Clock()
    worker = _worker(engine, clock)
    worker.drain_once()
    ((_stored, status, attempts, error),) = _at_rest(engine)
    assert (status, attempts, relay.sent) == (STATUS_PENDING, 1, [])
    assert error is not None and error.startswith("MailSealError: ")
    assert "SECRET_KEY_DECRYPT_FALLBACKS" in error and "terp secrets reseal" in error, "it names the remedy"
    for _ in range(MAIL_SEND.retry.max_attempts - 1):
        clock.now += timedelta(seconds=MAIL_SEND.retry.max_backoff_seconds + 1)
        worker.drain_once()
    ((_stored, status, attempts, _error),) = _at_rest(engine)
    assert (status, attempts, relay.sent) == (STATUS_DEAD_LETTERED, MAIL_SEND.retry.max_attempts, [])


def test_listing_the_retired_key_again_sends_the_mail_at_its_next_retry(
    engine: Any, relay: CapturingMailTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    message = MailMessage(**_MESSAGE)
    with WriteGuardedSession(engine) as session:
        message_id = send_mail(session, message)
    _rotate(monkeypatch, keep_the_old_key=False)  # the old key retired before the re-seal ran
    clock = _Clock()
    worker = _worker(engine, clock)
    worker.drain_once()
    assert relay.sent == []

    _rotate(monkeypatch, keep_the_old_key=True)  # the remedy the failure names
    clock.now += timedelta(seconds=MAIL_SEND.retry.backoff_seconds + 1)
    worker.drain_once()
    (email,) = relay.sent
    assert email.as_bytes() == _as_built(message, message_id)


def test_the_seal_error_is_a_500_that_says_what_to_do() -> None:
    error = MailSealError()
    assert (error.status_code, error.code) == (500, "mail_seal_unreadable")
    assert "SECRET_KEY_DECRYPT_FALLBACKS" in error.message and "terp secrets reseal" in error.message


# --------------------------------------------------------------------------- #
# the cap: derived, and the largest message fits it
# --------------------------------------------------------------------------- #
def test_fernets_expansion_is_measured_against_the_cipher() -> None:
    for size in range(70):  # every residue of the sixteen-byte block, more than four times over
        assert delivery._sealed_length(size) == len(delivery._QUEUED.seal("x" * size)), size


def _json_bytes(value: str) -> int:
    """The bytes *value* takes as a field of the sealed JSON, its quotes left out."""
    return len(MailMessage.model_construct(text=value).model_dump_json(include={"text"}).encode()) - len('{"text":""}')


def test_no_character_takes_more_than_six_bytes_in_the_sealed_json() -> None:
    assert max(_json_bytes(chr(code)) for code in range(0x80)) == delivery._MAX_BYTES_PER_CHARACTER == 6
    # Everything else is written as its own UTF-8, at most four bytes: no escape at all.
    wide = "".join(chr(code) for code in range(0x80, 0x110000) if not 0xD800 <= code <= 0xDFFF)
    assert _json_bytes(wide) == len(wide.encode("utf-8"))
    # The one string with no UTF-8 never reaches the serializer.
    with pytest.raises(ValidationError):
        MailMessage(to=["customer@example.test"], subject="Hello", text="lone \ud800 surrogate")


def test_the_largest_message_there_can_be_seals_within_the_cap() -> None:
    address = "a" * 64 + "@" + "b" * 63 + "." + "c" * 63 + "." + "d" * 56 + ".test"
    assert len(address) == MAX_ADDRESS_LENGTH
    widest = MailMessage(
        to=[address] * MAX_RECIPIENTS,
        subject="\U0001f600" * MAX_SUBJECT_LENGTH,  # four bytes each, the widest a header allows
        text="\x01" * MAX_TEXT_LENGTH,  # six bytes each in the JSON
        reply_to=address,
    )
    payload = MailJobPayload(message_id="<widest@example.test>", sealed=delivery._seal(widest))
    assert payload.sealed is not None and len(payload.sealed) <= MAX_SEALED_LENGTH
    assert payload.message() == widest
    with pytest.raises(ValidationError):
        MailJobPayload(message_id="<x@example.test>", sealed="enc:v1:" + "A" * (MAX_SEALED_LENGTH - 6))
    # Derived, not padded: what the cap holds beyond the widest message is what an address
    # could take and an ASCII one does not (five bytes of six) and what a subject's widest
    # character leaves (two of six), plus one block of padding, in base64.
    slack = 5 * (MAX_RECIPIENTS + 1) * MAX_ADDRESS_LENGTH + 2 * MAX_SUBJECT_LENGTH + 16
    assert 0 <= MAX_SEALED_LENGTH - len(payload.sealed) <= 4 * math.ceil(slack / 3)
    # The derivation counts the four fields a message has; a fifth has to join it.
    assert set(MailMessage.model_fields) == {"to", "subject", "text", "reply_to"}
