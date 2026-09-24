"""The one relay an application sends through, declared once instead of decided per send.

An application that sends mail decides which server it talks to, how the connection is
protected, which account it signs in as and who the mail is *from*. If any of those is
an argument to a send, it is decided again at every call site, and the call site is where
"just this once over plaintext" gets written. So all of them are declaration here, and a
message carries none of them:

* the **relay** is one host and port, named by configuration and never by a message — a
  recipient address decides where a mail *ends up*, never which server this process
  opens a connection to;
* the connection is **encrypted by default** — STARTTLS on the submission port, or TLS
  from the first byte on 465 — with the certificate and the hostname verified, and there
  is no setting that turns the verification off;
* **credentials travel only over an encrypted connection**, refused at construction
  otherwise, in every environment;
* the **sender** is fixed. A message may name a ``Reply-To``, never a ``From``, so a
  feature cannot be talked into sending mail that claims to come from someone else;
* a relay without encryption (``MailSecurity.NONE``) exists for the local mail catcher a
  development stack runs, and a production boot refuses it (ADR 0128's shape: the answer
  is environment-independent, so a gate can ask it off the production host).

Deliberately absent: the SSRF denylist the egress capability applies. That list exists
because an outbound URL can be *steered* — built from data a caller influences — and
this destination cannot: it is the one host the deployment configured. What protects a
mail relay is that the session is encrypted and the certificate proves the name, which
is also why a relay on a private network (an on-premises mail server, a development
catcher on the compose network) needs no exception here.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.errors import HeaderParseError
from email.headerregistry import Address
from enum import StrEnum

from terp.core import settings as _platform_settings

_logger = logging.getLogger("terp.capabilities.mail")

#: A bare hostname: letters, digits and hyphens in dot-separated labels. No scheme, no
#: port, no path and no user part — each of those is a sign that a URL was pasted where a
#: host belongs, and a relay "host" of ``smtp://mail.example.com:587`` fails far from here.
_HOSTNAME = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$")

#: ``Display Name <address@example.com>`` — the one shape besides a bare address that a
#: sender setting takes.
_NAMED_ADDRESS = re.compile(r"^(?P<name>[^<>]*?)\s*<(?P<address>[^<>]+)>$")


class MailSecurity(StrEnum):
    """How the connection to the relay is protected.

    ``STARTTLS`` upgrades a plain connection before anything else is said — and a relay
    that does not offer the upgrade is refused rather than spoken to in the clear, which
    is the downgrade an attacker on the path would otherwise only have to strip one line
    to cause. ``TLS`` is encrypted from the first byte (port 465). ``NONE`` is the local
    catcher a development stack runs, and a production boot refuses it.
    """

    STARTTLS = "starttls"
    TLS = "tls"
    NONE = "none"


_DEFAULT_PORT: dict[MailSecurity, int] = {
    MailSecurity.STARTTLS: 587,
    MailSecurity.TLS: 465,
    MailSecurity.NONE: 25,
}


def breaks_a_header(value: str) -> bool:
    """Whether *value* holds a character that ends a header line, or any other control.

    Not only CR and LF. The email package validates and folds a header with
    ``str.splitlines``, which also breaks at the C1 control U+0085 and the Unicode line
    and paragraph separators U+2028 and U+2029, so a value checked for CR and LF alone
    passes validation and is refused when the message is built — a queued mail that can
    never be sent. The categories below are exactly the ones those breaks fall in (Cc,
    Zl, Zp), and Cc takes the remaining controls with it.
    """
    return any(unicodedata.category(ch) in ("Cc", "Zl", "Zp") for ch in value)


def parse_address(value: str) -> Address:
    """Parse one addr-spec (``someone@example.com``) strictly, or raise ``ValueError``.

    Stricter than what RFC 5322 permits, on purpose: the forms refused here are the ones a
    feature never means and an attacker sometimes does. A CR or LF anywhere (header
    injection), a second address smuggled after a comma, an IP-literal domain
    (``someone@[10.0.0.1]``, which skips the recipient's own mail routing), a domain with no
    dot, and a non-ASCII local part — which needs an extension (SMTPUTF8) this capability
    does not negotiate, so accepting it here would only move the refusal to the relay.
    """
    if not value or len(value) > 254:
        raise ValueError(f"not a mail address: {value!r}")
    try:
        address = Address(addr_spec=value)
    except (HeaderParseError, ValueError) as exc:  # the parser's two ways of saying "no"
        raise ValueError(f"not a mail address: {value!r}") from exc
    domain = address.domain.lower()
    if address.addr_spec != value or "." not in domain or not _HOSTNAME.match(domain):
        raise ValueError(f"not a mail address: {value!r}")
    return address


def parse_sender(value: str) -> Address:
    """Parse a sender setting: ``someone@example.com`` or ``Name <someone@example.com>``."""
    named = _NAMED_ADDRESS.match(value.strip())
    if named is None:
        return parse_address(value.strip())
    name = named.group("name").strip().strip('"').strip()
    if breaks_a_header(name):
        raise ValueError(f"not a sender: {value!r}")
    spec = parse_address(named.group("address").strip())
    return Address(display_name=name, username=spec.username, domain=spec.domain)


@dataclass(frozen=True)
class MailSettings:
    """The declared relay and sender of one application.

    ``sender`` is the ``From`` of every message — ``someone@example.com`` or
    ``Name <someone@example.com>``. ``host`` is the relay's bare hostname and ``port``
    defaults to the conventional one for ``security`` (587, 465, or 25). ``username`` and
    ``password`` are both set or both empty; ``password`` is kept out of ``repr`` so the
    object can be logged.
    """

    sender: str
    host: str
    port: int | None = None
    security: MailSecurity = MailSecurity.STARTTLS
    username: str = ""
    password: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        parse_sender(self.sender)
        if not _HOSTNAME.match(self.host):
            raise ValueError(
                "MailSettings.host is the relay's bare lowercase hostname — no scheme, "
                f"port or path: {self.host!r}"
            )
        if self.port is not None and not 0 < self.port < 65536:
            raise ValueError(f"MailSettings.port must be a TCP port: {self.port!r}")
        if bool(self.username) != bool(self.password):
            raise ValueError(
                "MailSettings.username and MailSettings.password are set together or not "
                "at all — a relay account with one half missing fails on the first send"
            )
        if self.username and self.security is MailSecurity.NONE:
            raise ValueError(
                "MailSettings refuses to sign in to a relay over an unencrypted "
                "connection: the password would cross the network in the clear. Use "
                "MailSecurity.STARTTLS or MailSecurity.TLS."
            )

        # Decided by an environment-INDEPENDENT predicate, so the answer exists somewhere
        # a gate can read it and not only inside a branch that runs on the production
        # host. Outside production the same state is said out loud, never tolerated in
        # silence (ADR 0128).
        problems = self.production_problems()
        if problems:
            if _platform_settings.is_production:
                raise ValueError("; ".join(problems))
            _logger.warning(
                "mail relay %s is configured WITHOUT encryption in this deployment. A "
                "production boot is REFUSED in this state.",
                self.host,
            )

    @property
    def sender_address(self) -> Address:
        """The parsed ``From`` address."""
        return parse_sender(self.sender)

    @property
    def resolved_port(self) -> int:
        """The declared port, or the conventional one for the declared security."""
        return self.port if self.port is not None else _DEFAULT_PORT[self.security]

    def production_problems(self) -> list[str]:
        """What a production boot refuses about this relay, environment-independent."""
        if self.security is MailSecurity.NONE:
            return [
                f"mail relay {self.host!r} is configured without encryption "
                "(MailSecurity.NONE); a production relay uses STARTTLS or TLS, because "
                "every message would otherwise cross the network readable"
            ]
        return []


def mail_settings_from_environment(
    environ: Mapping[str, str],
) -> MailSettings | None:
    """Read the relay from the fixed environment variables, or ``None`` when none is set.

    The names are fixed — ``MAIL_FROM``, ``SMTP_HOST``, ``SMTP_PORT``, ``SMTP_SECURITY``,
    ``SMTP_USERNAME`` and ``SMTP_PASSWORD`` — so every Terp application configures its
    relay the same way, and a deployment tool can name them without reading the code.

    ``MAIL_FROM`` and ``SMTP_HOST`` are the two that decide whether a relay is configured
    at all, and they are set together: one without the other is a half-finished
    configuration, and it is refused here rather than discovered at the first send.
    ``SMTP_SECURITY`` is ``starttls`` (the default), ``tls`` or ``none``. Pass
    ``os.environ`` from the composition root.
    """
    sender = environ.get("MAIL_FROM", "").strip()
    host = environ.get("SMTP_HOST", "").strip()
    if not sender and not host:
        return None
    if not sender or not host:
        missing = "MAIL_FROM" if not sender else "SMTP_HOST"
        raise ValueError(
            f"{missing} is not set, but the other half of the mail relay is: set "
            "MAIL_FROM and SMTP_HOST together, or neither"
        )
    raw_security = environ.get("SMTP_SECURITY", "").strip().lower() or MailSecurity.STARTTLS
    try:
        security = MailSecurity(raw_security)
    except ValueError as exc:
        raise ValueError(
            f"SMTP_SECURITY must be one of starttls, tls or none, not {raw_security!r}"
        ) from exc
    raw_port = environ.get("SMTP_PORT", "").strip()
    try:
        port = int(raw_port) if raw_port else None
    except ValueError as exc:
        raise ValueError(f"SMTP_PORT must be a number, not {raw_port!r}") from exc
    return MailSettings(
        sender=sender,
        host=host.lower(),
        port=port,
        security=security,
        username=environ.get("SMTP_USERNAME", "").strip(),
        password=environ.get("SMTP_PASSWORD", ""),
    )


__all__ = [
    "MailSecurity",
    "breaks_a_header",
    "MailSettings",
    "mail_settings_from_environment",
    "parse_address",
    "parse_sender",
]
