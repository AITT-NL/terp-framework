"""The Terp Standard's runtime security cases, run against the shipped example (terp-spec 0.43.0).

A runtime-security case is a requirement an implementation proves by running it: its text in
the standard is not evidence. Each test here is the reference implementation's evidence for
one case and is named after its id. It performs the case's setup and exercise through the
shipped routes over real persistence, asserts its expected outcomes, and keeps its controls,
so a composition that refused everything could not pass.

``sessions.rotation`` and ``native.browser-refused`` run over ``main.build()`` as shipped. The
self-service cases need the accounts module, which the example does not mount, so they mount
it beside the example's own sign-in, ``/me`` and notes routes, with mail captured. Clocks are
controlled rather than waited out: the backoff's through the store it reads, and the token
lifetime's through the function that reads it.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import json
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
from starlette.middleware import Middleware

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

from terp.capabilities.access import enforce_permission, resolve_module_rank
from terp.capabilities.audit import persist_audit
from terp.capabilities.auth import tenant_from_bearer
from terp.capabilities.eventbus import dispatch_in_process
from terp.capabilities.identity import RefreshTokenService, User
from terp.capabilities.mail import (
    MAIL_SEND,
    CapturingMailTransport,
    MailDeliveryError,
    MailSettings,
    configure_mail,
    reset_mail,
)
from terp.capabilities.tenancy import TenantMiddleware
from terp.capabilities.users import SelfService, UsersService, account_tokens, build_accounts_module

from app.auth import me_module, native_login_module, principal_provider
from app.modules.notes.module import module as notes_module
from control_plane import control_plane

_PASSWORD = "a long and unremarkable passphrase"
_COOKIE = "terp_refresh"
_LOGIN = "/api/v1/auth/login"
_REFRESH = "/api/v1/auth/refresh"
_NATIVE_LOGIN = "/api/v1/auth/native/login"
_NATIVE_REFRESH = "/api/v1/auth/native/refresh"
_ME = "/api/v1/me/"
_NOTES = "/api/v1/notes/"
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


def _said(response: httpx.Response) -> tuple[int, Any, list[tuple[str, str]]]:
    """Everything a caller is told, headers included, less the request id every response carries."""
    headers = sorted((name, value) for name, value in response.headers.items() if name != "x-request-id")
    return (*_answer(response), headers)


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
    """``sessions.rotation``: past the grace, a spent refresh credential revokes its whole sign-in."""
    make_user("rotation@example.com", _PASSWORD, Roles.EDITOR)
    carrier = _Carrier(app_db, body=body)
    _, first = carrier.sign_in("rotation@example.com")
    _, second = carrier.sign_in("rotation@example.com")
    # Past the documented concurrent-refresh grace: a replay is never a benign race here.
    monkeypatch.setattr(settings, "REFRESH_ROTATION_GRACE_SECONDS", 0)

    # Control: before the reuse, the second sign-in refreshes, and the successor it was
    # issued refreshes in turn.
    refreshed = carrier.refresh(second)
    assert refreshed.status_code == 200, refreshed.text
    again = carrier.refresh(carrier.successor(refreshed))
    assert again.status_code == 200, again.text
    second = carrier.successor(again)
    assert TestClient(app_db).get(_ME, headers=_bearer(again.json()["access_token"])).status_code == 200

    rotated = carrier.refresh(first)
    assert rotated.status_code == 200, rotated.text
    successor = carrier.successor(rotated)
    replay = carrier.refresh(first)
    assert replay.status_code == 401
    assert "access_token" not in replay.text, "the spent credential yields no access credential"
    assert carrier.refresh(successor).status_code == 401, "reuse revoked every refresh credential of that sign-in"

    # Control: the second sign-in's latest refresh credential keeps working.
    assert carrier.refresh(second).status_code == 200


_PROVENANCE = (
    {"Origin": "https://app.example.test"},
    {"Sec-Fetch-Site": "same-origin"},
    {"Sec-Fetch-Mode": "cors"},
    {"Sec-Fetch-Dest": "empty"},
    {"Sec-Fetch-User": "?1"},
    {"Sec-Fetch-Storage-Access": "active"},
)
#: Credentials of a form the routes do not accept: a password longer than any the sign-in
#: reads, and an empty refresh token or one longer than any the routes issue.
_MALFORMED_PASSWORD = "p" * 257
_MALFORMED_TOKENS = ("", "t" * 129)


def test_case_native_browser_refused(app_db: FastAPI, make_user) -> None:
    """``native.browser-refused``: a body-carrier route refuses any request with browser provenance."""
    make_user("native@example.com", _PASSWORD, Roles.EDITOR)
    carrier = _Carrier(app_db, body=True)
    _, live = carrier.sign_in("native@example.com")
    passwords = (_PASSWORD, "not the password", _MALFORMED_PASSWORD)
    tokens = (live, "not-a-refresh-credential", *_MALFORMED_TOKENS)

    def attempts(client: TestClient, headers: dict[str, str] | None = None) -> list[httpx.Response]:
        return [
            *(
                client.post(_NATIVE_LOGIN, json={"email": "native@example.com", "password": p}, headers=headers)
                for p in passwords
            ),
            *(client.post(_NATIVE_REFRESH, json={"refresh_token": t}, headers=headers) for t in tokens),
        ]

    refusals = [response for headers in _PROVENANCE for response in attempts(TestClient(app_db), headers)]
    browser = TestClient(app_db)
    assert browser.post(_LOGIN, json={"email": "native@example.com", "password": _PASSWORD}).status_code == 200
    assert browser.cookies.get(_COOKIE), "the browser holds its refresh cookie"
    refusals += attempts(browser)

    answers = [_answer(response) for response in refusals]
    assert answers[0][0] == 403 and answers[0][1]["code"] == "native_client_only"
    assert all(answer == answers[0] for answer in answers), (
        "one refusal for every request, whether the credential was valid, invalid or malformed"
    )
    assert not any("token" in key for _, body in answers for key in body)

    # Control: without provenance, a credential of a form the routes do not accept is
    # refused as malformed, so the refusals above came before the form was checked.
    plain = TestClient(app_db)
    malformed = [
        plain.post(_NATIVE_LOGIN, json={"email": "native@example.com", "password": _MALFORMED_PASSWORD}),
        *(plain.post(_NATIVE_REFRESH, json={"refresh_token": t}) for t in _MALFORMED_TOKENS),
    ]
    assert [response.status_code for response in malformed] == [422] * 3
    # Control, and the refused credential stays live: without provenance both routes answer.
    refreshed = carrier.refresh(live)
    assert refreshed.status_code == 200, refreshed.text
    assert TestClient(app_db).get(_ME, headers=_bearer(refreshed.json()["access_token"])).status_code == 200
    assert carrier.sign_in("native@example.com")[1]


# --------------------------------------------------------------------------- #
# self-service-accounts, mounted beside the example's sign-in, /me and notes
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
        """Ask for an account, redeem the mailed token with a password, return an access token."""
        client = self.client(caller)
        assert client.post(_SIGN_UP, json={"email": address}).status_code == 202
        assert client.post(_VERIFY, json={"token": self.token(address), "password": _PASSWORD}).status_code == 201
        return self.sign_in(address).json()["access_token"]

    def sign_in(self, address: str, password: str = _PASSWORD, caller: str = "10.0.0.9") -> httpx.Response:
        return self.client(caller).post(_LOGIN, json={"email": address, "password": password})


def _relay_down(message: Any) -> None:
    raise MailDeliveryError()


@contextmanager
def _accounts(db_engine: Engine, *, transport: Any = None, **declaration: Any) -> Iterator[_Accounts]:
    """The accounts module composed with the example's own routes, its mail captured.

    The module's backoff store reads *clock*, so a test waits out a backoff by moving it.
    *transport* replaces the capture, for a relay that is down.
    """
    clock = [time.time()]
    mailbox = CapturingMailTransport()
    configure_mail(
        MailSettings(sender="Accounts <noreply@example.test>", host="smtp.example.test"),
        transport=transport or mailbox,
    )
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
    # The notes module as main.build() composes it, so an operation the next authority up
    # may perform is the example's own: writing a note needs an editor.
    application = create_app(
        [native_login_module, me_module, notes_module, module],
        title="runtime security cases",
        principal_provider=principal_provider,
        discover_capabilities=True,
        capability_names=("access", "users"),
        control_plane=dataclasses.replace(control_plane, jobs=JobCatalog((*control_plane.jobs.jobs, MAIL_SEND))),
        audit_sink=persist_audit,
        event_dispatcher=dispatch_in_process,
        job_queue=InProcessJobQueue(session_factory=lambda: WriteGuardedSession(db_engine)),
        permission_enforcer=enforce_permission,
        module_rank_resolver=resolve_module_rank,
        middleware=[Middleware(TenantMiddleware, resolve_tenant=tenant_from_bearer)],
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
    """``accounts.enumeration``: a request about an address answers alike, and does the same
    work, whatever the address."""
    make_user("active@example.com", _PASSWORD, Roles.EDITOR)
    deactivated = db_session.get(User, make_user("gone@example.com", _PASSWORD, Roles.EDITOR))
    assert deactivated is not None
    deactivated.is_active = False
    db_session.add(deactivated)
    db_session.add(User(email="provider@example.com", hashed_password=None, role=int(Roles.VIEWER)))
    db_session.commit()
    addresses = ("active@example.com", "gone@example.com", "provider@example.com", "new@example.com")

    with _accounts(db_engine) as stack:
        # Each address from a caller of its own, none slowed, so no per-caller value differs.
        callers = {address: stack.client(f"10.0.6.{n}") for n, address in enumerate(addresses, start=1)}
        sign_ups = [callers[address].post(_SIGN_UP, json={"email": address}) for address in addresses]
        sent_by_sign_up = [message["To"] for message in stack.mailbox.sent]
        resets = [callers[address].post(_RESET, json={"email": address}) for address in addresses]
        sent_by_reset = [message["To"] for message in stack.mailbox.sent][len(sent_by_sign_up) :]

        for answers in (sign_ups, resets):
            assert answers[0].status_code == 202
            assert all(_said(response) == _said(answers[0]) for response in answers), (
                "the same status, body and headers for every address"
            )
        assert sorted(sent_by_sign_up) == sorted(addresses), "each sign-up sends its address exactly one message"
        assert sorted(sent_by_reset) == sorted(addresses), "and so does each reset"
        # Control: the address with no account gets a verification link, the account a reset link.
        assert [urlsplit(link).path for link in stack.links("new@example.com")] == ["/account/verify"]
        assert [urlsplit(link).path for link in stack.links("active@example.com")] == ["/account/reset"]

    # Every request does the same work, so a relay that is down answers every address alike.
    with _accounts(db_engine, transport=_relay_down) as stack:
        for path in (_SIGN_UP, _RESET):
            answers = [
                stack.client(f"10.0.7.{n}").post(path, json={"email": address})
                for n, address in enumerate(addresses, start=1)
            ]
            assert answers[0].status_code == 502
            assert all(_said(response) == _said(answers[0]) for response in answers)


@pytest.mark.parametrize("approval", [False, True], ids=["open", "approved"])
def test_case_accounts_proof_of_address(db_engine: Engine, approval: bool) -> None:
    """``accounts.proof-of-address``: nothing exists, and nobody signs in, until the token is
    redeemed, and the account opens with the password given then, never one the asker chose."""
    asked, chosen = "the passphrase whoever asked would set", _PASSWORD
    with _accounts(db_engine, requires_approval=approval) as stack:
        # The request takes no password: one presented with it is ignored, never stored.
        asking = stack.client().post(_SIGN_UP, json={"email": "member@example.com", "password": asked})
        assert asking.status_code == 202
        unknown = stack.sign_in("nobody@example.com")
        for n, password in enumerate((asked, chosen), start=1):
            before = stack.sign_in("member@example.com", password, caller=f"10.0.8.{n}")
            assert before.status_code == 401
            assert _answer(before) == _answer(unknown), "before redemption the address is as unknown as one never seen"
        assert _users(db_engine) == []

        opened = stack.client().post(_VERIFY, json={"token": stack.token("member@example.com"), "password": chosen})
        assert opened.status_code == 201 and opened.json() == {"active": not approval}
        assert stack.sign_in("member@example.com", asked, caller="10.0.8.3").status_code == 401, (
            "the password presented with the request never signs in"
        )
        after = stack.sign_in("member@example.com", chosen, caller="10.0.8.4")
        if approval:
            assert after.status_code == 401, "an account held for approval cannot sign in"
        else:
            # Control: without an approval step, the account signs in with the password
            # given at redemption.
            assert after.status_code == 200, after.text


def test_case_accounts_single_use(db_engine: Engine, make_user) -> None:
    """``accounts.single-use``: a token works once, and a reset token dies with a later revocation."""
    make_user("member@example.com", _PASSWORD, Roles.EDITOR)
    with _accounts(db_engine) as stack:
        client = stack.client()
        assert client.post(_SIGN_UP, json={"email": "new@example.com"}).status_code == 202
        verification = stack.token("new@example.com")
        assert client.post(_RESET, json={"email": "member@example.com"}).status_code == 202
        first = stack.token("member@example.com")
        assert client.post(_RESET, json={"email": "member@example.com"}).status_code == 202
        second = stack.token("member@example.com")
        assert first != second

        # Control: the first redemption of the verification token and of the first reset token.
        assert stack.client("10.0.1.1").post(_VERIFY, json={"token": verification, "password": _PASSWORD}).status_code == 201
        assert stack.client("10.0.1.2").post(
            _CONFIRM, json={"token": first, "password": "the first new passphrase of this case"}
        ).status_code == 204

        again = stack.client("10.0.1.3").post(
            _VERIFY, json={"token": verification, "password": "another long and unremarkable passphrase"}
        )
        assert (again.status_code, again.json()["code"]) == (400, "invalid_token")
        assert [u.email for u in _users(db_engine)].count("new@example.com") == 1
        assert stack.sign_in("new@example.com", "another long and unremarkable passphrase", caller="10.0.1.7").status_code == 401
        again = stack.client("10.0.1.4").post(_CONFIRM, json={"token": first, "password": "the second new passphrase of this case"})
        assert (again.status_code, again.json()["code"]) == (400, "invalid_token")
        stale = stack.client("10.0.1.5").post(_CONFIRM, json={"token": second, "password": "the third new passphrase of this case"})
        assert (stale.status_code, stale.json()["code"]) == (400, "invalid_token"), (
            "the first reset revoked the sessions this token was issued under"
        )
        assert stack.sign_in("member@example.com", "the first new passphrase of this case").status_code == 200, "nothing changed"
        for refused in ("the second new passphrase of this case", "the third new passphrase of this case"):
            assert stack.sign_in("member@example.com", refused, caller="10.0.1.6").status_code == 401


def _encoded_part(token: str) -> tuple[str, str]:
    """The token's leading format marker (``enc:v1:``, say), if it has one, and the text after it."""
    marker, _, encoded = token.rpartition(":")
    return (f"{marker}:" if marker else ""), encoded


def _decodings(token: str) -> list[bytes]:
    """The token as text, and the text after its format marker as each common encoding decodes it."""
    _, encoded = _encoded_part(token)
    found = [token.encode(), unquote(token).encode()]
    for decode in (base64.urlsafe_b64decode, base64.b64decode, bytes.fromhex):
        try:
            raw = decode(encoded) if decode is bytes.fromhex else decode(encoded + "=" * (-len(encoded) % 4))
        except (binascii.Error, ValueError):
            continue
        found.append(raw)
    return found


def _altered(token: str) -> str:
    """The token in the same form with one decoded byte changed: its marker kept, re-encoded as sent."""
    marker, encoded = _encoded_part(token)
    raw = bytearray(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    raw[len(raw) // 2] ^= 0x01
    altered = base64.urlsafe_b64encode(bytes(raw)).decode()
    return marker + (altered if encoded.endswith("=") else altered.rstrip("="))


def test_case_accounts_sealed_tokens(db_engine: Engine, make_user) -> None:
    """``accounts.sealed-tokens``: a token cannot be altered or read, and rides only the fragment."""
    make_user("member@example.com", _PASSWORD, Roles.EDITOR)
    with _accounts(db_engine) as stack:
        assert stack.client("10.0.2.1").post(_SIGN_UP, json={"email": "new@example.com"}).status_code == 202
        assert stack.client("10.0.2.2").post(_RESET, json={"email": "member@example.com"}).status_code == 202
        (verify_link,) = stack.links("new@example.com")
        (reset_link,) = stack.links("member@example.com")

        for link, address in ((verify_link, "new@example.com"), (reset_link, "member@example.com")):
            parts = urlsplit(link)
            token = parts.fragment.removeprefix("token=")
            assert token and parts.fragment == f"token={token}", "the token rides the fragment"
            assert parts.query == "" and token not in parts.path, "and nowhere a server sees"
            assert not any(address.encode() in decoded for decoded in _decodings(token))
            # Control: the same search finds the address in a token of this form that is
            # only encoded, so finding nothing above is the seal and not the search.
            marker, _ = _encoded_part(token)
            encoded_only = marker + base64.urlsafe_b64encode(json.dumps({"e": address}).encode()).decode()
            assert any(address.encode() in decoded for decoded in _decodings(encoded_only))

        verification, reset = stack.token("new@example.com"), stack.token("member@example.com")
        for token in (verification, reset):
            altered = _altered(token)
            assert altered != token and len(altered) == len(token), "other bytes, the same length"
            assert _encoded_part(altered)[0] == _encoded_part(token)[0], "and the same form"
        new = "an entirely new and unremarkable passphrase"
        refused = [
            stack.client("10.0.2.3").post(_VERIFY, json={"token": _altered(verification), "password": new}),
            stack.client("10.0.2.4").post(_CONFIRM, json={"token": _altered(reset), "password": new}),
            stack.client("10.0.2.5").post(_VERIFY, json={"token": reset, "password": new}),
            stack.client("10.0.2.6").post(_CONFIRM, json={"token": verification, "password": new}),
        ]
        assert [(r.status_code, r.json()["code"]) for r in refused] == [(400, "invalid_token")] * 4
        assert [u.email for u in _users(db_engine)] == ["member@example.com"], "nothing was opened"
        assert stack.sign_in("member@example.com").status_code == 200, "and nothing was reset"

        # Control: each unaltered token redeems for its own purpose.
        assert stack.client("10.0.2.7").post(_VERIFY, json={"token": verification, "password": _PASSWORD}).status_code == 201
        assert stack.client("10.0.2.8").post(_CONFIRM, json={"token": reset, "password": new}).status_code == 204


def test_case_accounts_expiry(db_engine: Engine, make_user, monkeypatch: pytest.MonkeyPatch) -> None:
    """``accounts.expiry``: a token dies with its lifetime, which is bounded at a week and a day."""
    make_user("member@example.com", _PASSWORD, Roles.EDITOR)
    renewed = "the passphrase a reset within its lifetime set"
    with _accounts(db_engine) as stack:
        for n, address in enumerate(("late@example.com", "early@example.com"), start=1):
            assert stack.client(f"10.0.3.{n}").post(_SIGN_UP, json={"email": address}).status_code == 202
        assert stack.client("10.0.3.3").post(_RESET, json={"email": "member@example.com"}).status_code == 202
        late, early, within = (stack.token(a) for a in ("late@example.com", "early@example.com", "member@example.com"))

        # Control: within their lifetimes, a verification token and a reset token redeem.
        assert stack.client("10.0.3.4").post(_VERIFY, json={"token": early, "password": _PASSWORD}).status_code == 201
        assert stack.client("10.0.3.5").post(_CONFIRM, json={"token": within, "password": renewed}).status_code == 204
        # A reset issued after that one, so only its lifetime can refuse it below.
        assert stack.client("10.0.3.6").post(_RESET, json={"email": "member@example.com"}).status_code == 202
        reset = stack.token("member@example.com")
        assert reset != within

        # The clock the tokens are read against moves past both default lifetimes.
        past = datetime.now(UTC) + timedelta(hours=25)
        monkeypatch.setattr(account_tokens, "_utc_now", lambda: past)
        expired = [
            stack.client("10.0.3.7").post(_VERIFY, json={"token": late, "password": _PASSWORD}),
            stack.client("10.0.3.8").post(
                _CONFIRM, json={"token": reset, "password": "an entirely new and unremarkable passphrase"}
            ),
        ]
        assert [(r.status_code, r.json()["code"]) for r in expired] == [(400, "invalid_token")] * 2
        assert "late@example.com" not in {u.email for u in _users(db_engine)}
        assert stack.sign_in("member@example.com", renewed).status_code == 200, "the expired reset changed nothing"

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
    """``accounts.backoff``: requests slow down alike for every address, per caller, and never lock out."""
    make_user("member@example.com", _PASSWORD, Roles.EDITOR)
    addresses = ("member@example.com", "someone@example.com")
    with _accounts(db_engine) as stack:
        first, second = stack.client("10.0.4.1"), stack.client("10.0.4.2")

        def until_refused(address: str) -> list[tuple[int, Any]]:
            answers: list[tuple[int, Any]] = []
            while not answers or answers[-1][0] != 429:
                answers.append(_answer(first.post(_SIGN_UP, json={"email": address})))
                assert len(answers) <= 10, "the backoff engaged"
            return answers

        with_account, without = (until_refused(address) for address in addresses)
        assert with_account == without, "the same requests receive the same answers"
        assert with_account[0][0] == 202, "control: a first request about each address is accepted"
        refusal = with_account[-1][1]
        assert refusal["code"] == "too_many_attempts"
        assert "lock" not in refusal["detail"].lower(), "a refusal says wait, never locked"

        # While the first caller is slowed, a caller that has not been is answered on its merits.
        for address in addresses:
            assert first.post(_SIGN_UP, json={"email": address}).status_code == 429
            assert second.post(_SIGN_UP, json={"email": address}).status_code == 202

        stack.clock[0] += 3  # past the documented first backoff (two seconds)
        for address in addresses:
            assert first.post(_SIGN_UP, json={"email": address}).status_code == 202

        # Failed redemptions back off the caller that made them, and only that caller.
        for n, address in enumerate(("valid@example.com", "other@example.com"), start=3):
            assert stack.client(f"10.0.4.{n}").post(_SIGN_UP, json={"email": address}).status_code == 202
        guesser, honest = stack.client("10.0.4.5"), stack.client("10.0.4.6")
        statuses = [
            guesser.post(_VERIFY, json={"token": f"guess-{n}", "password": _PASSWORD}).status_code for n in range(4)
        ]
        assert statuses == [400, 400, 400, 429]
        valid = {"token": stack.token("valid@example.com"), "password": _PASSWORD}
        assert guesser.post(_VERIFY, json=valid).status_code == 429
        other = {"token": stack.token("other@example.com"), "password": _PASSWORD}
        assert honest.post(_VERIFY, json=other).status_code == 201, "another caller's redemption is not held up"
        stack.clock[0] += 3
        assert guesser.post(_VERIFY, json=valid).status_code == 201, "after the backoff a request is answered on its merits"


def test_case_accounts_lowest_rank(db_engine: Engine, make_user) -> None:
    """``accounts.lowest-rank``: a self-registered account holds the least authority there is."""
    least, next_up = sorted(Roles)[:2]
    make_user("editor@example.com", _PASSWORD, next_up)
    note = {"title": "a note", "body": ""}
    with _accounts(db_engine) as stack:
        member = stack.open_account("member@example.com")
        profile = stack.client().get(_ME, headers=_bearer(member))
        assert profile.status_code == 200, profile.text
        assert profile.json()["role_rank"] == least
        # Writing a note is what the next authority up may do and the least may not; reading
        # one the least may, so the refusal is about authority and not about being signed in.
        assert stack.client().post(_NOTES, json=note, headers=_bearer(member)).status_code == 403
        assert stack.client().get(_NOTES, headers=_bearer(member)).status_code == 200

        # Control: a subject with the next authority performs the same operation.
        editor = stack.sign_in("editor@example.com")
        assert editor.status_code == 200, editor.text
        assert stack.client().post(_NOTES, json=note, headers=_bearer(editor.json()["access_token"])).status_code == 201


def test_case_accounts_close(db_engine: Engine, make_user) -> None:
    """``accounts.close``: closing takes the password again and ends every session."""
    make_user("admin@example.com", _PASSWORD, Roles.ADMIN)
    with _accounts(db_engine) as stack:
        stack.open_account("member@example.com")
        browser, phone = stack.client("10.0.5.1"), stack.client("10.0.5.2")
        signed_in = browser.post(_LOGIN, json={"email": "member@example.com", "password": _PASSWORD})
        assert signed_in.status_code == 200 and browser.cookies.get(_COOKIE)
        native = phone.post(_NATIVE_LOGIN, json={"email": "member@example.com", "password": _PASSWORD})
        assert native.status_code == 200
        access = [signed_in.json()["access_token"], native.json()["access_token"]]
        native_refresh = native.json()["refresh_token"]

        def accepted() -> list[int]:
            return [stack.client().get(_ME, headers=_bearer(token)).status_code for token in access]

        def refresh_both() -> None:
            """Refresh each client, keeping the credentials each refresh issues."""
            nonlocal native_refresh
            cookie = browser.post(_REFRESH)  # the browser's jar keeps the rotated cookie
            body = phone.post(_NATIVE_REFRESH, json={"refresh_token": native_refresh})
            assert (cookie.status_code, body.status_code) == (200, 200), (cookie.text, body.text)
            native_refresh = body.json()["refresh_token"]
            access.extend((cookie.json()["access_token"], body.json()["access_token"]))

        # Control: before closing, both clients' access and refresh credentials are accepted.
        assert accepted() == [200, 200]
        refresh_both()
        assert accepted() == [200] * 4

        wrong = browser.post(_CLOSE, json={"password": "not the password"}, headers=_bearer(access[0]))
        # A 403, not a 401: the session is valid, and a client reads a 401 as one that is not.
        assert (wrong.status_code, wrong.json()["code"]) == (403, "password_not_confirmed")
        assert accepted() == [200] * 4, "a wrong password changes nothing"
        refresh_both()

        closed = browser.post(_CLOSE, json={"password": _PASSWORD}, headers=_bearer(access[0]))
        assert closed.status_code == 204, closed.text
        assert accepted() == [401] * 6
        assert browser.post(_REFRESH).status_code == 401
        assert phone.post(_NATIVE_REFRESH, json={"refresh_token": native_refresh}).status_code == 401
        assert stack.sign_in("member@example.com").status_code == 401

        admin = stack.sign_in("admin@example.com").json()["access_token"]
        refused = stack.client("10.0.5.4").post(_CLOSE, json={"password": _PASSWORD}, headers=_bearer(admin))
        assert (refused.status_code, refused.json()["code"]) == (409, "last_admin_protected")
        assert stack.sign_in("admin@example.com").status_code == 200
