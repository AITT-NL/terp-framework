"""``send_mail`` and the ``MAIL_SEND`` job: a send commits with the write that caused it.

A feature sends mail *because* something happened — a work order was closed, an account
was created — and the send has to agree with the write about whether it happened. Sent
from the request, it does not: the relay is slow or down and the request fails with it,
or the mail goes out and the write then rolls back, and a customer is told about a change
that does not exist. So :func:`send_mail` never talks to a relay. It validates the
message, mints its ``Message-ID``, and **enqueues** the typed :data:`MAIL_SEND` job on the
caller's session — which, with the durable outbox wired, is a row committed in the same
transaction as the business write. The worker (``terp jobs worker``) delivers it
afterwards, and a delivery that fails raises, so the outbox retries it with backoff and
dead-letters it once the budget is spent: the one place an operator looks for work that
did not happen.

With the in-process job queue — the zero-infrastructure default of a development stack —
the job runs inline, so a failing send fails the request that asked for it. That is the
loud version of the same failure, in the environment where loud is what you want.

The relay is a process-wide decision made once, in the composition root, by
:func:`configure_mail` — the API process and the worker both import it, so both hold the
same one. What it takes is a :class:`~terp.capabilities.mail.MailSettings`, or ``None``
when the environment names no relay; ``None`` refuses a production boot and, anywhere
else, installs a stand-in that delivers nothing and says so in the log for every message
(ADR 0128: permissive in the inner loop, never quiet).

**The queued message is sealed at rest (ADR 0199).** With the outbox wired, the job's
payload is a row of ``outbox_message``, and the outbox keeps every row it has dispatched.
A message's recipients and text are a person's data, and a self-service mail's text holds
a credential: its link's token works until it is redeemed or expires. So the payload
carries the ``Message-ID`` and the message as one value of a sealing domain of its own,
sealed under ``SECRET_KEY``; the job opens it under ``SECRET_KEY`` or a
``SECRET_KEY_DECRYPT_FALLBACKS`` entry, and ``terp secrets reseal`` moves it to a new key
after a rotation, as it moves every other sealed value.
"""

from __future__ import annotations

import logging
import math
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.headerregistry import Address
from email.message import EmailMessage
from typing import Any, Final, Self

from pydantic import ConfigDict, model_serializer, model_validator
from sqlmodel import Field, Session

from terp.core import (
    BaseSchema,
    JobContext,
    JobDefinition,
    JobVisibility,
    RetryPolicy,
    SealingDomain,
    enqueue,
)
from terp.core import settings as _platform_settings

from terp.capabilities.mail.errors import MailConfigurationError, MailPlaintextRetiredError, MailSealError
from terp.capabilities.mail.message import (
    MAX_RECIPIENTS,
    MAX_SUBJECT_LENGTH,
    MAX_TEXT_LENGTH,
    MailMessage,
    build_email,
)
from terp.capabilities.mail.settings import MAX_ADDRESS_LENGTH, MailSettings
from terp.capabilities.mail.smtp import SmtpTransport

_logger = logging.getLogger("terp.capabilities.mail")

#: Where a message goes once it is built: the SMTP relay in a deployment, a
#: :class:`CapturingMailTransport` in a test. A transport raises to signal a failed
#: delivery, which is what makes the outbox retry it.
MailTransport = Callable[[EmailMessage], None]

#: The sender while no relay is configured. ``.invalid`` is reserved (RFC 2606) for names
#: that must never resolve, which is exactly what an undelivered message should carry.
_UNCONFIGURED_SENDER = Address(addr_spec="unconfigured@mail.invalid")


class CapturingMailTransport:
    """A transport that keeps every message instead of sending it — for tests.

    ``configure_mail(settings, transport=CapturingMailTransport())`` in a test's setup,
    and each sent message is an :class:`~email.message.EmailMessage` in :attr:`sent`,
    rendered exactly as the relay would have received it.
    """

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def __call__(self, message: EmailMessage) -> None:
        self.sent.append(message)


def _log_undelivered(message: EmailMessage) -> None:
    """The stand-in outside production when no relay is configured: say so, send nothing.

    The subject and the number of recipients reach the log; the addresses and the body
    do not, because a development database is often a copy of a real one.
    """
    _logger.warning(
        "mail NOT delivered — no relay is configured (set MAIL_FROM and SMTP_HOST): "
        "%r to %d recipient(s), %s",
        message["Subject"],
        len(message["To"].addresses),
        message["Message-ID"],
    )


@dataclass(frozen=True)
class _MailRuntime:
    """What ``configure_mail`` decided: the sender and where a built message goes."""

    sender: Address
    transport: MailTransport


_runtime: _MailRuntime | None = None


def configure_mail(
    settings: MailSettings | None, *, transport: MailTransport | None = None
) -> None:
    """Declare this process's relay, once, from the composition root.

    ``settings`` is normally ``mail_settings_from_environment(os.environ)``. ``None`` —
    the environment names no relay — refuses a **production** boot with
    :class:`MailConfigurationError` and, anywhere else, installs a stand-in that delivers
    nothing and logs every message it did not deliver. ``transport`` replaces the SMTP
    relay — with a test's :class:`CapturingMailTransport`, or with a mail provider's HTTP
    API built on ``terp.capabilities.egress`` — and is visible here, in the composition
    root, rather than at any call site. It cannot be combined with ``None``, because a
    message still needs a sender.
    """
    global _runtime
    if settings is None:
        if transport is not None:
            raise ValueError(
                "configure_mail(None, transport=...) has no sender to build a message "
                "from; pass the MailSettings the test sends as"
            )
        if _platform_settings.is_production:
            raise MailConfigurationError(
                "This application sends mail but no relay is configured: set MAIL_FROM "
                "and SMTP_HOST for this environment."
            )
        _logger.warning(
            "no mail relay is configured: messages are logged, not delivered. A "
            "production boot is REFUSED in this state."
        )
        _runtime = _MailRuntime(_UNCONFIGURED_SENDER, _log_undelivered)
        return
    _runtime = _MailRuntime(
        settings.sender_address,
        transport if transport is not None else SmtpTransport(settings),
    )


def reset_mail() -> None:
    """Forget the configured relay (the test-isolation reset)."""
    global _runtime
    _runtime = None


def mail_is_configured() -> bool:
    """Whether the composition root has declared this process's relay with ``configure_mail``.

    For a capability whose every route sends mail (self-service accounts, ADR 0196): it
    refuses to be built without one, so the missing declaration is a boot failure rather
    than an error at the first send.
    """
    return _runtime is not None


def _configured() -> _MailRuntime:
    if _runtime is None:
        raise MailConfigurationError(
            "send_mail was called before configure_mail: declare the relay in the "
            "composition root with configure_mail(mail_settings_from_environment(os.environ))."
        )
    return _runtime


#: The queued message's own key, derived from ``SECRET_KEY`` under a label no other use
#: shares, so a queued mail opens in no other domain and no other domain's value opens here.
_QUEUED: Final[SealingDomain] = SealingDomain("mail.queued", b"terp.mail.queued-message.v1")

#: What every sealing domain writes (``terp.core.secrets``): this prefix, then a Fernet token.
_SEALED_PREFIX: Final[str] = "enc:v1:"

#: The most bytes one character of a message takes in the JSON that is sealed. The
#: serializer writes a control character as a six-byte ``\u00XX`` escape, a quote or a
#: backslash as two bytes, and any other character as its UTF-8, at most four; a lone
#: surrogate, the one string with no UTF-8, is refused when the message is built.
_MAX_BYTES_PER_CHARACTER: Final[int] = 6


def _sealed_length(plaintext_bytes: int) -> int:
    """The length of the value that sealing *plaintext_bytes* bytes writes.

    The prefix, then a Fernet token in base64url with padding: a version byte, an eight-byte
    timestamp, a sixteen-byte IV, the AES-128-CBC ciphertext and a 32-byte HMAC. PKCS7 pads
    the plaintext to the next multiple of sixteen bytes, by a whole block when it is one.
    """
    ciphertext = (plaintext_bytes // 16 + 1) * 16
    return len(_SEALED_PREFIX) + 4 * math.ceil((1 + 8 + 16 + ciphertext + 32) / 3)


#: The longest sealed message there can be, derived from :class:`MailMessage`'s own caps:
#: every character the message can hold, at its widest, inside the JSON around them. That
#: JSON (the keys, the quotes, the commas and brackets of a message to as many recipients as
#: it may have) is measured from the serializer rather than counted by hand. A ``Reply-To``
#: of ``null`` writes four bytes, fewer than the quotes and the shortest address it replaces.
MAX_SEALED_LENGTH: Final[int] = _sealed_length(
    len(
        MailMessage.model_construct(to=[""] * MAX_RECIPIENTS, subject="", text="", reply_to="")
        .model_dump_json()
        .encode("utf-8")
    )
    + _MAX_BYTES_PER_CHARACTER
    * (
        MAX_RECIPIENTS * MAX_ADDRESS_LENGTH
        + MAX_SUBJECT_LENGTH
        + MAX_TEXT_LENGTH
        + MAX_ADDRESS_LENGTH
    )
)

#: The message's own fields: the plaintext form a caller may enqueue, which is sealed when written.
_PLAINTEXT_FIELDS: Final[frozenset[str]] = frozenset(MailMessage.model_fields)

_ONE_FORM = (
    "a MAIL_SEND payload carries its message sealed or, as a caller enqueues it, in "
    "plaintext: exactly one of the two"
)


def _seal(message: MailMessage) -> str:
    """*message* as one value sealed under ``SECRET_KEY``."""
    return _QUEUED.seal(message.model_dump_json())


class MailJobPayload(BaseSchema):
    """The ``MAIL_SEND`` job's payload: the message sealed at rest, and its ``Message-ID``.

    ``sealed`` is the whole message, its recipients, subject, text and ``Reply-To``, as one
    value of the capability's own sealing domain, so the payload an outbox row holds has
    no address and no text in it (ADR 0199). The ``Message-ID`` stays readable: it is the job's
    idempotency key, and it rides the payload rather than being minted at delivery, so
    every retry of one send is the same message to the recipient's mail client.

    The message's own fields, beside the ``Message-ID``, are accepted as input and never
    written: the payload serializes sealed whichever form it was given, so what enqueues one
    in plaintext, ``terp jobs run`` included, queues it sealed. A payload that holds both
    forms, or neither, is refused, and the refusal never repeats what the payload held. A
    stored row in the plaintext form, which only a release before 0.36.1 wrote, is no longer
    read: :meth:`message` refuses it (ADR 0199, decision 3, as amended in 0.39.0).
    """

    model_config = ConfigDict(hide_input_in_errors=True)

    message_id: str = Field(min_length=1, max_length=300)
    sealed: str | None = Field(default=None, min_length=1, max_length=MAX_SEALED_LENGTH)
    #: The plaintext form, gathered from the message's own fields. Never serialized.
    plaintext: MailMessage | None = None

    @model_validator(mode="before")
    @classmethod
    def _gather_the_plaintext_form(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data
        plaintext = {name: data[name] for name in _PLAINTEXT_FIELDS if name in data}
        if all(value is None for value in plaintext.values()):
            return data
        if data.get("plaintext") is not None:
            raise ValueError(_ONE_FORM)  # gathering it would drop the one already there
        # A ``sealed`` beside the fields stays, so the form check below refuses the pair.
        rest = {key: value for key, value in data.items() if key not in plaintext}
        return {**rest, "plaintext": plaintext}

    @model_validator(mode="after")
    def _holds_exactly_one_form(self) -> Self:
        if (self.sealed is None) == (self.plaintext is None):
            raise ValueError(_ONE_FORM)
        return self

    @model_serializer(mode="plain")
    def _serialize_sealed(self) -> dict[str, Any]:
        sealed = _seal(self.plaintext) if self.plaintext is not None else self.sealed
        return {"message_id": self.message_id, "sealed": sealed}

    def message(self) -> MailMessage:
        """The message, opened under ``SECRET_KEY`` or a ``SECRET_KEY_DECRYPT_FALLBACKS`` entry.

        Raises :class:`MailSealError`, naming the remedy, when no configured key opens it:
        the job then fails, and the outbox retries it and in the end dead-letters it. A payload
        read in the plaintext form is a row a release before 0.36.1 queued, since every payload
        this release writes is sealed, and raises :class:`MailPlaintextRetiredError` the same
        way: that reader was retired in 0.39.0.
        """
        if self.plaintext is not None:
            raise MailPlaintextRetiredError()
        opened = _QUEUED.open(self.sealed or "")
        if opened is None:
            raise MailSealError()
        return MailMessage.model_validate_json(opened[0])


def send_mail(session: Session, message: MailMessage) -> str:
    """Queue *message* for delivery on *session*, and return its ``Message-ID``.

    Pass the session of the write the mail is about, so the send commits — or rolls back
    — with it. Nothing is sent from here: the ``MAIL_SEND`` job delivers it. The message
    is sealed before it is queued, whichever queue is wired, so it is never stored in the
    clear. Refused with :class:`MailConfigurationError` when the composition root never
    called :func:`configure_mail`, so a missing declaration surfaces at the first send
    rather than as a queue of jobs that can never run.
    """
    message_id = f"<{uuid.uuid4().hex}@{_configured().sender.domain}>"
    enqueue(
        session,
        job=MAIL_SEND,
        payload=MailJobPayload(message_id=message_id, sealed=_seal(message)),
        idempotency_key=message_id,
    )
    return message_id


def _utc_now() -> datetime:
    """UTC ``now`` for the ``Date`` header (private so tests can patch it)."""
    return datetime.now(UTC)


def deliver_mail(ctx: JobContext, payload: MailJobPayload) -> None:
    """Open the message, build it from the declared sender, and hand it to the transport.

    ``ctx`` is part of every job handler's contract and unused here: a delivery writes
    nothing, so it needs neither the session nor the re-bound actor. A failure propagates —
    :class:`~terp.capabilities.mail.MailDeliveryError` from the relay,
    :class:`MailConfigurationError` from a worker that was started without the composition
    root's ``configure_mail``, or :class:`MailSealError` for a message no configured key
    opens — so the outbox retries and, in the end, dead-letters it where an operator will
    see it. Nothing is sent from a payload that did not open.
    """
    runtime = _configured()
    runtime.transport(
        build_email(
            payload.message(),
            sender=runtime.sender,
            message_id=payload.message_id,
            sent_at=_utc_now(),
        )
    )


#: The typed job contract an app registers in its control plane's ``JobCatalog`` — the
#: capability cannot enqueue a job the catalog does not declare. ``RESTRICTED``, because
#: the payload is a person's message, sealed or not. Retries lean on the outbox: a relay
#: that is down for a while is the common failure, so the backoff starts at a minute,
#: doubles, and levels off at half an hour before the last attempt dead-letters.
MAIL_SEND = JobDefinition(
    name="mail.message.send",
    payload_schema=MailJobPayload,
    handler=deliver_mail,
    retry=RetryPolicy(max_attempts=8, backoff_seconds=60.0, max_backoff_seconds=1800.0),
    queue="mail",
    visibility=JobVisibility.RESTRICTED,
)


__all__ = [
    "MAIL_SEND",
    "MAX_SEALED_LENGTH",
    "CapturingMailTransport",
    "MailJobPayload",
    "MailTransport",
    "configure_mail",
    "deliver_mail",
    "mail_is_configured",
    "reset_mail",
    "send_mail",
]
