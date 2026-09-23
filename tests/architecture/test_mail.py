"""The mail capability: one declared relay, and every send held to it.

``no_raw_outbound_http`` now refuses ``smtplib`` in application code and sends the author
to ``terp.capabilities.mail``. These tests hold that capability to what it claims, and
most of them are refusals: a message whose header would split, a relay that will not
encrypt, a certificate for the wrong name, a password about to cross the network in the
clear, a production process with no relay at all.

The SMTP half is measured, not mocked. A small relay runs on loopback inside the test —
plain, STARTTLS and implicit TLS, with a certificate issued by a throwaway authority — so
what is asserted about encryption and credentials is what ``smtplib`` actually did on a
real socket. The only substitution is the trust anchor: the client's context is the
production one (``_tls_context``, asserted on its own) with the test authority added.
"""

from __future__ import annotations

import base64
import logging
import pathlib
import socketserver
import ssl
import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from pydantic import ValidationError
from sqlmodel import Field, Session, SQLModel, create_engine, select

from terp.core import (
    AuditAction,
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    InProcessJobQueue,
    JobCatalog,
    JobContext,
)
from terp.core.jobs import configure_jobs
from terp.core._internal.session_guard import WriteGuardedSession

from terp.capabilities.mail import (
    MAIL_SEND,
    MAX_RECIPIENTS,
    CapturingMailTransport,
    MailConfigurationError,
    MailDeliveryError,
    MailMessage,
    MailSecurity,
    MailSettings,
    configure_mail,
    mail_settings_from_environment,
    reset_mail,
    send_mail,
)
from terp.capabilities.mail import smtp as smtp_module
from terp.capabilities.mail.delivery import MailJobPayload, deliver_mail
from terp.capabilities.mail.message import build_email
from terp.capabilities.mail.settings import parse_address, parse_sender
from terp.capabilities.mail.smtp import SmtpTransport, _tls_context
from terp.capabilities.outbox import (
    STATUS_DEAD_LETTERED,
    STATUS_DISPATCHED,
    STATUS_PENDING,
    OutboxJobQueue,
    OutboxMessage,
    OutboxWorker,
)

_SENDER = "Orders <noreply@example.test>"


@pytest.fixture(autouse=True)
def _isolated_mail() -> Iterator[None]:
    """The relay is a process-wide declaration, so every test starts without one."""
    reset_mail()
    yield
    reset_mail()


def _settings(**overrides: object) -> MailSettings:
    values: dict[str, object] = {"sender": _SENDER, "host": "smtp.example.test"}
    values.update(overrides)
    return MailSettings(**values)  # type: ignore[arg-type]


def _message(**overrides: object) -> MailMessage:
    values: dict[str, object] = {
        "to": ["customer@example.test"],
        "subject": "Your order has shipped",
        "text": "Order 1042 is on its way.",
    }
    values.update(overrides)
    return MailMessage(**values)  # type: ignore[arg-type]


def _production(monkeypatch: pytest.MonkeyPatch) -> None:
    from terp.core import settings

    monkeypatch.setattr(type(settings), "is_production", property(lambda self: True))


# --------------------------------------------------------------------------- #
# addresses
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value",
    [
        "",
        "a" * 250 + "@example.test",  # longer than any address a relay accepts
        "customer@example.test\r\nBcc: everyone@example.test",  # header injection
        "a@example.test, b@example.test",  # a second recipient smuggled in
        "customer@[10.0.0.1]",  # an IP literal skips the recipient's mail routing
        "customer@localhost",  # no dot: not a domain anyone else can deliver to
        "jörg@example.test",  # non-ASCII local part needs SMTPUTF8
        '"customer"@example.test',  # quoting that normalises away is not the address
        "customer@exa mple.test",
        "@example.test",
    ],
)
def test_an_address_that_is_not_exactly_one_address_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match="not a mail address"):
        parse_address(value)


def test_a_plain_address_is_accepted_as_written() -> None:
    assert str(parse_address("Customer.Name+tag@sub.example.test")) == (
        "Customer.Name+tag@sub.example.test"
    )


def test_a_sender_is_a_bare_address_or_a_named_one() -> None:
    assert str(parse_sender("noreply@example.test")) == "noreply@example.test"
    named = parse_sender('"Jansen, B.V." <noreply@example.test>')
    assert named.display_name == "Jansen, B.V."
    assert named.addr_spec == "noreply@example.test"
    # Rendered with the quoting the comma needs, not as two addresses.
    assert str(named) == '"Jansen, B.V." <noreply@example.test>'


@pytest.mark.parametrize(
    "value",
    ["Orders\r\nBcc: x@example.test <noreply@example.test>", "Orders <not-an-address>"],
)
def test_a_sender_that_would_split_a_header_is_refused(value: str) -> None:
    with pytest.raises(ValueError):
        parse_sender(value)


# --------------------------------------------------------------------------- #
# the declaration
# --------------------------------------------------------------------------- #
def test_the_default_relay_is_encrypted_on_the_submission_port() -> None:
    settings = _settings()
    assert settings.security is MailSecurity.STARTTLS
    assert settings.resolved_port == 587
    assert settings.production_problems() == []
    assert _settings(security=MailSecurity.TLS).resolved_port == 465
    assert _settings(security=MailSecurity.NONE).resolved_port == 25
    assert _settings(port=2525).resolved_port == 2525


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"host": "smtp://smtp.example.test:587"}, "bare lowercase hostname"),
        ({"host": "SMTP.example.test"}, "bare lowercase hostname"),
        ({"host": ""}, "bare lowercase hostname"),
        ({"port": 0}, "TCP port"),
        ({"port": 70000}, "TCP port"),
        ({"username": "orders"}, "set together"),
        ({"password": "secret-value"}, "set together"),
        ({"sender": "nobody"}, "not a mail address"),
    ],
)
def test_a_relay_declaration_that_would_fail_later_is_refused_now(
    overrides: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        _settings(**overrides)


def test_a_password_never_crosses_an_unencrypted_connection_in_any_environment() -> None:
    with pytest.raises(ValueError, match="unencrypted"):
        _settings(security=MailSecurity.NONE, username="orders", password="secret-value")


def test_the_password_stays_out_of_the_repr() -> None:
    settings = _settings(username="orders", password="secret-value")
    assert "secret-value" not in repr(settings)


def test_an_unencrypted_relay_is_said_out_loud_in_development(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="terp.capabilities.mail"):
        settings = _settings(host="mailpit", port=1025, security=MailSecurity.NONE)
    assert settings.production_problems()
    assert "WITHOUT encryption" in caplog.text


def test_an_unencrypted_relay_refuses_a_production_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _production(monkeypatch)
    with pytest.raises(ValueError, match="without encryption"):
        _settings(host="mailpit", port=1025, security=MailSecurity.NONE)


# --------------------------------------------------------------------------- #
# the environment
# --------------------------------------------------------------------------- #
def test_an_environment_that_names_no_relay_reads_as_none() -> None:
    assert mail_settings_from_environment({}) is None
    assert mail_settings_from_environment({"MAIL_FROM": " ", "SMTP_HOST": ""}) is None


def test_the_environment_is_read_from_the_fixed_names() -> None:
    settings = mail_settings_from_environment(
        {
            "MAIL_FROM": _SENDER,
            "SMTP_HOST": "SMTP.Example.Test",
            "SMTP_PORT": "2587",
            "SMTP_SECURITY": "TLS",
            "SMTP_USERNAME": "orders",
            "SMTP_PASSWORD": "secret-value",
        }
    )
    assert settings == MailSettings(
        sender=_SENDER,
        host="smtp.example.test",
        port=2587,
        security=MailSecurity.TLS,
        username="orders",
        password="secret-value",
    )
    defaults = mail_settings_from_environment(
        {"MAIL_FROM": _SENDER, "SMTP_HOST": "smtp.example.test"}
    )
    assert defaults == _settings()


@pytest.mark.parametrize(
    ("environ", "match"),
    [
        ({"MAIL_FROM": _SENDER}, "SMTP_HOST is not set"),
        ({"SMTP_HOST": "smtp.example.test"}, "MAIL_FROM is not set"),
        (
            {"MAIL_FROM": _SENDER, "SMTP_HOST": "smtp.example.test", "SMTP_SECURITY": "ssl"},
            "SMTP_SECURITY must be one of",
        ),
        (
            {"MAIL_FROM": _SENDER, "SMTP_HOST": "smtp.example.test", "SMTP_PORT": "five"},
            "SMTP_PORT must be a number",
        ),
    ],
)
def test_a_half_configured_environment_is_refused_at_boot(
    environ: dict[str, str], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        mail_settings_from_environment(environ)


# --------------------------------------------------------------------------- #
# the message
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "overrides",
    [
        {"to": []},
        {"to": [f"person{n}@example.test" for n in range(MAX_RECIPIENTS + 1)]},
        {"to": ["a@example.test, b@example.test"]},
        {"subject": "Shipped\r\nBcc: everyone@example.test"},
        {"subject": "Shipped\tnow"},
        {"subject": ""},
        {"text": ""},
        {"text": "a NUL \x00 would fail inside the business write"},
        {"reply_to": "sales@example.test\r\nBcc: everyone@example.test"},
    ],
)
def test_a_message_that_would_misbehave_is_refused_when_it_is_asked_for(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _message(**overrides)


def test_a_message_at_the_recipient_bound_is_accepted() -> None:
    to = [f"person{n}@example.test" for n in range(MAX_RECIPIENTS)]
    assert _message(to=to).to == to


def test_the_rendered_message_is_from_the_declared_sender_and_says_a_program_sent_it() -> None:
    message = _message(
        to=["customer@example.test", "second@example.test"],
        subject="Café heeft je bestelling verzonden",
        text="Line one\nregel twee é",
        reply_to="sales@example.test",
    )
    sent_at = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    email = build_email(
        message,
        sender=parse_sender(_SENDER),
        message_id="<fixed@example.test>",
        sent_at=sent_at,
    )
    assert email["From"] == _SENDER
    assert email["To"] == "customer@example.test, second@example.test"
    assert email["Reply-To"] == "sales@example.test"
    assert email["Subject"] == "Café heeft je bestelling verzonden"
    assert email["Message-ID"] == "<fixed@example.test>"
    assert email["Auto-Submitted"] == "auto-generated"
    assert email["Date"] == "Wed, 23 Sep 2026 12:00:00 +0000"
    assert email["Content-Transfer-Encoding"] == "quoted-printable"
    assert email.get_content() == "Line one\nregel twee é\n"
    assert "Bcc" not in email


def test_a_message_without_a_reply_to_carries_none() -> None:
    email = build_email(
        _message(),
        sender=parse_sender(_SENDER),
        message_id="<fixed@example.test>",
        sent_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    assert "Reply-To" not in email


# --------------------------------------------------------------------------- #
# the relay on a real socket
# --------------------------------------------------------------------------- #
@dataclass
class _Session:
    tls: bool
    commands: list[str] = field(default_factory=list)
    greeting: str | None = None
    credentials: tuple[bytes, ...] | None = None
    authenticated_over_tls: bool | None = None
    recipients: list[str] = field(default_factory=list)
    data: bytes | None = None


class _Relay:
    """A loopback SMTP relay that speaks just enough of the protocol to be honest.

    AUTH is advertised only inside TLS unless ``auth_in_clear`` — the second shape exists
    to prove the client does not take the bait.
    """

    def __init__(
        self,
        *,
        tls: ssl.SSLContext | None = None,
        implicit_tls: bool = False,
        offer_starttls: bool = True,
        auth_in_clear: bool = False,
        auth_ok: bool = True,
        refuse: tuple[str, ...] = (),
        hang_up_after_data: bool = False,
    ) -> None:
        self.tls = tls
        self.implicit_tls = implicit_tls
        self.offer_starttls = offer_starttls
        self.auth_in_clear = auth_in_clear
        self.auth_ok = auth_ok
        self.refuse = refuse
        self.hang_up_after_data = hang_up_after_data
        self.sessions: list[_Session] = []
        relay = self

        class _Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                relay._serve(self.request)

        class _Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

            def handle_error(self, request: object, client_address: object) -> None:
                """A client that walks away mid-handshake is the point of some tests."""

        self._server = _Server(("127.0.0.1", 0), _Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _serve(self, sock: object) -> None:  # noqa: C901 - one small protocol, inline on purpose
        session = _Session(tls=self.implicit_tls)
        self.sessions.append(session)
        if self.implicit_tls:
            assert self.tls is not None
            sock = self.tls.wrap_socket(sock, server_side=True)  # type: ignore[arg-type]
        reader = sock.makefile("rb")  # type: ignore[attr-defined]

        def reply(line: str) -> None:
            sock.sendall(line.encode("ascii") + b"\r\n")  # type: ignore[attr-defined]

        reply("220 relay.test ESMTP")
        while True:
            raw = reader.readline()
            if not raw:
                return
            line = raw.decode("utf-8").rstrip("\r\n")
            verb = line.split(" ", 1)[0].upper()
            session.commands.append(verb)
            if verb in ("EHLO", "HELO"):
                session.greeting = line.split(" ", 1)[1]
                lines = ["relay.test"]
                if self.offer_starttls and self.tls is not None and not session.tls:
                    lines.append("STARTTLS")
                if session.tls or self.auth_in_clear:
                    lines.append("AUTH PLAIN")
                lines.append("8BITMIME")
                for item in lines[:-1]:
                    reply(f"250-{item}")
                reply(f"250 {lines[-1]}")
            elif verb == "STARTTLS":
                reply("220 go ahead")
                reader.close()
                assert self.tls is not None
                sock = self.tls.wrap_socket(sock, server_side=True)  # type: ignore[arg-type]
                reader = sock.makefile("rb")  # type: ignore[attr-defined]
                session.tls = True
            elif verb == "AUTH":
                session.credentials = tuple(base64.b64decode(line.split()[2]).split(b"\0")[1:])
                session.authenticated_over_tls = session.tls
                reply("235 2.7.0 ok" if self.auth_ok else "535 5.7.8 credentials rejected")
            elif verb == "MAIL":
                reply("250 ok")
            elif verb == "RCPT":
                address = line[line.index("<") + 1 : line.index(">")]
                if address in self.refuse:
                    reply("550 5.1.1 no such mailbox")
                else:
                    session.recipients.append(address)
                    reply("250 ok")
            elif verb == "DATA":
                reply("354 go ahead")
                chunks: list[bytes] = []
                while (chunk := reader.readline()) not in (b".\r\n", b""):
                    chunks.append(chunk)
                session.data = b"".join(chunks)
                reply("250 queued")
                if self.hang_up_after_data:
                    return
            elif verb == "QUIT":
                reply("221 bye")
                return
            else:  # RSET, NOOP
                reply("250 ok")


@dataclass(frozen=True)
class _Authority:
    ca_pem: str
    certificates: pathlib.Path

    def server_context(self, name: str) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.certificates / f"{name}.pem", self.certificates / f"{name}.key")
        return context


def _issue(tmp: pathlib.Path, *names: str) -> _Authority:
    """A throwaway certificate authority and one server certificate per *names*.

    RFC 5280-shaped (key usages, key identifiers), because Python's default client
    context verifies strictly and a sloppy test certificate would fail for the wrong
    reason.
    """
    now = datetime.now(UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "terp test authority")])
    usage = {
        "content_commitment": False,
        "key_encipherment": False,
        "data_encipherment": False,
        "key_agreement": False,
        "encipher_only": False,
        "decipher_only": False,
    }
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(hours=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, **usage),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    for name in names:
        key = ec.generate_private_key(ec.SECP256R1())
        certificate = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
            .issuer_name(ca_name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(hours=1))
            .not_valid_after(now + timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(digital_signature=True, key_cert_sign=False, crl_sign=False, **usage),
                critical=True,
            )
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        (tmp / f"{name}.pem").write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        (tmp / f"{name}.key").write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    return _Authority(ca.public_bytes(serialization.Encoding.PEM).decode("ascii"), tmp)


@pytest.fixture
def authority(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> _Authority:
    """Issue test certificates and make the client trust their authority — only that."""
    issued = _issue(tmp_path, "localhost", "other.example.test")

    def _trusting() -> ssl.SSLContext:
        context = _tls_context()
        context.load_verify_locations(cadata=issued.ca_pem)
        return context

    monkeypatch.setattr(smtp_module, "_tls_context", _trusting)
    return issued


@pytest.fixture
def relays() -> Iterator[Callable[..., _Relay]]:
    started: list[_Relay] = []

    def _start(**kwargs: object) -> _Relay:
        relay = _Relay(**kwargs)  # type: ignore[arg-type]
        started.append(relay)
        return relay

    yield _start
    for relay in started:
        relay.close()


def _rendered(**overrides: object) -> EmailMessage:
    return build_email(
        _message(**overrides),
        sender=parse_sender(_SENDER),
        message_id="<relay-test@example.test>",
        sent_at=datetime(2026, 9, 23, tzinfo=UTC),
    )


def _relay_settings(relay: _Relay, **overrides: object) -> MailSettings:
    return _settings(host="localhost", port=relay.port, **overrides)


def test_the_production_context_verifies_the_certificate_and_the_name() -> None:
    context = _tls_context()
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_starttls_encrypts_before_the_password_is_sent(
    authority: _Authority, relays: Callable[..., _Relay], caplog: pytest.LogCaptureFixture
) -> None:
    relay = relays(tls=authority.server_context("localhost"))
    settings = _relay_settings(relay, username="orders", password="secret-value")
    with caplog.at_level(logging.INFO, logger="terp.capabilities.mail"):
        SmtpTransport(settings)(_rendered())
    assert "accepted <relay-test@example.test> for 1 recipient(s)" in caplog.text

    (session,) = relay.sessions
    assert session.tls is True
    assert session.authenticated_over_tls is True
    assert session.credentials == (b"orders", b"secret-value")
    assert session.recipients == ["customer@example.test"]
    assert session.data is not None and b"Subject: Your order has shipped" in session.data
    # The greeting names the sender's domain, never this machine's internal name.
    assert session.greeting == "example.test"
    assert session.commands.index("STARTTLS") < session.commands.index("AUTH")


def test_a_relay_that_does_not_offer_starttls_is_refused_not_spoken_to_in_the_clear(
    authority: _Authority, relays: Callable[..., _Relay], caplog: pytest.LogCaptureFixture
) -> None:
    # The relay even offers to take the password in the clear. It must not get it.
    relay = relays(tls=None, auth_in_clear=True)
    settings = _relay_settings(relay, username="orders", password="secret-value")
    with caplog.at_level(logging.WARNING, logger="terp.capabilities.mail"):
        with pytest.raises(MailDeliveryError) as refused:
            SmtpTransport(settings)(_rendered())

    (session,) = relay.sessions
    assert "AUTH" not in session.commands
    assert "MAIL" not in session.commands
    assert session.data is None
    assert "SMTPNotSupportedError" in caplog.text
    # What reaches a caller is a sentence, not the relay's own words.
    assert refused.value.message == "The mail could not be handed to the mail server."


def test_implicit_tls_is_encrypted_from_the_first_byte(
    authority: _Authority, relays: Callable[..., _Relay]
) -> None:
    relay = relays(tls=authority.server_context("localhost"), implicit_tls=True)
    settings = _relay_settings(
        relay, security=MailSecurity.TLS, username="orders", password="secret-value"
    )
    SmtpTransport(settings)(_rendered())

    (session,) = relay.sessions
    assert session.tls is True
    assert "STARTTLS" not in session.commands
    assert session.authenticated_over_tls is True
    assert session.recipients == ["customer@example.test"]


def test_a_certificate_for_another_name_is_refused_before_anything_is_said(
    authority: _Authority, relays: Callable[..., _Relay], caplog: pytest.LogCaptureFixture
) -> None:
    relay = relays(tls=authority.server_context("other.example.test"))
    settings = _relay_settings(relay, username="orders", password="secret-value")
    with caplog.at_level(logging.WARNING, logger="terp.capabilities.mail"):
        with pytest.raises(MailDeliveryError):
            SmtpTransport(settings)(_rendered())

    (session,) = relay.sessions
    assert session.credentials is None
    assert session.data is None
    assert "SSLCertVerificationError" in caplog.text


def test_a_local_catcher_without_encryption_receives_the_message(
    relays: Callable[..., _Relay],
) -> None:
    relay = relays(tls=None)
    SmtpTransport(_relay_settings(relay, security=MailSecurity.NONE))(_rendered())

    (session,) = relay.sessions
    assert session.tls is False
    assert session.recipients == ["customer@example.test"]


def test_a_relay_that_refuses_every_recipient_fails_the_delivery(
    authority: _Authority, relays: Callable[..., _Relay], caplog: pytest.LogCaptureFixture
) -> None:
    relay = relays(tls=authority.server_context("localhost"), refuse=("customer@example.test",))
    with caplog.at_level(logging.WARNING, logger="terp.capabilities.mail"):
        with pytest.raises(MailDeliveryError):
            SmtpTransport(_relay_settings(relay))(_rendered())
    assert "SMTPRecipientsRefused" in caplog.text


def test_a_partly_refused_message_is_not_retried_into_a_second_copy(
    authority: _Authority, relays: Callable[..., _Relay], caplog: pytest.LogCaptureFixture
) -> None:
    relay = relays(tls=authority.server_context("localhost"), refuse=("gone@example.test",))
    with caplog.at_level(logging.INFO, logger="terp.capabilities.mail"):
        SmtpTransport(_relay_settings(relay))(
            _rendered(to=["customer@example.test", "gone@example.test"])
        )
    (session,) = relay.sessions
    assert session.recipients == ["customer@example.test"]
    assert "refused 1 of 2 recipients" in caplog.text
    assert "for 1 recipient(s)" in caplog.text


def test_rejected_credentials_fail_the_delivery_and_the_log_says_why(
    authority: _Authority, relays: Callable[..., _Relay], caplog: pytest.LogCaptureFixture
) -> None:
    relay = relays(tls=authority.server_context("localhost"), auth_ok=False)
    settings = _relay_settings(relay, username="orders", password="wrong-value")
    with caplog.at_level(logging.WARNING, logger="terp.capabilities.mail"):
        with pytest.raises(MailDeliveryError) as failed:
            SmtpTransport(settings)(_rendered())
    assert "535" in caplog.text
    assert "credentials rejected" in caplog.text
    assert failed.value.log_context["smtp_code"] == 535
    assert "credentials rejected" not in failed.value.message


def test_a_relay_that_cannot_be_reached_fails_the_delivery(
    caplog: pytest.LogCaptureFixture,
) -> None:
    closed = socketserver.TCPServer(("127.0.0.1", 0), socketserver.BaseRequestHandler)
    port = closed.server_address[1]
    closed.server_close()
    with caplog.at_level(logging.WARNING, logger="terp.capabilities.mail"):
        with pytest.raises(MailDeliveryError) as failed:
            SmtpTransport(_settings(host="localhost", port=port))(_rendered())
    assert failed.value.log_context["smtp_code"] is None
    assert "ConnectionRefusedError" in caplog.text


def test_a_session_that_ends_badly_after_the_message_was_taken_is_still_a_delivery(
    authority: _Authority, relays: Callable[..., _Relay]
) -> None:
    relay = relays(tls=authority.server_context("localhost"), hang_up_after_data=True)
    SmtpTransport(_relay_settings(relay))(_rendered())  # does not raise
    (session,) = relay.sessions
    assert session.data is not None
    assert "QUIT" not in session.commands


# --------------------------------------------------------------------------- #
# configure_mail / send_mail / MAIL_SEND
# --------------------------------------------------------------------------- #
class _RecordingQueue(InProcessJobQueue):
    """Keeps each envelope instead of running it."""

    def __init__(self) -> None:
        super().__init__()
        self.envelopes: list[object] = []

    def enqueue(self, session: Session, envelope: object) -> str:  # type: ignore[override]
        self.envelopes.append(envelope)
        return "recorded"


def test_send_mail_before_the_relay_is_declared_is_refused() -> None:
    configure_jobs(JobCatalog([MAIL_SEND]), queue=_RecordingQueue())
    with pytest.raises(MailConfigurationError, match="before configure_mail"):
        send_mail(None, _message())  # type: ignore[arg-type]


def test_a_worker_started_without_the_declaration_fails_the_job_so_it_is_retried() -> None:
    payload = MailJobPayload(**_message().model_dump(), message_id="<x@example.test>")
    with pytest.raises(MailConfigurationError):
        deliver_mail(JobContext(session=None), payload)  # type: ignore[arg-type]


def test_send_mail_enqueues_the_job_with_a_stable_identity() -> None:
    queue = _RecordingQueue()
    configure_jobs(JobCatalog([MAIL_SEND]), queue=queue)
    configure_mail(_settings(), transport=CapturingMailTransport())

    message_id = send_mail(None, _message())  # type: ignore[arg-type]

    (envelope,) = queue.envelopes
    assert envelope.name == MAIL_SEND.name  # type: ignore[attr-defined]
    assert envelope.idempotency_key == message_id  # type: ignore[attr-defined]
    assert envelope.payload["message_id"] == message_id  # type: ignore[attr-defined]
    assert envelope.payload["to"] == ["customer@example.test"]  # type: ignore[attr-defined]
    assert message_id.startswith("<") and message_id.endswith("@example.test>")


def test_the_job_carries_personal_data_and_says_so() -> None:
    from terp.core import JobVisibility

    assert MAIL_SEND.visibility is JobVisibility.RESTRICTED


def test_the_inline_queue_delivers_during_the_send_and_a_failure_fails_the_caller(
    tmp_path: pathlib.Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'inline.db'}")
    configure_jobs(
        JobCatalog([MAIL_SEND]),
        queue=InProcessJobQueue(session_factory=lambda: WriteGuardedSession(engine)),
    )
    captured = CapturingMailTransport()
    configure_mail(_settings(), transport=captured)
    with WriteGuardedSession(engine) as session:
        message_id = send_mail(session, _message())
    (email,) = captured.sent
    assert email["Message-ID"] == message_id
    assert email["From"] == _SENDER

    def _down(_message: EmailMessage) -> None:
        raise MailDeliveryError("The mail could not be handed to the mail server.")

    configure_mail(_settings(), transport=_down)
    with WriteGuardedSession(engine) as session, pytest.raises(MailDeliveryError):
        send_mail(session, _message())
    engine.dispose()


def test_no_relay_in_development_logs_each_message_instead_of_sending_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="terp.capabilities.mail"):
        configure_mail(None)
    assert "REFUSED" in caplog.text
    configure_jobs(JobCatalog([MAIL_SEND]), queue=_RecordingQueue())
    message_id = send_mail(None, _message())  # type: ignore[arg-type]
    assert message_id.endswith("@mail.invalid>")

    payload = MailJobPayload(**_message().model_dump(), message_id=message_id)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="terp.capabilities.mail"):
        deliver_mail(JobContext(session=None), payload)  # type: ignore[arg-type]
    assert "NOT delivered" in caplog.text
    assert "accepted" not in caplog.text  # nothing claims a delivery that did not happen
    assert "Your order has shipped" in caplog.text
    # The address and the body stay out of the log.
    assert "customer@example.test" not in caplog.text
    assert "on its way" not in caplog.text


def test_no_relay_refuses_a_production_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    _production(monkeypatch)
    with pytest.raises(MailConfigurationError, match="no relay is configured"):
        configure_mail(None)


def test_a_captured_message_still_needs_a_sender() -> None:
    with pytest.raises(ValueError, match="no sender"):
        configure_mail(None, transport=CapturingMailTransport())


def test_the_declared_relay_is_the_smtp_transport() -> None:
    from terp.capabilities.mail import delivery

    configure_mail(_settings())
    assert isinstance(delivery._configured().transport, SmtpTransport)


# --------------------------------------------------------------------------- #
# the send and the write it is about
# --------------------------------------------------------------------------- #
class _MailOrder(BaseTable, table=True):
    __tablename__ = "_mail_order"
    number: str = Field(max_length=20)


class _MailOrderCreate(BaseSchema):
    number: str = Field(max_length=20)


class _MailOrderUpdate(BaseUpdateSchema):
    number: str | None = Field(default=None, max_length=20)


class _Refused(RuntimeError):
    pass


class _MailOrderService(BaseService[_MailOrder, _MailOrderCreate, _MailOrderUpdate]):
    model = _MailOrder
    fail_after_send = False

    def _after_write(self, session: Session, entity: _MailOrder, action: AuditAction) -> None:
        if action is AuditAction.CREATED:
            send_mail(session, _message(subject=f"Order {entity.number} received"))
            if self.fail_after_send:
                raise _Refused()


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def engine(tmp_path: pathlib.Path) -> Iterator[object]:
    eng = create_engine(f"sqlite:///{tmp_path / 'mail.db'}")
    SQLModel.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


def _worker(engine: object, clock: _Clock) -> OutboxWorker:
    return OutboxWorker(
        lambda: Session(engine),  # type: ignore[arg-type]
        job_session_factory=lambda: WriteGuardedSession(engine),  # type: ignore[arg-type]
        clock=clock,
    )


def test_a_send_commits_with_its_write_and_the_worker_delivers_it(engine: object) -> None:
    configure_jobs(JobCatalog([MAIL_SEND]), queue=OutboxJobQueue(), system_actor_id=uuid.uuid4())
    captured = CapturingMailTransport()
    configure_mail(_settings(), transport=captured)

    with WriteGuardedSession(engine) as session:  # type: ignore[arg-type]
        _MailOrderService().create(session, _MailOrderCreate(number="1042"))
    assert captured.sent == []  # nothing is sent from the request

    with Session(engine) as session:  # type: ignore[arg-type]
        row = session.exec(select(OutboxMessage)).one()
        assert row.status == STATUS_PENDING
        assert row.name == MAIL_SEND.name

    clock = _Clock(datetime.now(UTC) + timedelta(seconds=1))
    _worker(engine, clock).drain_once()
    (email,) = captured.sent
    assert email["Subject"] == "Order 1042 received"
    with Session(engine) as session:  # type: ignore[arg-type]
        assert session.exec(select(OutboxMessage)).one().status == STATUS_DISPATCHED


def test_a_write_that_rolls_back_takes_its_mail_with_it(engine: object) -> None:
    configure_jobs(JobCatalog([MAIL_SEND]), queue=OutboxJobQueue())
    configure_mail(_settings(), transport=CapturingMailTransport())
    service = _MailOrderService()
    service.fail_after_send = True

    with WriteGuardedSession(engine) as session:  # type: ignore[arg-type]
        with pytest.raises(_Refused):
            service.create(session, _MailOrderCreate(number="1043"))
        session.rollback()
    with Session(engine) as session:  # type: ignore[arg-type]
        assert session.exec(select(_MailOrder)).all() == []
        assert session.exec(select(OutboxMessage)).all() == []


def test_a_relay_that_is_down_is_retried_as_the_same_message_then_dead_lettered(
    engine: object,
) -> None:
    configure_jobs(JobCatalog([MAIL_SEND]), queue=OutboxJobQueue(), system_actor_id=uuid.uuid4())
    seen: list[str] = []

    def _down(message: EmailMessage) -> None:
        seen.append(message["Message-ID"])
        raise MailDeliveryError("The mail could not be handed to the mail server.")

    configure_mail(_settings(), transport=_down)
    with WriteGuardedSession(engine) as session:  # type: ignore[arg-type]
        message_id = send_mail(session, _message())

    clock = _Clock(datetime.now(UTC) + timedelta(seconds=1))
    worker = _worker(engine, clock)
    for _ in range(MAIL_SEND.retry.max_attempts):
        worker.drain_once()
        clock.now += timedelta(seconds=MAIL_SEND.retry.max_backoff_seconds + 1)

    assert seen == [message_id] * MAIL_SEND.retry.max_attempts
    with Session(engine) as session:  # type: ignore[arg-type]
        row = session.exec(select(OutboxMessage)).one()
        assert row.status == STATUS_DEAD_LETTERED
        assert "MailDeliveryError" in (row.last_error or "")
