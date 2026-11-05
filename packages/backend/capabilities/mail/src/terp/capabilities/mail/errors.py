"""What can go wrong on the way to a mail relay, as typed errors.

Each is an ``AppError`` subclass, so a send that fails inline (the in-process job queue,
in development) reaches a client through the same envelope as every other failure rather
than as whichever exception ``smtplib`` happened to raise. The distinction between them
is who has to act: a configuration error is the application's own declaration being
absent or refused, a delivery error is the relay, and a seal error is a queued message
that no key the environment lists can open.
"""

from __future__ import annotations

from terp.core import AppError


class MailConfigurationError(AppError):
    """500 — mail is used, but this process has no relay the deployment accepts.

    Raised when :func:`~terp.capabilities.mail.send_mail` is called before the
    composition root ran :func:`~terp.capabilities.mail.configure_mail`, and by
    ``configure_mail`` itself when a production process is given no relay at all. A 500
    rather than a 502: nothing upstream failed — the application was started without a
    decision it needs.
    """

    status_code = 500
    code = "mail_not_configured"
    default_message = "Sending mail is not configured for this application."


class MailDeliveryError(AppError):
    """502 — the relay could not be reached, refused the session, or refused the message.

    Deliberately not a carrier for the relay's own reply. An SMTP error string routinely
    names an internal host, an account or a policy; it belongs in the log with the
    exception chained to it, and what reaches a client is that a mail was not sent.
    Raised inside the ``MAIL_SEND`` job, it is also the signal that makes the durable
    outbox retry with backoff and dead-letter once the budget is spent.
    """

    status_code = 502
    code = "mail_delivery_failed"
    default_message = "The mail could not be handed to the mail server."


class MailSealError(AppError):
    """500 — a queued mail opens under no configured key, so it is not sent (ADR 0199).

    A queued message is sealed under ``SECRET_KEY`` and opens under it or under a
    ``SECRET_KEY_DECRYPT_FALLBACKS`` entry. One that opens under neither was sealed under a
    key the environment no longer lists, retired before ``terp secrets reseal`` moved it, or
    it was damaged. Raised inside the ``MAIL_SEND`` job, it fails the delivery like any other
    failure, so the outbox retries it and dead-letters it once the budget is spent, and
    nothing is ever sent from a payload that did not open.
    """

    status_code = 500
    code = "mail_seal_unreadable"
    default_message = (
        "A queued mail opens under no configured key, so it was not sent. If SECRET_KEY was "
        "rotated, list the key it replaced in SECRET_KEY_DECRYPT_FALLBACKS again: the mail "
        "is sent at its next retry, while it has attempts left. Then run `terp secrets "
        "reseal`, and drop the fallback only once it reports nothing left."
    )


__all__ = ["MailConfigurationError", "MailDeliveryError", "MailSealError"]
