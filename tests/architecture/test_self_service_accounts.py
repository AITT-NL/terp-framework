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
    response = client.post(_SIGN_UP, json={"email": "new@example.test"})
    assert (response.status_code, response.json()) == (202, {"status": "accepted"})
    assert _rows(engine, User) == [], "an unproven address leaves no account"
    (sent,) = mail.sent
    assert sent["To"] == "new@example.test" and sent["Subject"] == "Confirm your address"
    assert "https://app.example.test/account/verify#token=" in sent.get_content(), "the token rides the fragment"
    assert "new@example.test" not in _token(mail), "the token is sealed, not readable"
    (row,) = _rows(engine, AccountToken)
    assert (row.purpose, row.used_at) == ("sign_up", None)
    assert "user_id" not in AccountToken.model_fields, "a row names no account, whatever the address"


def test_redeeming_the_token_opens_the_account_at_the_viewer_rank_and_only_once(engine: Any, mail: CapturingMailTransport) -> None:
    client = _client(engine)
    client.post(_SIGN_UP, json={"email": "new@example.test"})
    token = _token(mail)
    opened = client.post(_VERIFY, json={"token": token, "password": _PASSWORD})
    assert (opened.status_code, opened.json()) == (201, {"active": True})
    (user,) = _rows(engine, User)
    assert (user.email, user.role, user.is_active) == ("new@example.test", int(Roles.VIEWER), True)
    assert user.hashed_password is not None and verify_password(_PASSWORD, user.hashed_password)
    assert _rows(engine, AccountToken)[0].used_at is not None
    again = client.post(_VERIFY, json={"token": token, "password": _PASSWORD})
    assert (again.status_code, again.json()["code"]) == (400, "invalid_token")


def test_whoever_asks_cannot_choose_the_password_the_account_opens_with(engine: Any, mail: CapturingMailTransport) -> None:
    client = _client(engine)
    requesters_own = "the requester's own long passphrase"
    # A sign-up has no password field; one sent anyway is not read.
    assert client.post(_SIGN_UP, json={"email": "victim@example.test", "password": requesters_own}).status_code == 202
    mailbox_choice = "the mailbox holder's own long passphrase"
    assert client.post(_VERIFY, json={"token": _token(mail), "password": mailbox_choice}).status_code == 201
    (user,) = _rows(engine, User)
    assert user.hashed_password is not None and verify_password(mailbox_choice, user.hashed_password)
    assert not verify_password(requesters_own, user.hashed_password), "the requester cannot sign in to it"


def test_an_app_that_approves_accounts_opens_them_inactive(engine: Any, mail: CapturingMailTransport) -> None:
    client = _client(engine, requires_approval=True)
    client.post(_SIGN_UP, json={"email": "held@example.test"})
    assert client.post(_VERIFY, json={"token": _token(mail), "password": _PASSWORD}).json() == {"active": False}
    assert _rows(engine, User)[0].is_active is False


def test_a_second_token_for_a_redeemed_address_is_refused(engine: Any, mail: CapturingMailTransport) -> None:
    client = _client(engine)
    for _ in range(2):
        client.post(_SIGN_UP, json={"email": "twice@example.test"})
    first, second = (_token_in(sent) for sent in mail.sent)
    assert client.post(_VERIFY, json={"token": first, "password": _PASSWORD}).status_code == 201
    assert client.post(_VERIFY, json={"token": second, "password": _PASSWORD}).status_code == 400


def test_two_spellings_of_one_mailbox_are_one_address(engine: Any, mail: CapturingMailTransport) -> None:
    _user(engine, "member@example.test")
    client = _client(engine)
    client.post(_SIGN_UP, json={"email": "Member@Example.test"})
    (notice,) = mail.sent
    assert notice["Subject"] == "You already have an account", "a case variant is the same address"
    sealed = account_tokens.seal_account_token("sign_up", {"e": "MEMBER@example.test"}, ttl=timedelta(hours=1))
    with WriteGuardedSession(engine) as session:
        account_tokens.AccountTokenService().record(session, sealed, purpose="sign_up", ttl=timedelta(hours=1))
    assert client.post(_VERIFY, json={"token": sealed, "password": _PASSWORD}).status_code == 400
    assert [u.email for u in _rows(engine, User)] == ["member@example.test"], "no second account for one mailbox"
    client.post(_RESET, json={"email": "MEMBER@example.test"})
    assert mail.sent[-1]["Subject"] == "Reset your password", "and a reset reaches the account in any case"


def test_a_sign_up_for_an_address_with_an_account_answers_the_same_way(engine: Any, mail: CapturingMailTransport) -> None:
    _user(engine, "taken@example.test")
    client = _client(engine)
    taken = client.post(_SIGN_UP, json={"email": "taken@example.test"})
    free = client.post(_SIGN_UP, json={"email": "free@example.test"})
    assert (taken.status_code, taken.json()) == (free.status_code, free.json())
    notice = mail.sent[0]
    assert notice["Subject"] == "You already have an account" and "#token=" not in notice.get_content()
    assert [row.purpose for row in _rows(engine, AccountToken)] == ["sign_up", "sign_up"], "the same write either way"


def test_a_weak_password_at_redemption_opens_nothing_and_leaves_the_token_usable(engine: Any, mail: CapturingMailTransport) -> None:
    client = _client(engine)
    client.post(_SIGN_UP, json={"email": "weak@example.test"})
    token = _token(mail)
    response = client.post(_VERIFY, json={"token": token, "password": "short"})
    assert (response.status_code, response.json()["code"]) == (422, "weak_password")
    assert _rows(engine, User) == [] and _rows(engine, AccountToken)[0].used_at is None
    assert client.post(_VERIFY, json={"token": token, "password": _PASSWORD}).status_code == 201


def test_a_token_is_checked_before_the_password_so_a_guess_is_always_a_failed_redemption(
    engine: Any, mail: CapturingMailTransport
) -> None:
    response = _client(engine).post(_VERIFY, json={"token": "a-guess", "password": "short"})
    assert (response.status_code, response.json()["code"]) == (400, "invalid_token")


@pytest.mark.parametrize("address", ["nobody", "someone@intranet", "a" * 250 + "@example.test", "two@example.test, three@example.test"])
@pytest.mark.parametrize("path", [_SIGN_UP, _RESET])
def test_a_malformed_address_is_refused_at_the_boundary_without_repeating_it(
    engine: Any, mail: CapturingMailTransport, caplog: pytest.LogCaptureFixture, path: str, address: str
) -> None:
    with caplog.at_level("DEBUG"):
        response = _client(engine).post(path, json={"email": address})
    assert response.status_code == 422, "a 422 that names the field, never a 500"
    (problem,) = response.json()["detail"]
    assert problem["loc"][-1] == "email" and address not in problem["msg"]
    assert address not in caplog.text, "the refused address is personal data and is not logged"
    assert mail.sent == [] and _rows(engine, AccountToken) == []


def test_a_token_that_is_damaged_foreign_or_unknown_is_refused(engine: Any, mail: CapturingMailTransport) -> None:
    client = _client(engine)
    reset_token = account_tokens.seal_account_token("reset", {"u": str(uuid.uuid4()), "v": 0}, ttl=timedelta(hours=1))
    unrecorded = account_tokens.seal_account_token("sign_up", {"e": "x@example.test"}, ttl=timedelta(hours=1))
    for token in ("not-a-token", reset_token, unrecorded):
        response = client.post(_VERIFY, json={"token": token, "password": _PASSWORD})
        assert (response.status_code, response.json()["code"]) == (400, "invalid_token"), token


def test_an_expired_token_is_refused(engine: Any, mail: CapturingMailTransport, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(engine)
    client.post(_SIGN_UP, json={"email": "late@example.test"})
    token = _token(mail)
    later = datetime.now(UTC) + timedelta(hours=25)
    monkeypatch.setattr(account_tokens, "_utc_now", lambda: later)
    assert client.post(_VERIFY, json={"token": token, "password": _PASSWORD}).status_code == 400
    assert _rows(engine, User) == []


def test_a_seal_past_its_expiry_is_refused_even_when_its_row_is_live(engine: Any, mail: CapturingMailTransport) -> None:
    expired = account_tokens.seal_account_token("sign_up", {"e": "seal@example.test"}, ttl=timedelta(seconds=-1))
    with WriteGuardedSession(engine) as session:
        account_tokens.AccountTokenService().record(session, expired, purpose="sign_up", ttl=timedelta(hours=1))
    assert _client(engine).post(_VERIFY, json={"token": expired, "password": _PASSWORD}).status_code == 400
    assert _rows(engine, User) == [], "the seal's own expiry refuses it, not only the row's"


def test_a_row_past_its_expiry_is_refused_even_when_the_seal_still_opens(engine: Any, mail: CapturingMailTransport) -> None:
    client = _client(engine)
    client.post(_SIGN_UP, json={"email": "stale@example.test"})
    with Session(engine) as session:
        (row,) = session.exec(select(AccountToken)).all()
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        session.add(row)
        session.commit()
    assert client.post(_VERIFY, json={"token": _token(mail), "password": _PASSWORD}).status_code == 400


# --------------------------------------------------------------------------- #
# recover
# --------------------------------------------------------------------------- #


def test_a_reset_request_answers_the_same_for_any_address_and_sends_each_one_message(
    engine: Any, mail: CapturingMailTransport
) -> None:
    _user(engine, "member@example.test")
    _user(engine, "sso@example.test", password=None)
    client = _client(engine)
    addresses = ("member@example.test", "nobody@example.test", "sso@example.test")
    answers = [client.post(_RESET, json={"email": email}) for email in addresses]
    assert {(r.status_code, str(r.json())) for r in answers} == {(202, "{'status': 'accepted'}")}
    assert [sent["To"] for sent in mail.sent] == list(addresses), "one message each, whatever the address"
    link, *notices = mail.sent
    assert "/account/reset#token=" in link.get_content()
    assert all(n["Subject"] == "No password to reset" and "#token=" not in n.get_content() for n in notices)
    rows = _rows(engine, AccountToken)
    assert [(row.purpose, row.used_at) for row in rows] == [("reset", None)] * 3, "the same row for every address"


def test_a_relay_that_is_down_fails_every_reset_request_alike(engine: Any, mail: CapturingMailTransport) -> None:
    """With the inline queue, a mail is sent inside the request; every case sends one, so an
    outage answers every address the same way, and no case is told apart by it."""
    from terp.capabilities.mail import MailDeliveryError

    def refusing(message: Any) -> None:
        raise MailDeliveryError()

    configure_mail(MailSettings(sender="Accounts <noreply@example.test>", host="smtp.example.test"), transport=refusing)
    _user(engine, "member@example.test")
    client = _client(engine)
    answers = [client.post(_RESET, json={"email": email}) for email in ("member@example.test", "nobody@example.test")]
    assert [r.status_code for r in answers] == [502, 502]
    assert answers[0].json()["code"] == answers[1].json()["code"] == "mail_delivery_failed"


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
    reset_row = next(row for row in _rows(engine, AccountToken) if row.purpose == "reset")
    assert reset_row.used_at is not None, "the reset row is spent, beside the epoch it moved"
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
    decoy = _token(mail) if "#token=" in mail.sent[-1].get_content() else None
    assert decoy is None, "an address with no account gets no token"
    forged = account_tokens.seal_account_token("reset", {"u": "not-a-uuid", "v": 0}, ttl=timedelta(hours=1))
    with WriteGuardedSession(engine) as session:
        account_tokens.AccountTokenService().record(session, forged, purpose="reset", ttl=timedelta(hours=1))
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
    with WriteGuardedSession(engine) as session:
        RefreshTokenService().issue(session, user_id)
    client = _client(engine, principal=Principal(id=user_id, role=Roles.VIEWER), deletion=AccountDeletion.REMOVE)
    assert client.post(_CLOSE, json={"password": _PASSWORD}).status_code == 204
    assert _rows(engine, User) == []
    assert all(row.revoked_at is not None for row in _rows(engine, RefreshToken)), "no family is left live"


def test_a_removal_a_reference_refuses_closes_the_account_by_scrubbing_it(
    mail: CapturingMailTransport, caplog: pytest.LogCaptureFixture
) -> None:
    """One write either way: the refused delete changes nothing, and the scrub then closes it."""
    import sqlalchemy as sa

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sa.event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE example_reference (id INTEGER PRIMARY KEY, user_id CHAR(32) "
            "REFERENCES identity_user (id) ON DELETE RESTRICT)"
        )
    user_id = _user(engine, "leaving@example.test")
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO example_reference (id, user_id) VALUES (1, ?)", (user_id.hex,))
    client = _client(engine, principal=Principal(id=user_id, role=Roles.VIEWER), deletion=AccountDeletion.REMOVE)
    with caplog.at_level("WARNING", logger="terp.capabilities.users.service"):
        assert client.post(_CLOSE, json={"password": _PASSWORD}).status_code == 204
    (user,) = _rows(engine, User)
    assert (user.is_active, user.hashed_password, user.email) == (False, None, f"closed-{user_id.hex}@closed.invalid")
    assert "scrubbed instead" in caplog.text and "leaving@example.test" not in caplog.text
    engine.dispose()


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
    guesses = [client.post(_VERIFY, json={"token": f"guess-{n}", "password": _PASSWORD}).status_code for n in range(8)]
    assert guesses[0] == 400 and 429 in guesses, guesses
    closing = _client(engine, principal=Principal(id=_user(engine, "c@example.test"), role=Roles.VIEWER))
    attempts = [closing.post(_CLOSE, json={"password": "wrong"}).status_code for _ in range(8)]
    assert attempts[0] == 401 and 429 in attempts, attempts


def test_bad_tokens_from_many_callers_never_hold_up_an_honest_one(engine: Any, mail: CapturingMailTransport) -> None:
    """The redemption counter is each caller's own (ADR 0147): no state is shared to spend."""
    client = _client(engine)
    client.post(_SIGN_UP, json={"email": "honest@example.test"})
    token = _token(mail)
    for caller in range(60):
        guesser = TestClient(client.app, client=(f"10.1.{caller // 250}.{caller % 250}", 50000))
        assert guesser.post(_VERIFY, json={"token": f"guess-{caller}", "password": _PASSWORD}).status_code == 400
    honest = TestClient(client.app, client=("10.9.9.9", 50000))
    assert honest.post(_VERIFY, json={"token": token, "password": _PASSWORD}).status_code == 201


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
    messages = AccountMessages(sign_up_subject="Bevestig je adres", sign_up_text="Open {link}; geldig: {lifetime}.")
    client = _client(engine, messages=messages, sign_up_ttl=timedelta(minutes=30))
    client.post(_SIGN_UP, json={"email": "nl@example.test"})
    (sent,) = mail.sent
    assert sent["Subject"] == "Bevestig je adres" and "geldig: 30 minutes." in sent.get_content()


@pytest.mark.parametrize(
    ("ttl", "words"),
    [
        (timedelta(hours=24), "24 hours"),
        (timedelta(hours=1), "1 hour"),
        (timedelta(minutes=90), "90 minutes"),
        (timedelta(minutes=1), "1 minute"),
        (timedelta(seconds=59), "less than a minute"),
    ],
)
def test_a_mail_never_promises_more_time_than_the_link_has(ttl: timedelta, words: str) -> None:
    from terp.capabilities.users.accounts import _lifetime

    assert _lifetime(ttl) == words


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
