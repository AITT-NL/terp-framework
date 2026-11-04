"""Self-service accounts (ADR 0196): open, prove, recover and close, with the failures designed out.

Each guarantee the ADR lists is held here against a real composition: the users and identity
services on SQLite, the inline job queue delivering mail to a capturing transport, and the
routes mounted from ``build_accounts_module``. The negative cases are the point: an address
that has an account is indistinguishable from one that has none, a token works once and
expires, a closed account keeps no session, and a half-configured module is refused.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from terp.core import (
    InMemoryThrottleStore,
    InProcessJobQueue,
    JobCatalog,
    Principal,
    Roles,
    get_principal,
    mark_shared_throttle_store,
    settings,
)
from terp.core._internal.session_guard import WriteGuardedSession
from terp.core.app import register_error_handlers
from terp.core.db import get_session
from terp.core.jobs import configure_jobs, reset_jobs_runtime

from terp.capabilities.auth import hash_password, verify_password
from terp.capabilities.identity import AccountToken, RefreshToken, RefreshTokenService, User
from terp.capabilities.mail import MAIL_SEND, CapturingMailTransport, MailSettings, configure_mail, reset_mail
from terp.capabilities.users import (
    USERS_OPERATIONS,
    AccountDeletion,
    AccountMessages,
    SelfService,
    UsersService,
    build_accounts_module,
)
from terp.capabilities.users import account_tokens

_PASSWORD = "a long and unremarkable passphrase"
_SIGN_UP = "/api/v1/accounts/sign-up"
_VERIFY = "/api/v1/accounts/verify"
_RESET = "/api/v1/accounts/password-reset"
_CONFIRM = "/api/v1/accounts/password-reset/confirm"
_CLOSE = "/api/v1/accounts/me/close"


@pytest.fixture
def engine() -> Iterator[Any]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def mail(engine: Any) -> Iterator[CapturingMailTransport]:
    """The relay and the inline queue: a sent mail lands in the transport during the request."""
    captured = CapturingMailTransport()
    configure_jobs(
        JobCatalog([MAIL_SEND]), queue=InProcessJobQueue(session_factory=lambda: WriteGuardedSession(engine))
    )
    configure_mail(MailSettings(sender="Accounts <noreply@example.test>", host="smtp.example.test"), transport=captured)
    yield captured
    reset_mail()
    reset_jobs_runtime()


def _declaration(**overrides: Any) -> SelfService:
    values: dict[str, Any] = {
        "reason": "members open their own accounts from the mobile app",
        "users": UsersService(refresh_revoker=RefreshTokenService().revoke_all_for_user),
        "throttle_store": InMemoryThrottleStore(),
        "link_base": "https://app.example.test",
    }
    values.update(overrides)
    return SelfService(**values)


def _client(engine: Any, *, principal: Principal | None = None, **overrides: Any) -> TestClient:
    module = build_accounts_module(_declaration(**overrides))
    app = FastAPI()
    register_error_handlers(app)
    assert module.router is not None
    app.include_router(module.router, prefix="/api/v1/accounts")

    def _session() -> Iterator[Session]:
        with WriteGuardedSession(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_principal] = lambda: principal
    return TestClient(app, raise_server_exceptions=False)


def _rows(engine: Any, model: type[Any]) -> list[Any]:
    with Session(engine) as session:
        return list(session.exec(select(model)).all())


def _user(engine: Any, email: str, *, password: str | None = _PASSWORD, role: Roles = Roles.VIEWER) -> uuid.UUID:
    with Session(engine) as session:
        user = User(email=email, hashed_password=hash_password(password) if password else None, role=int(role))
        session.add(user)
        session.commit()
        return user.id


def _token_in(message: Any) -> str:
    match = re.search(r"#token=(\S+)", message.get_content())
    assert match is not None, message.get_content()
    return match.group(1)


def _token(mail: CapturingMailTransport) -> str:
    return _token_in(mail.sent[-1])


# --------------------------------------------------------------------------- #
# open and prove
# --------------------------------------------------------------------------- #


def test_a_sign_up_mails_a_token_and_creates_nothing_until_it_is_redeemed(engine: Any, mail: CapturingMailTransport) -> None:
    client = _client(engine)
    response = client.post(_SIGN_UP, json={"email": "new@example.test", "password": _PASSWORD})
    assert (response.status_code, response.json()) == (202, {"status": "accepted"})
    assert _rows(engine, User) == [], "an unproven address leaves no account"
    (sent,) = mail.sent
    assert sent["To"] == "new@example.test" and sent["Subject"] == "Confirm your address"
    assert "https://app.example.test/account/verify#token=" in sent.get_content(), "the token rides the fragment"
    assert "new@example.test" not in _token(mail), "the token is sealed, not readable"
    (row,) = _rows(engine, AccountToken)
    assert (row.purpose, row.user_id, row.used_at) == ("sign_up", None, None)


def test_redeeming_the_token_opens_the_account_at_the_viewer_rank_and_only_once(engine: Any, mail: CapturingMailTransport) -> None:
    client = _client(engine)
    client.post(_SIGN_UP, json={"email": "new@example.test", "password": _PASSWORD})
    token = _token(mail)
    opened = client.post(_VERIFY, json={"token": token})
    assert (opened.status_code, opened.json()) == (201, {"active": True})
    (user,) = _rows(engine, User)
    assert (user.email, user.role, user.is_active) == ("new@example.test", int(Roles.VIEWER), True)
    assert user.hashed_password is not None and verify_password(_PASSWORD, user.hashed_password)
    assert _rows(engine, AccountToken)[0].used_at is not None
    again = client.post(_VERIFY, json={"token": token})
    assert (again.status_code, again.json()["code"]) == (400, "invalid_token")


def test_an_app_that_approves_accounts_opens_them_inactive(engine: Any, mail: CapturingMailTransport) -> None:
    client = _client(engine, requires_approval=True)
    client.post(_SIGN_UP, json={"email": "held@example.test", "password": _PASSWORD})
    assert client.post(_VERIFY, json={"token": _token(mail)}).json() == {"active": False}
    assert _rows(engine, User)[0].is_active is False


def test_a_second_token_for_a_redeemed_address_is_refused(engine: Any, mail: CapturingMailTransport) -> None:
    client = _client(engine)
    for _ in range(2):
        client.post(_SIGN_UP, json={"email": "twice@example.test", "password": _PASSWORD})
    first, second = (_token_in(sent) for sent in mail.sent)
    assert client.post(_VERIFY, json={"token": first}).status_code == 201
    assert client.post(_VERIFY, json={"token": second}).status_code == 400


def test_a_sign_up_for_an_address_with_an_account_answers_the_same_way(engine: Any, mail: CapturingMailTransport) -> None:
    _user(engine, "taken@example.test")
    client = _client(engine)
    taken = client.post(_SIGN_UP, json={"email": "taken@example.test", "password": _PASSWORD})
    free = client.post(_SIGN_UP, json={"email": "free@example.test", "password": _PASSWORD})
    assert (taken.status_code, taken.json()) == (free.status_code, free.json())
    notice = mail.sent[0]
    assert notice["Subject"] == "You already have an account" and "#token=" not in notice.get_content()
    assert [row.purpose for row in _rows(engine, AccountToken)] == ["sign_up", "sign_up"], "the same write either way"


def test_a_weak_password_is_refused_before_anything_is_written_or_sent(engine: Any, mail: CapturingMailTransport) -> None:
    response = _client(engine).post(_SIGN_UP, json={"email": "weak@example.test", "password": "short"})
    assert (response.status_code, response.json()["code"]) == (422, "weak_password")
    assert mail.sent == [] and _rows(engine, AccountToken) == []


def test_a_token_that_is_damaged_foreign_or_unknown_is_refused(engine: Any, mail: CapturingMailTransport) -> None:
    client = _client(engine)
    reset_token = account_tokens.seal_account_token("reset", {"u": str(uuid.uuid4()), "v": 0}, ttl=timedelta(hours=1))
    unrecorded = account_tokens.seal_account_token("sign_up", {"e": "x@example.test", "h": "h"}, ttl=timedelta(hours=1))
    for token in ("not-a-token", reset_token, unrecorded):
        response = client.post(_VERIFY, json={"token": token})
        assert (response.status_code, response.json()["code"]) == (400, "invalid_token"), token


def test_an_expired_token_is_refused(engine: Any, mail: CapturingMailTransport, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(engine)
    client.post(_SIGN_UP, json={"email": "late@example.test", "password": _PASSWORD})
    token = _token(mail)
    later = datetime.now(UTC) + timedelta(hours=25)
    monkeypatch.setattr(account_tokens, "_utc_now", lambda: later)
    assert client.post(_VERIFY, json={"token": token}).status_code == 400
    assert _rows(engine, User) == []


def test_a_row_past_its_expiry_is_refused_even_when_the_seal_still_opens(engine: Any, mail: CapturingMailTransport) -> None:
    client = _client(engine)
    client.post(_SIGN_UP, json={"email": "stale@example.test", "password": _PASSWORD})
    with Session(engine) as session:
        (row,) = session.exec(select(AccountToken)).all()
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        session.add(row)
        session.commit()
    assert client.post(_VERIFY, json={"token": _token(mail)}).status_code == 400


# --------------------------------------------------------------------------- #
# recover
# --------------------------------------------------------------------------- #


def test_a_reset_request_answers_the_same_for_any_address_and_mails_only_an_account(
    engine: Any, mail: CapturingMailTransport
) -> None:
    _user(engine, "member@example.test")
    _user(engine, "sso@example.test", password=None)
    client = _client(engine)
    answers = {email: client.post(_RESET, json={"email": email}) for email in ("member@example.test", "nobody@example.test", "sso@example.test")}
    assert {(r.status_code, str(r.json())) for r in answers.values()} == {(202, "{'status': 'accepted'}")}
    (sent,) = mail.sent
    assert sent["To"] == "member@example.test" and "/account/reset#token=" in sent.get_content()
    rows = _rows(engine, AccountToken)
    assert [row.purpose for row in rows] == ["reset"] * 3, "the same write for every address"
    assert sum(row.user_id is not None for row in rows) == 1


def test_a_reset_token_sets_the_password_once_and_ends_every_session(engine: Any, mail: CapturingMailTransport) -> None:
    user_id = _user(engine, "member@example.test")
    with WriteGuardedSession(engine) as session:
        RefreshTokenService().issue(session, user_id)
    client = _client(engine)
    client.post(_RESET, json={"email": "member@example.test"})
    token = _token(mail)
    new = "another long and unremarkable passphrase"
    assert client.post(_CONFIRM, json={"token": token, "password": new}).status_code == 204
    (user,) = _rows(engine, User)
    assert user.hashed_password is not None and verify_password(new, user.hashed_password)
    assert user.token_version == 1
    assert all(row.revoked_at is not None for row in _rows(engine, RefreshToken)), "refresh families revoked"
    again = client.post(_CONFIRM, json={"token": token, "password": "yet another long passphrase here"})
    assert (again.status_code, again.json()["code"]) == (400, "invalid_token")


def test_a_reset_token_dies_with_any_revocation_after_it_was_mailed(engine: Any, mail: CapturingMailTransport) -> None:
    user_id = _user(engine, "member@example.test")
    client = _client(engine)
    client.post(_RESET, json={"email": "member@example.test"})
    with WriteGuardedSession(engine) as session:
        UsersService().revoke_sessions(session, user_id)
    assert client.post(_CONFIRM, json={"token": _token(mail), "password": "a new and long passphrase"}).status_code == 400


def test_a_reset_token_for_no_account_or_a_forged_subject_is_refused(engine: Any, mail: CapturingMailTransport) -> None:
    client = _client(engine)
    client.post(_RESET, json={"email": "nobody@example.test"})
    with Session(engine) as session:
        (decoy,) = session.exec(select(AccountToken)).all()
    forged = account_tokens.seal_account_token("reset", {"u": "not-a-uuid", "v": 0}, ttl=timedelta(hours=1))
    with WriteGuardedSession(engine) as session:
        account_tokens.AccountTokenService().record(session, forged, purpose="reset", ttl=timedelta(hours=1))
    assert decoy.user_id is None
    for token in (forged, "not-a-token"):
        assert client.post(_CONFIRM, json={"token": token, "password": "a new and long passphrase"}).status_code == 400


def test_a_weak_new_password_leaves_the_reset_token_usable(engine: Any, mail: CapturingMailTransport) -> None:
    _user(engine, "member@example.test")
    client = _client(engine)
    client.post(_RESET, json={"email": "member@example.test"})
    token = _token(mail)
    assert client.post(_CONFIRM, json={"token": token, "password": "short"}).status_code == 422
    assert client.post(_CONFIRM, json={"token": token, "password": "a new and long passphrase"}).status_code == 204


# --------------------------------------------------------------------------- #
# close
# --------------------------------------------------------------------------- #


def test_closing_an_account_takes_the_password_scrubs_it_and_ends_every_session(engine: Any, mail: CapturingMailTransport) -> None:
    user_id = _user(engine, "leaving@example.test")
    with WriteGuardedSession(engine) as session:
        RefreshTokenService().issue(session, user_id)
    client = _client(engine, principal=Principal(id=user_id, role=Roles.VIEWER))
    assert client.post(_CLOSE, json={"password": "not the password"}).status_code == 401
    assert client.post(_CLOSE, json={"password": _PASSWORD}).status_code == 204
    (user,) = _rows(engine, User)
    assert (user.is_active, user.hashed_password, user.token_version) == (False, None, 1)
    assert user.email == f"closed-{user_id.hex}@closed.invalid", "the person's address is gone"
    assert all(row.revoked_at is not None for row in _rows(engine, RefreshToken))


def test_an_app_that_removes_accounts_deletes_the_row(engine: Any, mail: CapturingMailTransport) -> None:
    user_id = _user(engine, "leaving@example.test")
    client = _client(engine, principal=Principal(id=user_id, role=Roles.VIEWER), deletion=AccountDeletion.REMOVE)
    assert client.post(_CLOSE, json={"password": _PASSWORD}).status_code == 204
    assert _rows(engine, User) == []


def test_closing_is_refused_without_a_session_a_password_or_an_active_account(engine: Any, mail: CapturingMailTransport) -> None:
    assert _client(engine).post(_CLOSE, json={"password": _PASSWORD}).status_code == 401
    sso = _user(engine, "sso@example.test", password=None)
    response = _client(engine, principal=Principal(id=sso, role=Roles.VIEWER)).post(_CLOSE, json={"password": "x"})
    assert (response.status_code, response.json()["code"]) == (409, "account_signs_in_elsewhere")
    ghost = _client(engine, principal=Principal(id=uuid.uuid4(), role=Roles.VIEWER))
    assert ghost.post(_CLOSE, json={"password": _PASSWORD}).status_code == 401


def test_the_last_administrator_cannot_close_their_own_account(engine: Any, mail: CapturingMailTransport) -> None:
    admin = _user(engine, "admin@example.test", role=Roles.ADMIN)
    response = _client(engine, principal=Principal(id=admin, role=Roles.ADMIN)).post(_CLOSE, json={"password": _PASSWORD})
    assert (response.status_code, response.json()["code"]) == (409, "last_admin_protected")


# --------------------------------------------------------------------------- #
# back off, never lock out
# --------------------------------------------------------------------------- #


def test_repeated_requests_and_failed_redemptions_back_off(engine: Any, mail: CapturingMailTransport) -> None:
    client = _client(engine)
    statuses = [client.post(_RESET, json={"email": "flood@example.test"}).status_code for _ in range(8)]
    assert 429 in statuses and statuses[0] == 202, statuses
    guesses = [client.post(_VERIFY, json={"token": f"guess-{n}"}).status_code for n in range(8)]
    assert guesses[0] == 400 and 429 in guesses, guesses
    closing = _client(engine, principal=Principal(id=_user(engine, "c@example.test"), role=Roles.VIEWER))
    attempts = [closing.post(_CLOSE, json={"password": "wrong"}).status_code for _ in range(8)]
    assert attempts[0] == 401 and 429 in attempts, attempts


# --------------------------------------------------------------------------- #
# the declaration and the module
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"reason": "  "}, "requires a non-empty justification"),
        ({"link_base": "ftp://app.example.test"}, "absolute http"),
        ({"link_base": "https://app.example.test/?next=1"}, "absolute http"),
        ({"verify_path": "account/verify"}, "verify_path must start"),
        ({"reset_ttl": timedelta(days=2)}, "reset_ttl must be positive"),
        ({"sign_up_ttl": timedelta(0)}, "sign_up_ttl must be positive"),
    ],
)
def test_a_declaration_that_cannot_be_honoured_is_refused(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _declaration(**overrides)


def test_the_module_is_refused_without_a_relay(mail: CapturingMailTransport) -> None:
    reset_mail()
    with pytest.raises(ValueError, match="call configure_mail"):
        build_accounts_module(_declaration())
    configure_mail(MailSettings(sender="a@example.test", host="smtp.example.test"), transport=mail)
    module = build_accounts_module(_declaration())
    assert tuple(module.jobs) == (MAIL_SEND,), "a boot whose catalog lacks MAIL_SEND is refused"
    assert {path for path, _ in module.rate_limit} == {
        "/sign-up", "/verify", "/password-reset", "/password-reset/confirm", "/me/close"
    }


def test_a_store_each_worker_keeps_is_accepted_and_said_out_loud(
    mail: CapturingMailTransport, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # The platform's own stance (ADR 0036): a per-instance store is correct for one
    # instance, so refusing it would break something that is not wrong. Production too.
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with caplog.at_level("WARNING", logger="terp.capabilities.users.accounts"):
        build_accounts_module(_declaration())
    assert "PER WORKER" in caplog.text
    caplog.clear()
    with caplog.at_level("WARNING", logger="terp.capabilities.users.accounts"):
        build_accounts_module(_declaration(throttle_store=mark_shared_throttle_store(InMemoryThrottleStore())))
    assert "PER WORKER" not in caplog.text, "a shared store is the answer, so nothing is said"


def test_plaintext_links_are_refused_in_production_and_said_out_loud_elsewhere(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="terp.capabilities.users.self_service"):
        plaintext = _declaration(link_base="http://app.example.test")
    assert "REFUSED" in caplog.text
    assert plaintext.production_problems() == [
        "SelfService.link_base must be https in production, got 'http://app.example.test' (a "
        "page loaded over plaintext can be rewritten to read the token from the link)"
    ], "the verdict is answerable off the production host"
    assert _declaration().production_problems() == []
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(ValueError, match="must be https in production"):
        _declaration(link_base="http://app.example.test")
    assert _declaration().link_base == "https://app.example.test"


def test_every_route_declares_a_published_operation_and_none_is_discovered(mail: CapturingMailTransport) -> None:
    from terp.capabilities.users import module as discovered
    from terp.core.routing import declared_operation

    module = build_accounts_module(_declaration())
    assert module.router is not None
    declared = {declared_operation(route.endpoint) for route in module.router.routes if isinstance(route, APIRoute)}
    assert None not in declared and len(declared) == 5
    assert declared <= set(USERS_OPERATIONS), "an app that splats USERS_OPERATIONS can boot STRICT"
    assert discovered.router is not None
    assert not [route for route in discovered.router.routes if "sign-up" in getattr(route, "path", "")], (
        "the auto-discovered users module never carries the self-service routes"
    )


def test_an_app_writes_its_own_mail_copy(engine: Any, mail: CapturingMailTransport) -> None:
    messages = AccountMessages(sign_up_subject="Bevestig je adres", sign_up_text="Open {link} binnen {hours} uur.")
    client = _client(engine, messages=messages, sign_up_ttl=timedelta(minutes=30))
    client.post(_SIGN_UP, json={"email": "nl@example.test", "password": _PASSWORD})
    (sent,) = mail.sent
    assert sent["Subject"] == "Bevestig je adres" and "binnen 1 uur" in sent.get_content()


# --------------------------------------------------------------------------- #
# the token itself
# --------------------------------------------------------------------------- #


def test_a_token_opens_only_for_its_own_purpose_and_only_while_it_lives() -> None:
    token = account_tokens.seal_account_token("sign_up", {"e": "a@example.test"}, ttl=timedelta(hours=1))
    opened = account_tokens.open_account_token("sign_up", token)
    assert opened is not None and opened["e"] == "a@example.test"
    assert account_tokens.open_account_token("reset", token) is None
    domain = account_tokens._DOMAIN
    for body in ("not json", "[1]", '{"p": "sign_up"}', '{"p": "sign_up", "x": "soon"}'):
        assert account_tokens.open_account_token("sign_up", domain.seal(body)) is None, body


def test_a_token_stored_before_a_key_rotation_is_still_found(monkeypatch: pytest.MonkeyPatch) -> None:
    before = account_tokens.account_token_digests("t")[0]
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", [settings.SECRET_KEY])
    monkeypatch.setattr(settings, "SECRET_KEY", "a-different-and-sufficiently-long-secret-key-value")
    assert before in account_tokens.account_token_digests("t")[1:]
