"""The platform's one SMTP client: the declared relay, encrypted, verified, time-bounded.

``no_raw_outbound_http`` refuses ``smtplib`` in application code and sends the author to
this capability, for the same arithmetic it applies to HTTP: the things that must be
right about a connection to a mail server are right in as many places as there are
clients. Here they are right once:

* **the session is encrypted before anything is said** — STARTTLS, or TLS from the first
  byte — and a relay that does not offer STARTTLS is refused, never spoken to in the
  clear, because stripping that one capability line is the whole of a downgrade attack;
* **the certificate and the hostname are verified**, by the standard library's default
  context with TLS 1.2 as the floor, and there is no parameter that turns that off;
* **credentials are sent only inside that session**;
* **every socket operation is time-bounded**, so a relay that stops answering holds one
  delivery attempt rather than a worker;
* the ``EHLO`` greeting names the **sender's domain**, not this machine: the default is
  the process's own hostname, which inside a container is an internal name the relay
  would then write into the ``Received`` header of every message.

The relay's own reply is kept out of every error a caller sees. It goes to the log, with
the exception chained, because a mail server's error text routinely names accounts and
internal hosts.
"""

from __future__ import annotations

import logging
import smtplib  # arch-allow-no-raw-outbound-http: this IS the sanctioned mail seam the rule points every other package at; the relay is the one declared host, encrypted and certificate-verified, and no call site can choose another
import ssl
from email.message import EmailMessage
from typing import Final

from terp.capabilities.mail.errors import MailDeliveryError
from terp.capabilities.mail.settings import MailSecurity, MailSettings

_logger = logging.getLogger("terp.capabilities.mail")

#: Bounds every socket operation on the relay connection (connect, each command, each
#: reply). Not a setting: a relay that needs longer than this to answer one command is
#: not going to deliver the message, and the call site is exactly the place that is
#: tempted to raise it "just here".
TIMEOUT_SECONDS: Final[float] = 30.0

#: How much of a relay's error reply reaches the log.
_REPLY_LOG_LIMIT: Final[int] = 300


def _tls_context() -> ssl.SSLContext:
    """Certificate and hostname verified, TLS 1.2 at least — the only context there is."""
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


class SmtpTransport:
    """Hand one message to the declared relay; raise :class:`MailDeliveryError` if it fails.

    Constructed from :class:`~terp.capabilities.mail.MailSettings` by
    :func:`~terp.capabilities.mail.configure_mail`; a composition root never builds one
    itself.
    """

    def __init__(self, settings: MailSettings) -> None:
        self._settings = settings

    def _open(self) -> smtplib.SMTP:
        settings = self._settings
        greeting = settings.sender_address.domain
        if settings.security is MailSecurity.TLS:
            return smtplib.SMTP_SSL(
                settings.host,
                settings.resolved_port,
                local_hostname=greeting,
                timeout=TIMEOUT_SECONDS,
                context=_tls_context(),
            )
        return smtplib.SMTP(
            settings.host,
            settings.resolved_port,
            local_hostname=greeting,
            timeout=TIMEOUT_SECONDS,
        )

    def __call__(self, message: EmailMessage) -> None:
        settings = self._settings
        try:
            client = self._open()
        except (smtplib.SMTPException, OSError) as exc:
            raise self._failure(message, exc) from exc
        try:
            if settings.security is MailSecurity.STARTTLS:
                # Raises SMTPNotSupportedError when the relay does not offer the upgrade:
                # there is no fallback to the unencrypted session.
                client.starttls(context=_tls_context())
            if settings.username:
                client.login(settings.username, settings.password)
            refused = client.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise self._failure(message, exc) from exc
        finally:
            _close(client)
        recipients = len(message["To"].addresses)
        if refused:
            # The relay took the message for some recipients and refused others. That is
            # not retried: a retry would deliver a second copy to everyone it accepted.
            _logger.warning(
                "mail relay %s refused %d of %d recipients of %s",
                settings.host,
                len(refused),
                recipients,
                message["Message-ID"],
            )
        _logger.info(
            "mail relay %s accepted %s for %d recipient(s)",
            settings.host,
            message["Message-ID"],
            recipients - len(refused),
        )

    def _failure(self, message: EmailMessage, exc: BaseException) -> MailDeliveryError:
        """Log what the relay said, and return the error a caller is allowed to see.

        ``OSError`` covers what happens below SMTP: a refused or timed-out connection, a
        name that does not resolve, a TLS handshake or certificate failure. The relay's
        reply is logged here, for the operator, because nothing downstream logs it — the
        durable outbox records only the typed error, and that says nothing on purpose.
        """
        settings = self._settings
        code = getattr(exc, "smtp_code", None)
        reply = getattr(exc, "smtp_error", b"")
        if isinstance(reply, bytes):
            reply = reply.decode("utf-8", "replace")
        _logger.warning(
            "mail relay %s:%d did not take %s: %s %s %s",
            settings.host,
            settings.resolved_port,
            message["Message-ID"],
            type(exc).__name__,
            code if code is not None else "-",
            str(reply)[:_REPLY_LOG_LIMIT],
        )
        return MailDeliveryError(
            "The mail could not be handed to the mail server.",
            log_context={
                "relay": settings.host,
                "port": settings.resolved_port,
                "smtp_code": code,
                "cause": type(exc).__name__,
            },
        )


def _close(client: smtplib.SMTP) -> None:
    """End the session without letting its ending decide the outcome.

    ``QUIT`` comes after the relay has already accepted or refused the message, so an
    error here says nothing about delivery — and treating it as a failure would make the
    outbox deliver an accepted message a second time.
    """
    try:
        client.quit()
    except (smtplib.SMTPException, OSError):
        client.close()


__all__ = ["TIMEOUT_SECONDS", "SmtpTransport"]
