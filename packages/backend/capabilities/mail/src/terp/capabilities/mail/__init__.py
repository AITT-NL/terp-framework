"""Terp mail capability — outbound e-mail through one declared relay.

``no_raw_outbound_http`` refuses ``smtplib`` in application code, for the reason it
refuses a raw HTTP client: whether the connection is encrypted, whether the certificate
is checked, which account signs in and how long a dead server may hold a worker are
decisions, and a raw client makes them again at every call site. This capability makes
them once.

A **library** capability, like ``terp-cap-egress``: no router, no table, no
auto-discovery entry point. An application declares its relay in the composition root
and registers the one job; a feature then sends with one call::

    # app/main.py — the relay, from MAIL_FROM / SMTP_HOST / SMTP_PORT / SMTP_SECURITY /
    # SMTP_USERNAME / SMTP_PASSWORD
    configure_mail(mail_settings_from_environment(os.environ))

    # control_plane/jobs.py
    job_catalog = JobCatalog([MAIL_SEND])

    # a module's service, on the session of the write the mail is about
    send_mail(session, MailMessage(
        to=[order.customer_email],
        subject="Your order has shipped",
        text=f"Order {order.number} is on its way.",
    ))

``send_mail`` sends nothing itself: it enqueues ``MAIL_SEND`` on the caller's session, so
with the durable outbox wired the mail commits — or rolls back — with the write, and the
worker delivers it with retries. The session to the relay is encrypted (STARTTLS or TLS)
with the certificate verified, credentials never cross an unencrypted connection, the
sender is fixed, and a message is plain text with one-line headers and a bounded number
of recipients.
"""

from __future__ import annotations

from terp.capabilities.mail.delivery import (
    MAIL_SEND,
    CapturingMailTransport,
    MailTransport,
    configure_mail,
    reset_mail,
    send_mail,
)
from terp.capabilities.mail.errors import MailConfigurationError, MailDeliveryError
from terp.capabilities.mail.message import MAX_RECIPIENTS, MailMessage
from terp.capabilities.mail.settings import (
    MailSecurity,
    MailSettings,
    mail_settings_from_environment,
)

__all__ = [
    "MAIL_SEND",
    "MAX_RECIPIENTS",
    "CapturingMailTransport",
    "MailConfigurationError",
    "MailDeliveryError",
    "MailMessage",
    "MailSecurity",
    "MailSettings",
    "MailTransport",
    "configure_mail",
    "mail_settings_from_environment",
    "reset_mail",
    "send_mail",
]
