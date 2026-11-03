"""The Terp Standard's runtime security cases, run against the shipped example (terp-spec 0.43.0).

A runtime-security case is a requirement an implementation proves by running it: its text in
the standard is not evidence. Each test here is the reference implementation's evidence for
one case and is named after its id. It performs the case's setup and exercise through the
shipped routes over real persistence, asserts its expected outcomes, and keeps its controls,
so a composition that refused everything could not pass.

``sessions.rotation`` and ``native.browser-refused`` run over ``main.build()`` as shipped. The
self-service cases need the accounts module, which the example does not mount, so they mount
it beside the example's own login, ``/me`` and users routes, with mail captured. Clocks are
controlled rather than waited out: the backoff's through the store it reads, and the token
lifetime's through the function that reads it.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, select

from terp.core import (
    InMemoryThrottleStore,
    InProcessJobQueue,
    JobCatalog,
    Roles,
    create_app,
    get_session,
    settings,
)
from terp.core._internal.session_guard import WriteGuardedSession
from terp.core.jobs import reset_jobs_runtime

from terp.capabilities.audit import persist_audit
from terp.capabilities.identity import RefreshTokenService, User
from terp.capabilities.mail import MAIL_SEND, CapturingMailTransport, MailSettings, configure_mail, reset_mail
from terp.capabilities.users import SelfService, UsersService, account_tokens, build_accounts_module

from app.auth import me_module, native_login_module, principal_provider
from control_plane import control_plane

_PASSWORD = "a long and unremarkable passphrase"
_COOKIE = "terp_refresh"
_LOGIN = "/api/v1/auth/login"
_REFRESH = "/api/v1/auth/refresh"
_NATIVE_LOGIN = "/api/v1/auth/native/login"
_NATIVE_REFRESH = "/api/v1/auth/native/refresh"
_ME = "/api/v1/me/"
_USERS = "/api/v1/users/"
_SIGN_UP = "/api/v1/accounts/sign-up"
_VERIFY = "/api/v1/accounts/verify"
_RESET = "/api/v1/accounts/password-reset"
_CONFIRM = "/api/v1/accounts/password-reset/confirm"
_CLOSE = "/api/v1/accounts/me/close"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _answer(response: httpx.Response) -> tuple[int, Any]:
    """What a caller is told: the status and the body, less the id every response carries."""
    try:
        body = response.json()
    except ValueError:
        return response.status_code, response.content
    if isinstance(body, dict):
        body.pop("request_id", None)
    return response.status_code, body


# --------------------------------------------------------------------------- #
# refresh-sessions and native-clients, over main.build()
# --------------------------------------------------------------------------- #


class _Carrier:
    """Sign in and refresh through one refresh carrier: the browser cookie or the body."""

    def __init__(self, app: FastAPI, *, body: bool) -> None:
        self._app = app
        self._body = body

    def sign_in(self, email: str) -> tuple[TestClient, str]:
        client = TestClient(self._app)
        response = client.post(_NATIVE_LOGIN if self._body else _LOGIN, json={"email": email, "password": _PASSWORD})
        assert response.status_code == 200, response.text
        token = response.json()["refresh_token"] if self._body else client.cookies.get(_COOKIE)
        assert token, "the sign-in issued a refresh credential"
        return client, token

    def refresh(self, token: str) -> httpx.Response:
        client = TestClient(self._app)
        if self._body:
            return client.post(_NATIVE_REFRESH, json={"refresh_token": token})
        client.cookies.set(_COOKIE, token)
        return client.post(_REFRESH)

    def successor(self, response: httpx.Response) -> str:
        return response.json()["refresh_token"] if self._body else response.cookies[_COOKIE]


@pytest.mark.parametrize("body", [False, True], ids=["cookie", "body"])
def test_case_sessions_rotation(app_db: FastAPI, make_user, monkeypatch: pytest.MonkeyPatch, body: bool) -> None:
    """``sessions.rotation``: a spent credential presented again revokes its whole sign-in."""
    make_user("rotation@example.com", _PASSWORD, Roles.EDITOR)
    carrier = _Carrier(app_db, body=body)
    _, first = carrier.sign_in("rotation@example.com")
    _, second = carrier.sign_in("rotation@example.com")
    # Past the documented concurrent-refresh grace: a replay is never a benign race here.
    monkeypatch.setattr(settings, "REFRESH_ROTATION_GRACE_SECONDS", 0)

    # Control: a live credential refreshes and its successor is accepted.
    refreshed = carrier.refresh(first)
    assert refreshed.status_code == 200, refreshed.text
    successor = carrier.successor(refreshed)
    assert TestClient(app_db).get(_ME, headers=_bearer(refreshed.json()["access_token"])).status_code == 200

    replay = carrier.refresh(first)
    assert replay.status_code == 401
    assert "access_token" not in replay.text, "the spent credential yields no access credential"
    assert carrier.refresh(successor).status_code == 401, "reuse revoked the whole family"

    # Control: the other sign-in of the same subject is a different family and keeps working.
    assert carrier.refresh(second).status_code == 200


_PROVENANCE = (
    {"Origin": "https://app.example.test"},
    {"Sec-Fetch-Site": "same-origin"},
    {"Sec-Fetch-Mode": "cors"},
    {"Sec-Fetch-Dest": "empty"},
    {"Sec-Fetch-User": "?1"},
)


def test_case_native_browser_refused(app_db: FastAPI, make_user) -> None:
    """``native.browser-refused``: a body-carrier route refuses any request with browser provenance."""
    make_user("native@example.com", _PASSWORD, Roles.EDITOR)
    carrier = _Carrier(app_db, body=True)
    _, live = carrier.sign_in("native@example.com")
    client = TestClient(app_db)
    refusals: list[httpx.Response] = []
    for headers in _PROVENANCE:
        for password in (_PASSWORD, "not the password"):
            refusals.append(
                client.post(_NATIVE_LOGIN, json={"email": "native@example.com", "password": password}, headers=headers)
            )
        for token in (live, "not-a-refresh-credential"):
            refusals.append(client.post(_NATIVE_REFRESH, json={"refresh_token": token}, headers=headers))

    browser = TestClient(app_db)
    assert browser.post(_LOGIN, json={"email": "native@example.com", "password": _PASSWORD}).status_code == 200
    assert browser.cookies.get(_COOKIE), "the browser holds its refresh cookie"
    refusals.append(browser.post(_NATIVE_LOGIN, json={"email": "native@example.com", "password": _PASSWORD}))
    refusals.append(browser.post(_NATIVE_LOGIN, json={"email": "native@example.com", "password": "not the password"}))
    refusals.append(browser.post(_NATIVE_REFRESH, json={"refresh_token": live}))
    refusals.append(browser.post(_NATIVE_REFRESH, json={"refresh_token": "not-a-refresh-credential"}))

    answers = [_answer(response) for response in refusals]
    assert answers[0][0] == 403 and answers[0][1]["code"] == "native_client_only"
    assert all(answer == answers[0] for answer in answers), (
        "one refusal for every request, whether or not the credential was valid"
    )
    assert not any("token" in key for _, body in answers for key in body)

    # Control, and the refused credential stays live: without provenance both routes answer.
    refreshed = carrier.refresh(live)
    assert refreshed.status_code == 200, refreshed.text
    assert TestClient(app_db).get(_ME, headers=_bearer(refreshed.json()["access_token"])).status_code == 200
    assert carrier.sign_in("native@example.com")[1]


# --------------------------------------------------------------------------- #
# self-service-accounts, mounted beside the example's login, /me and users
# --------------------------------------------------------------------------- #


@dataclasses.dataclass
class _Accounts:
    app: FastAPI
    mailbox: CapturingMailTransport
    clock: list[float]

    def client(self, caller: str = "10.0.0.1") -> TestClient:
        return TestClient(self.app, client=(caller, 50000))

    def links(self, address: str) -> list[str]:
        return [
            match
            for message in self.mailbox.sent
            if message["To"] == address
            for match in re.findall(r"https://\S+", message.get_content())
        ]

    def token(self, address: str) -> str:
        return urlsplit(self.links(address)[-1]).fragment.removeprefix("token=")

    def open_account(self, address: str, caller: str = "10.0.0.1") -> str:
        """Ask for an account, redeem the mailed token, and return a fresh access token."""
        client = self.client(caller)
        assert client.post(_SIGN_UP, json={"email": address, "password": _PASSWORD}).status_code == 202
        assert client.post(_VERIFY, json={"token": self.token(address)}).status_code == 201
        return self.sign_in(address).json()["access_token"]

    def sign_in(self, address: str, password: str = _PASSWORD, caller: str = "10.0.0.9") -> httpx.Response:
        return self.client(caller).post(_LOGIN, json={"email": address, "password": password})


@contextmanager
def _accounts(db_engine: Engine, **declaration: Any) -> Iterator[_Accounts]:
    """The accounts module composed with the example's own routes, its mail captured.

    The module's backoff store reads *clock*, so a test waits out a backoff by moving it.
    """
    clock = [time.time()]
    mailbox = CapturingMailTransport()
    configure_mail(MailSettings(sender="Accounts <noreply@example.test>", host="smtp.example.test"), transport=mailbox)
    module = build_accounts_module(
        SelfService(
            **{
                "reason": "members open their own accounts",
                "users": UsersService(refresh_revoker=RefreshTokenService().revoke_all_for_user),
                "throttle_store": InMemoryThrottleStore(clock=lambda: clock[0]),
                "link_base": "https://app.example.test",
                **declaration,
            }
        )
    )
    application = create_app(
        [native_login_module, me_module, module],
        title="runtime security cases",
        principal_provider=principal_provider,
        discover_capabilities=True,
        capability_names=("users",),
        control_plane=dataclasses.replace(control_plane, jobs=JobCatalog((*control_plane.jobs.jobs, MAIL_SEND))),
        audit_sink=persist_audit,
        job_queue=InProcessJobQueue(session_factory=lambda: WriteGuardedSession(db_engine)),
        require_token_revocation=True,
        throttle_store=InMemoryThrottleStore(),
    )

    def _session() -> Iterator[Session]:
        with WriteGuardedSession(db_engine) as session:
            yield session

    application.dependency_overrides[get_session] = _session
    try:
        yield _Accounts(application, mailbox, clock)
    finally:
        application.dependency_overrides.clear()
        reset_mail()
        reset_jobs_runtime()


def _users(db_engine: Engine) -> list[User]:
    with Session(db_engine) as session:
        return list(session.exec(select(User)).all())


def test_case_accounts_enumeration(db_engine: Engine, db_session: Session, make_user) -> None:
    """``accounts.enumeration``: a request about an address answers alike whatever the address."""
    make_user("active@example.com", _PASSWORD, Roles.EDITOR)
    deactivated = db_session.get(User, make_user("gone@example.com", _PASSWORD, Roles.EDITOR))
    assert deactivated is not None
    deactivated.is_active = False
    db_session.add(deactivated)
    db_session.add(User(email="provider@example.com", hashed_password=None, role=int(Roles.VIEWER)))
    db_session.commit()
    addresses = ("active@example.com", "gone@example.com", "provider@example.com", "new@example.com")

    with _accounts(db_engine) as stack:
        client = stack.client()
        sign_ups = [client.post(_SIGN_UP, json={"email": a, "password": _PASSWORD}) for a in addresses]
        resets = [client.post(_RESET, json={"email": a}) for a in addresses]

        for answers in (sign_ups, resets):
            assert {(r.status_code, r.content) for r in answers} == {(202, answers[0].content)}
        recipients = {message["To"] for message in stack.mailbox.sent}
        assert recipients <= set(addresses), "a mail reaches only the address it is about"
        # Control: the address with no account gets a verification link, the account a reset link.
        assert [urlsplit(link).path for link in stack.links("new@example.com")] == ["/account/verify"]
        assert [urlsplit(link).path for link in stack.links("active@example.com")] == ["/account/reset"]


@pytest.mark.parametrize("approval", [False, True], ids=["open", "approved"])
def test_case_accounts_proof_of_address(db_engine: Engine, approval: bool) -> None:
    """``accounts.proof-of-address``: nothing exists, and nobody signs in, until the token is redeemed."""
    with _accounts(db_engine, requires_approval=approval) as stack:
        assert stack.client().post(_SIGN_UP, json={"email": "member@example.com", "password": _PASSWORD}).status_code == 202
        before = stack.sign_in("member@example.com")
        unknown = stack.sign_in("nobody@example.com")
        assert before.status_code == 401
        assert _answer(before) == _answer(unknown), "before redemption the address is as unknown as one never seen"
        assert _users(db_engine) == []

        opened = stack.client().post(_VERIFY, json={"token": stack.token("member@example.com")})
        assert opened.status_code == 201 and opened.json() == {"active": not approval}
        after = stack.sign_in("member@example.com")
        if approval:
            assert after.status_code == 401, "an account held for approval cannot sign in"
        else:
            # Control: without an approval step the redeemed account signs in with its password.
            assert after.status_code == 200, after.text


def test_case_accounts_single_use(db_engine: Engine, make_user) -> None:
    """``accounts.single-use``: a token works once, and a reset token dies with a later revocation."""
    make_user("member@example.com", _PASSWORD, Roles.EDITOR)
    with _accounts(db_engine) as stack:
        client = stack.client()
        assert client.post(_SIGN_UP, json={"email": "new@example.com", "password": _PASSWORD}).status_code == 202
        verification = stack.token("new@example.com")
        assert client.post(_RESET, json={"email": "member@example.com"}).status_code == 202
        first = stack.token("member@example.com")
        assert client.post(_RESET, json={"email": "member@example.com"}).status_code == 202
        second = stack.token("member@example.com")
        assert first != second

        # Control: the first redemption of the verification token and of the first reset token.
        assert stack.client("10.0.1.1").post(_VERIFY, json={"token": verification}).status_code == 201
        assert stack.client("10.0.1.2").post(
            _CONFIRM, json={"token": first, "password": "the first new passphrase of this case"}
        ).status_code == 204

        again = stack.client("10.0.1.3").post(_VERIFY, json={"token": verification})
        assert (again.status_code, again.json()["code"]) == (400, "invalid_token")
        assert [u.email for u in _users(db_engine)].count("new@example.com") == 1
        again = stack.client("10.0.1.4").post(_CONFIRM, json={"token": first, "password": "the second new passphrase of this case"})
        assert (again.status_code, again.json()["code"]) == (400, "invalid_token")
        stale = stack.client("10.0.1.5").post(_CONFIRM, json={"token": second, "password": "the third new passphrase of this case"})
        assert (stale.status_code, stale.json()["code"]) == (400, "invalid_token"), (
            "the first reset revoked the sessions this token was issued under"
        )
        assert stack.sign_in("member@example.com", "the first new passphrase of this case").status_code == 200, "nothing changed"
        for refused in ("the second new passphrase of this case", "the third new passphrase of this case"):
            assert stack.sign_in("member@example.com", refused, caller="10.0.1.6").status_code == 401


def _decodings(token: str) -> list[bytes]:
    """The token as text, and as each common text encoding would decode it."""
    found = [token.encode(), unquote(token).encode()]
    for decode in (base64.urlsafe_b64decode, base64.b64decode, bytes.fromhex):
        try:
            raw = decode(token + "=" * (-len(token) % 4)) if decode is not bytes.fromhex else decode(token)
        except (binascii.Error, ValueError):
            continue
        found.append(raw)
    return found


def _altered(token: str) -> str:
    """The token with one decoded byte changed, re-encoded the way it was sent."""
    raw = bytearray(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    raw[len(raw) // 2] ^= 0x01
    return base64.urlsafe_b64encode(bytes(raw)).decode()


def test_case_accounts_sealed_tokens(db_engine: Engine, make_user) -> None:
    """``accounts.sealed-tokens``: a token cannot be altered or read, and rides only the fragment."""
    make_user("member@example.com", _PASSWORD, Roles.EDITOR)
    with _accounts(db_engine) as stack:
        client = stack.client()
        assert client.post(_SIGN_UP, json={"email": "new@example.com", "password": _PASSWORD}).status_code == 202
        assert client.post(_RESET, json={"email": "member@example.com"}).status_code == 202
        (verify_link,) = stack.links("new@example.com")
        (reset_link,) = stack.links("member@example.com")

        for link, address in ((verify_link, "new@example.com"), (reset_link, "member@example.com")):
            parts = urlsplit(link)
            token = parts.fragment.removeprefix("token=")
            assert token and parts.fragment == f"token={token}", "the token rides the fragment"
            assert parts.query == "" and token not in parts.path, "and nowhere a server sees"
            assert not any(address.encode() in decoded for decoded in _decodings(token))

        verification, reset = stack.token("new@example.com"), stack.token("member@example.com")
        refused = [
            stack.client("10.0.2.1").post(_VERIFY, json={"token": _altered(verification)}),
            stack.client("10.0.2.2").post(_CONFIRM, json={"token": _altered(reset), "password": "an entirely new and unremarkable passphrase"}),
            stack.client("10.0.2.3").post(_VERIFY, json={"token": reset}),
            stack.client("10.0.2.4").post(_CONFIRM, json={"token": verification, "password": "an entirely new and unremarkable passphrase"}),
        ]
        assert [(r.status_code, r.json()["code"]) for r in refused] == [(400, "invalid_token")] * 4
        assert [u.email for u in _users(db_engine)] == ["member@example.com"], "nothing was opened"

        # Control: each unaltered token redeems for its own purpose.
        assert stack.client("10.0.2.5").post(_VERIFY, json={"token": verification}).status_code == 201
        assert stack.client("10.0.2.6").post(
            _CONFIRM, json={"token": reset, "password": "an entirely new and unremarkable passphrase"}
        ).status_code == 204


def test_case_accounts_expiry(db_engine: Engine, make_user, monkeypatch: pytest.MonkeyPatch) -> None:
    """``accounts.expiry``: a token dies with its lifetime, which is bounded at a week and a day."""
    make_user("member@example.com", _PASSWORD, Roles.EDITOR)
    with _accounts(db_engine) as stack:
        client = stack.client()
        for address in ("late@example.com", "early@example.com"):
            assert client.post(_SIGN_UP, json={"email": address, "password": _PASSWORD}).status_code == 202
        assert client.post(_RESET, json={"email": "member@example.com"}).status_code == 202
        late, early, reset = (stack.token(a) for a in ("late@example.com", "early@example.com", "member@example.com"))

        # Control: within its lifetime a token redeems.
        assert stack.client("10.0.3.1").post(_VERIFY, json={"token": early}).status_code == 201

        # The clock the tokens are read against moves past both default lifetimes.
        past = datetime.now(UTC) + timedelta(hours=25)
        monkeypatch.setattr(account_tokens, "_utc_now", lambda: past)
        expired = [
            stack.client("10.0.3.2").post(_VERIFY, json={"token": late}),
            stack.client("10.0.3.3").post(_CONFIRM, json={"token": reset, "password": "an entirely new and unremarkable passphrase"}),
        ]
        assert [(r.status_code, r.json()["code"]) for r in expired] == [(400, "invalid_token")] * 2
        assert "late@example.com" not in {u.email for u in _users(db_engine)}
        assert stack.sign_in("member@example.com").status_code == 200, "the expired reset changed nothing"

    def declare(**ttl: timedelta) -> Callable[[], SelfService]:
        return lambda: SelfService(
            reason="members open their own accounts",
            users=UsersService(),
            throttle_store=InMemoryThrottleStore(),
            link_base="https://app.example.test",
            **ttl,
        )

    for beyond in (declare(sign_up_ttl=timedelta(days=7, seconds=1)), declare(reset_ttl=timedelta(days=1, seconds=1))):
        with pytest.raises(ValueError, match="must be positive and at most"):
            beyond()
    assert declare(sign_up_ttl=timedelta(days=7), reset_ttl=timedelta(days=1))().reset_ttl == timedelta(days=1)


def test_case_accounts_backoff(db_engine: Engine, make_user) -> None:
    """``accounts.backoff``: requests slow down alike for every address, and never lock out."""
    make_user("member@example.com", _PASSWORD, Roles.EDITOR)
    with _accounts(db_engine) as stack:
        client = stack.client()

        def until_refused(address: str) -> list[tuple[int, Any]]:
            answers: list[tuple[int, Any]] = []
            while not answers or answers[-1][0] != 429:
                answers.append(_answer(client.post(_SIGN_UP, json={"email": address, "password": _PASSWORD})))
                assert len(answers) <= 10, "the backoff engaged"
            return answers

        with_account, without = until_refused("member@example.com"), until_refused("someone@example.com")
        assert with_account == without, "the same requests receive the same answers"
        assert with_account[0][0] == 202, "control: a first request about each address is accepted"
        refusal = with_account[-1][1]
        assert refusal["code"] == "too_many_attempts"
        assert "lock" not in refusal["detail"].lower(), "a refusal says wait, never locked"

        stack.clock[0] += 3  # past the documented first backoff (two seconds)
        for address in ("member@example.com", "someone@example.com"):
            assert client.post(_SIGN_UP, json={"email": address, "password": _PASSWORD}).status_code == 202

        # Failed redemptions from one caller back off the same way, and a valid one waits it out.
        assert stack.client("10.0.4.1").post(_SIGN_UP, json={"email": "valid@example.com", "password": _PASSWORD}).status_code == 202
        guesser = stack.client("10.0.4.2")
        statuses = [guesser.post(_VERIFY, json={"token": f"guess-{n}"}).status_code for n in range(4)]
        assert statuses == [400, 400, 400, 429]
        assert guesser.post(_VERIFY, json={"token": stack.token("valid@example.com")}).status_code == 429
        stack.clock[0] += 3
        assert guesser.post(_VERIFY, json={"token": stack.token("valid@example.com")}).status_code == 201, (
            "after the backoff a request is answered on its merits"
        )


def test_case_accounts_lowest_rank(db_engine: Engine, make_user) -> None:
    """``accounts.lowest-rank``: a self-registered account holds the least authority there is."""
    make_user("admin@example.com", _PASSWORD, Roles.ADMIN)
    with _accounts(db_engine) as stack:
        member = stack.open_account("member@example.com")
        profile = stack.client().get(_ME, headers=_bearer(member))
        assert profile.status_code == 200, profile.text
        assert profile.json()["role_rank"] == min(Roles) == Roles.VIEWER
        assert stack.client().get(_USERS, headers=_bearer(member)).status_code == 403

        # Control: an administrator performs the same operation.
        admin = stack.sign_in("admin@example.com")
        assert admin.status_code == 200, admin.text
        assert stack.client().get(_USERS, headers=_bearer(admin.json()["access_token"])).status_code == 200


def test_case_accounts_close(db_engine: Engine, make_user) -> None:
    """``accounts.close``: closing takes the password again and ends every session."""
    make_user("admin@example.com", _PASSWORD, Roles.ADMIN)
    with _accounts(db_engine) as stack:
        stack.open_account("member@example.com")
        browser = stack.client("10.0.5.1")
        signed_in = browser.post(_LOGIN, json={"email": "member@example.com", "password": _PASSWORD})
        assert signed_in.status_code == 200 and browser.cookies.get(_COOKIE)
        browser_access = signed_in.json()["access_token"]
        native = stack.client("10.0.5.2").post(_NATIVE_LOGIN, json={"email": "member@example.com", "password": _PASSWORD})
        assert native.status_code == 200
        native_access, native_refresh = native.json()["access_token"], native.json()["refresh_token"]

        def sessions_live() -> list[int]:
            return [stack.client().get(_ME, headers=_bearer(t)).status_code for t in (browser_access, native_access)]

        # Control: before closing, both clients' credentials are accepted.
        assert sessions_live() == [200, 200]

        wrong = browser.post(_CLOSE, json={"password": "not the password"}, headers=_bearer(browser_access))
        assert wrong.status_code == 401
        assert sessions_live() == [200, 200], "a wrong password changes nothing"

        closed = browser.post(_CLOSE, json={"password": _PASSWORD}, headers=_bearer(browser_access))
        assert closed.status_code == 204, closed.text
        assert sessions_live() == [401, 401]
        assert browser.post(_REFRESH).status_code == 401
        assert stack.client("10.0.5.3").post(_NATIVE_REFRESH, json={"refresh_token": native_refresh}).status_code == 401
        assert stack.sign_in("member@example.com").status_code == 401

        admin = stack.sign_in("admin@example.com").json()["access_token"]
        refused = stack.client("10.0.5.4").post(_CLOSE, json={"password": _PASSWORD}, headers=_bearer(admin))
        assert (refused.status_code, refused.json()["code"]) == (409, "last_admin_protected")
        assert stack.sign_in("admin@example.com").status_code == 200
