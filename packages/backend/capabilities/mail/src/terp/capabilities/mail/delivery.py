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
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.headerregistry import Address
from email.message import EmailMessage

from sqlmodel import Field, Session

from terp.core import (
    JobContext,
    JobDefinition,
    JobVisibility,
    RetryPolicy,
    enqueue,
)
from terp.core import settings as _platform_settings

from terp.capabilities.mail.errors import MailConfigurationError
from terp.capabilities.mail.message import MailMessage, build_email
from terp.capabilities.mail.settings import MailSettings
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


def _configured() -> _MailRuntime:
    if _runtime is None:
        raise MailConfigurationError(
            "send_mail was called before configure_mail: declare the relay in the "
            "composition root with configure_mail(mail_settings_from_environment(os.environ))."
        )
    return _runtime


class MailJobPayload(MailMessage):
    """The ``MAIL_SEND`` job's payload: the message, plus the identity it was given.

    The ``Message-ID`` rides the payload rather than being minted at delivery, so every
    retry of one send is the same message to the recipient's mail client.
    """

    message_id: str = Field(min_length=1, max_length=300)


def send_mail(session: Session, message: MailMessage) -> str:
    """Queue *message* for delivery on *session*, and return its ``Message-ID``.

    Pass the session of the write the mail is about, so the send commits — or rolls back
    — with it. Nothing is sent from here: the ``MAIL_SEND`` job delivers it. Refused with
    :class:`MailConfigurationError` when the composition root never called
    :func:`configure_mail`, so a missing declaration surfaces at the first send rather
    than as a queue of jobs that can never run.
    """
    message_id = f"<{uuid.uuid4().hex}@{_configured().sender.domain}>"
    enqueue(
        session,
        job=MAIL_SEND,
        payload=MailJobPayload(**message.model_dump(), message_id=message_id),
        idempotency_key=message_id,
    )
    return message_id


def _utc_now() -> datetime:
    """UTC ``now`` for the ``Date`` header (private so tests can patch it)."""
    return datetime.now(UTC)


def deliver_mail(ctx: JobContext, payload: MailJobPayload) -> None:
    """Build the message from the declared sender and hand it to the configured transport.

    ``ctx`` is part of every job handler's contract and unused here: a delivery writes
    nothing, so it needs neither the session nor the re-bound actor. A failure propagates — :class:`~terp.capabilities.mail.MailDeliveryError` from the
    relay, or :class:`MailConfigurationError` from a worker that was started without the
    composition root's ``configure_mail`` — so the outbox retries and, in the end,
    dead-letters it where an operator will see it.
    """
    runtime = _configured()
    runtime.transport(
        build_email(
            payload,
            sender=runtime.sender,
            message_id=payload.message_id,
            sent_at=_utc_now(),
        )
    )


#: The typed job contract an app registers in its control plane's ``JobCatalog`` — the
#: capability cannot enqueue a job the catalog does not declare. ``RESTRICTED``, because
#: the payload holds addresses and a message body. Retries lean on the outbox: a relay
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
    "CapturingMailTransport",
    "MailJobPayload",
    "MailTransport",
    "configure_mail",
    "deliver_mail",
    "reset_mail",
    "send_mail",
]
