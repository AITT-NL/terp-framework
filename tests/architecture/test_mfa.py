"""Gate for ``terp-cap-mfa`` (ADR 0150): TOTP, sealing, recovery codes, and the login seam.

The TOTP section is held to **RFC 6238's own published test vectors** rather than to
round-tripping our own implementation against itself. That distinction is the whole
reason hand-rolling the algorithm was defensible: a round-trip test passes just as
happily against an implementation that is confidently wrong in a way every authenticator
app disagrees with, and the vectors catch exactly that.
"""

from __future__ import annotations

import base64
import datetime
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from terp.core import Principal, Roles
from terp.core._internal.session_guard import WriteGuardedSession
from terp.core.config import settings

from terp.capabilities.auth import MfaRequiredError, decode_access_token
from terp.capabilities.mfa import (
    MfaAlreadyEnrolledError,
    MfaCodeInvalidError,
    MfaEnrolmentRead,
    MfaNotEnrolledError,
    MfaSecretError,
    MfaService,
    is_sealed_secret,
    seal_secret,
    unseal_secret,
)
from terp.capabilities.mfa import recovery, totp
from terp.capabilities.mfa.models import MfaEnrolment, MfaRecoveryCode

# RFC 6238 Appendix B, SHA1 rows. The published table is 8-digit and this implementation
# is 6-digit; truncation is `mod 10**digits`, so the 6-digit code is exactly the low six
# digits of the published value.
_RFC_SEED = base64.b32encode(b"12345678901234567890").decode("ascii")
_RFC_VECTORS = {
    59: "94287082",
    1111111109: "07081804",
    1111111111: "14050471",
    1234567890: "89005924",
    2000000000: "69279037",
    20000000000: "65353130",
}


@pytest.fixture(autouse=True)
def _secret_key() -> Iterator[None]:
    """Sealing derives from SECRET_KEY, so the suite pins one."""
    previous = settings.SECRET_KEY
    settings.SECRET_KEY = "mfa-test-secret-key-0123456789abcdef"
    yield
    settings.SECRET_KEY = previous


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with WriteGuardedSession(engine) as sess:
        yield sess
    engine.dispose()


# --------------------------------------------------------------------------- #
# TOTP, against the specification's own vectors
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("moment", "published"), sorted(_RFC_VECTORS.items()))
def test_totp_matches_the_rfc_6238_vectors(moment: int, published: str) -> None:
    assert totp.generate(_RFC_SEED, at=moment) == published[-6:]


def test_a_code_from_the_adjacent_step_verifies_and_two_steps_away_does_not() -> None:
    """Drift is bounded and symmetric, and the boundary is the assertion.

    A window that only reached backwards would fail the person whose phone is fast; one
    that reached two steps would double the codes a guesser may hit. Both edges are
    pinned, and so is the first step outside.
    """
    now = 1111111111
    assert totp.verify(_RFC_SEED, totp.generate(_RFC_SEED, at=now), at=now)
    assert totp.verify(_RFC_SEED, totp.generate(_RFC_SEED, at=now - 30), at=now)
    assert totp.verify(_RFC_SEED, totp.generate(_RFC_SEED, at=now + 30), at=now)
    assert not totp.verify(_RFC_SEED, totp.generate(_RFC_SEED, at=now - 60), at=now)
    assert not totp.verify(_RFC_SEED, totp.generate(_RFC_SEED, at=now + 60), at=now)


def test_verification_does_the_same_work_whichever_step_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every candidate step is computed, even after one matches.

    This is the one property of :func:`totp.verify` that no assertion on its *return
    value* can reach: short-circuiting on the first match is behaviourally identical and
    leaks, through timing, which step matched — and with it the direction and size of the
    caller's clock error. Counting the work is the only way to see it, so the count is
    what is asserted.
    """
    now = 1111111111
    calls: list[int] = []
    original = totp._counter_code

    def _counting(secret: str, counter: int) -> str:
        calls.append(counter)
        return original(secret, counter)

    # Generated BEFORE the counter is instrumented: `generate` computes a code too, and
    # counting it would put the work of producing the input into the measurement.
    codes = {offset: totp.generate(_RFC_SEED, at=now + offset) for offset in (-30, 0, 30)}
    monkeypatch.setattr(totp, "_counter_code", _counting)

    for offset, code in codes.items():
        calls.clear()
        assert totp.verify(_RFC_SEED, code, at=now)
        # 2 * drift_steps + 1 candidates, whichever one happened to match.
        assert len(calls) == 2 * totp.DEFAULT_DRIFT_STEPS + 1, (
            f"a code from step {offset // 30:+d} took {len(calls)} computations"
        )


def test_a_malformed_code_is_refused_without_touching_the_secret() -> None:
    for candidate in ("", "12345", "1234567", "abcdef", "12 34 56 78"):
        assert not totp.verify(_RFC_SEED, candidate)


def test_a_generated_secret_round_trips_through_an_authenticator_uri() -> None:
    secret = totp.generate_secret()
    uri = totp.provisioning_uri(secret, account="a@x.test", issuer="Acme")
    assert uri.startswith("otpauth://totp/")
    # The parameters an app reads; a typo in any of them scans cleanly and never matches.
    assert f"secret={secret}" in uri
    assert "algorithm=SHA1" in uri and "digits=6" in uri and "period=30" in uri
    assert totp.verify(secret, totp.generate(secret))


# --------------------------------------------------------------------------- #
# Sealing
# --------------------------------------------------------------------------- #
def test_the_secret_is_sealed_at_rest_and_comes_back_intact() -> None:
    secret = totp.generate_secret()
    sealed = seal_secret(secret)
    assert is_sealed_secret(sealed)
    assert secret not in sealed
    assert unseal_secret(sealed) == secret


def test_an_unsealed_value_is_refused_rather_than_used() -> None:
    """No row here predates the sealing control, so plaintext is a bug, not legacy.

    The webhooks capability passes an unsealed value through because rows written before
    its control exist. Copying that tolerance here would mean a tampered row reads as a
    valid second factor, which is the one mistake this module exists to prevent.
    """
    with pytest.raises(MfaSecretError):
        unseal_secret("JBSWY3DPEHPK3PXP")


def test_a_seal_from_another_key_does_not_open() -> None:
    sealed = seal_secret("JBSWY3DPEHPK3PXP")
    settings.SECRET_KEY = "a-completely-different-secret-key-0123456789"
    with pytest.raises(MfaSecretError):
        unseal_secret(sealed)


# --------------------------------------------------------------------------- #
# Recovery codes
# --------------------------------------------------------------------------- #
def test_recovery_codes_are_distinct_and_normalise_for_typing() -> None:
    codes = recovery.generate_codes()
    assert len(codes) == recovery.CODE_COUNT
    assert len(set(codes)) == len(codes)
    # People retype these from paper: separators and case are presentation, not content.
    one = codes[0]
    assert recovery.matches(one.lower().replace("-", " "), recovery.hash_code(one))


def test_a_recovery_code_is_stored_only_as_a_digest(session: Session) -> None:
    service = MfaService()
    issued = service.begin_enrolment(
        session, uuid.uuid4(), account="a@x.test", issuer="Acme"
    )
    stored = session.exec(select(MfaRecoveryCode)).all()
    assert len(stored) == recovery.CODE_COUNT
    for code in issued.recovery_codes:
        assert all(code not in row.code_hash for row in stored)


# --------------------------------------------------------------------------- #
# Enrolment is two steps
# --------------------------------------------------------------------------- #
def test_an_unconfirmed_enrolment_gates_nothing(session: Session) -> None:
    """The mis-scanned-QR case, which is the one that makes people disable the feature.

    A secret issued but never proved must not stand between its owner and their account:
    they may have scanned nothing at all, and would discover it at the next login with no
    way back in.
    """
    service = MfaService()
    user = uuid.uuid4()
    service.begin_enrolment(session, user, account="a@x.test", issuer="Acme")

    assert service.enrolment_for(session, user) is not None
    assert service.is_enrolled(session, user) is False


def test_confirming_with_a_generated_code_makes_the_factor_live(session: Session) -> None:
    service = MfaService()
    user = uuid.uuid4()
    issued = service.begin_enrolment(session, user, account="a@x.test", issuer="Acme")

    service.confirm_enrolment(session, user, totp.generate(issued.secret))

    assert service.is_enrolled(session, user) is True


def test_confirming_with_a_wrong_code_leaves_it_unconfirmed(session: Session) -> None:
    service = MfaService()
    user = uuid.uuid4()
    service.begin_enrolment(session, user, account="a@x.test", issuer="Acme")

    with pytest.raises(MfaCodeInvalidError):
        service.confirm_enrolment(session, user, "000000")
    assert service.is_enrolled(session, user) is False


def test_starting_again_replaces_an_unconfirmed_enrolment(session: Session) -> None:
    """Somebody who closed the tab cannot recover the first secret; let them restart."""
    service = MfaService()
    user = uuid.uuid4()
    first = service.begin_enrolment(session, user, account="a@x.test", issuer="Acme")
    second = service.begin_enrolment(session, user, account="a@x.test", issuer="Acme")

    assert first.secret != second.secret
    assert len(session.exec(select(MfaEnrolment)).all()) == 1
    # The first enrolment's codes went with it.
    assert len(session.exec(select(MfaRecoveryCode)).all()) == recovery.CODE_COUNT


def test_starting_again_over_a_live_factor_is_refused(session: Session) -> None:
    """Silently replacing a live factor is what an attacker with a stolen session does."""
    service = MfaService()
    user = uuid.uuid4()
    issued = service.begin_enrolment(session, user, account="a@x.test", issuer="Acme")
    service.confirm_enrolment(session, user, totp.generate(issued.secret))

    with pytest.raises(MfaAlreadyEnrolledError):
        service.begin_enrolment(session, user, account="a@x.test", issuer="Acme")


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #
def _live(session: Session, service: MfaService) -> tuple[uuid.UUID, object]:
    user = uuid.uuid4()
    issued = service.begin_enrolment(session, user, account="a@x.test", issuer="Acme")
    service.confirm_enrolment(session, user, totp.generate(issued.secret))
    return user, issued


def test_verify_accepts_the_current_totp_code(session: Session) -> None:
    service = MfaService()
    user, issued = _live(session, service)
    assert service.verify(session, user, totp.generate(issued.secret)) is True
    assert service.verify(session, user, "000000") is False


def test_a_recovery_code_works_once_and_then_never_again(session: Session) -> None:
    """A code that still worked after being used is a password with extra steps."""
    service = MfaService()
    user, issued = _live(session, service)
    code = issued.recovery_codes[0]

    assert service.verify(session, user, code) is True
    assert service.verify(session, user, code) is False
    # Spent, not deleted: an operator wants to see it in the trail.
    spent = [row for row in session.exec(select(MfaRecoveryCode)).all() if row.used_at]
    assert len(spent) == 1


def test_spending_one_recovery_code_leaves_the_others(session: Session) -> None:
    service = MfaService()
    user, issued = _live(session, service)
    service.verify(session, user, issued.recovery_codes[0])
    assert service.verify(session, user, issued.recovery_codes[1]) is True


def test_verify_is_false_for_a_subject_with_no_live_factor(session: Session) -> None:
    service = MfaService()
    assert service.verify(session, uuid.uuid4(), "000000") is False


def test_disabling_removes_the_factor_and_its_codes(session: Session) -> None:
    service = MfaService()
    user, _ = _live(session, service)

    service.disable(session, user)

    assert service.is_enrolled(session, user) is False
    assert session.exec(select(MfaEnrolment)).all() == []
    # The codes go with it. A disabled factor whose recovery codes still authenticate
    # is the worst of the available failures: the account looks protected and is not.
    assert session.exec(select(MfaRecoveryCode)).all() == []
    with pytest.raises(MfaNotEnrolledError):
        service.disable(session, user)


def test_no_read_dto_carries_the_secret() -> None:
    """The one moment a plaintext secret crosses the boundary is the enrolment response."""
    assert "secret" not in MfaEnrolmentRead.model_fields


# --------------------------------------------------------------------------- #
# The login seam
# --------------------------------------------------------------------------- #
def _login_app(session: Session, *, with_factor: bool):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from terp.capabilities.auth import build_login_router
    from terp.core.app import register_error_handlers
    from terp.core.db import get_session

    principal = Principal(id=_login_app.user, role=Roles.EDITOR)

    def authenticate(_session, email: str, password: str):
        return principal if password == "right" else None

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(
        build_login_router(
            authenticate,
            second_factor=MfaService() if with_factor else None,
        ),
        prefix="/auth",
    )
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app, raise_server_exceptions=False)


def test_a_login_with_no_second_factor_is_unchanged(session: Session) -> None:
    """Wiring the seam changes nothing for an account that has not enrolled."""
    _login_app.user = uuid.uuid4()
    client = _login_app(session, with_factor=True)

    response = client.post("/auth/login", json={"email": "a@x.test", "password": "right"})

    assert response.status_code == 200
    assert decode_access_token(response.json()["access_token"]).amr == ("pwd",)


def test_a_password_alone_is_refused_once_a_factor_is_live(session: Session) -> None:
    """The refusal is distinguishable so a client knows to prompt for the code."""
    _login_app.user = uuid.uuid4()
    service = MfaService()
    issued = service.begin_enrolment(
        session, _login_app.user, account="a@x.test", issuer="Acme"
    )
    service.confirm_enrolment(session, _login_app.user, totp.generate(issued.secret))
    client = _login_app(session, with_factor=True)

    response = client.post("/auth/login", json={"email": "a@x.test", "password": "right"})

    assert response.status_code == 401
    assert response.json()["code"] == MfaRequiredError.code


def test_the_right_password_and_code_mint_a_token_that_says_so(session: Session) -> None:
    _login_app.user = uuid.uuid4()
    service = MfaService()
    issued = service.begin_enrolment(
        session, _login_app.user, account="a@x.test", issuer="Acme"
    )
    service.confirm_enrolment(session, _login_app.user, totp.generate(issued.secret))
    client = _login_app(session, with_factor=True)

    response = client.post(
        "/auth/login",
        json={
            "email": "a@x.test",
            "password": "right",
            "mfa_code": totp.generate(issued.secret),
        },
    )

    assert response.status_code == 200
    # The token records HOW it was obtained, which is what a later step-up decision reads.
    assert decode_access_token(response.json()["access_token"]).amr == ("pwd", "otp")


def test_a_wrong_code_is_an_ordinary_authentication_failure(session: Session) -> None:
    """Not `mfa_required`: the client already prompted, and the answer was wrong."""
    _login_app.user = uuid.uuid4()
    service = MfaService()
    issued = service.begin_enrolment(
        session, _login_app.user, account="a@x.test", issuer="Acme"
    )
    service.confirm_enrolment(session, _login_app.user, totp.generate(issued.secret))
    client = _login_app(session, with_factor=True)

    response = client.post(
        "/auth/login",
        json={"email": "a@x.test", "password": "right", "mfa_code": "000000"},
    )

    assert response.status_code == 401
    assert response.json()["code"] != MfaRequiredError.code


def test_an_unconfirmed_enrolment_does_not_block_a_login(session: Session) -> None:
    """The lockout this capability must never cause, asserted end to end."""
    _login_app.user = uuid.uuid4()
    MfaService().begin_enrolment(
        session, _login_app.user, account="a@x.test", issuer="Acme"
    )
    client = _login_app(session, with_factor=True)

    response = client.post("/auth/login", json={"email": "a@x.test", "password": "right"})

    assert response.status_code == 200


def test_a_login_route_with_no_seam_wired_never_asks_for_a_factor(session: Session) -> None:
    """An app that has not wired MFA is unaffected even if a row exists."""
    _login_app.user = uuid.uuid4()
    service = MfaService()
    issued = service.begin_enrolment(
        session, _login_app.user, account="a@x.test", issuer="Acme"
    )
    service.confirm_enrolment(session, _login_app.user, totp.generate(issued.secret))
    client = _login_app(session, with_factor=False)

    response = client.post("/auth/login", json={"email": "a@x.test", "password": "right"})

    assert response.status_code == 200
    assert decode_access_token(response.json()["access_token"]).amr == ("pwd",)


def test_a_token_minted_without_an_amr_claim_reports_none(session: Session) -> None:
    """An older token says nothing about how it was obtained; that silence is not 'pwd'."""
    from terp.capabilities.auth import create_access_token

    token = create_access_token(subject=uuid.uuid4(), role=Roles.VIEWER)
    assert decode_access_token(token).amr == ()


def test_the_enrolment_row_never_holds_the_plaintext_secret(session: Session) -> None:
    service = MfaService()
    user = uuid.uuid4()
    issued = service.begin_enrolment(session, user, account="a@x.test", issuer="Acme")

    row = service.enrolment_for(session, user)
    assert row is not None
    assert issued.secret not in row.secret
    assert is_sealed_secret(row.secret)
    assert unseal_secret(row.secret) == issued.secret


def test_confirming_stamps_when_it_happened(session: Session) -> None:
    """The stamp is what separates a started enrolment from a live one.

    Asserted as a value rather than as a timezone: the column is declared
    ``DateTime(timezone=True)`` and the platform has a rule holding it that way, but
    SQLite does not preserve an offset, so a tzinfo assertion here would be testing the
    test database rather than the service.
    """
    before = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    service = MfaService()
    user, _ = _live(session, service)

    row = service.enrolment_for(session, user)
    assert row is not None and row.confirmed_at is not None
    stamped = row.confirmed_at.replace(tzinfo=None)
    assert before <= stamped <= datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def test_confirming_without_an_enrolment_is_refused(session: Session) -> None:
    """A code for a factor that was never started is a 404, not a silent no-op.

    The alternative — treating it as an ordinary wrong code — would tell a caller their
    digits were wrong when in fact nothing was ever enrolled, and would hide a client
    that has lost track of its own state.
    """
    service = MfaService()
    with pytest.raises(MfaNotEnrolledError):
        service.confirm_enrolment(session, uuid.uuid4(), "000000")


def test_confirming_a_live_factor_again_is_refused(session: Session) -> None:
    """Confirmation is the one-way step that makes a factor live, so it happens once.

    Allowing a second confirmation would let a replayed code re-stamp ``confirmed_at``,
    moving the record of when the factor became live away from the moment it did.
    """
    service = MfaService()
    user, issued = _live(session, service)
    with pytest.raises(MfaAlreadyEnrolledError):
        service.confirm_enrolment(session, user, totp.generate(issued.secret))


# --------------------------------------------------------------------------- #
# The self-scoped router
# --------------------------------------------------------------------------- #
def _router_app(session: Session, principal: Principal | None):
    """The MFA router mounted **bare** — no deny-by-default module guard in front of it.

    Deliberately bare. In a composed app the module guard rejects an anonymous caller
    before any handler runs, so the router's own ``_caller`` branch is unreachable there
    and would go untested in exactly the arrangement it exists for: this router mounted
    without a guard.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from terp.core import get_principal
    from terp.core.app import register_error_handlers
    from terp.core.db import get_session

    from terp.capabilities.mfa.router import router as mfa_router

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(mfa_router, prefix="/mfa")
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_principal] = lambda: principal
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/mfa/"), ("post", "/mfa/"), ("post", "/mfa/confirm"), ("delete", "/mfa/")],
)
def test_no_mfa_route_serves_an_anonymous_caller(
    session: Session, method: str, path: str
) -> None:
    """Every route reads the caller from the principal, so none may run without one.

    A 401 rather than the ``AttributeError`` an unguarded ``principal.id`` would raise:
    the second one is a 500 that tells an operator the service is broken when what
    actually happened is that a request arrived unauthenticated.
    """
    client = _router_app(session, None)
    body = {"json": {"code": "000000"}} if method == "post" else {}
    response = getattr(client, method)(path, **body)
    assert response.status_code == 401


def test_status_reports_nothing_before_an_enrolment(session: Session) -> None:
    principal = Principal(id=uuid.uuid4(), role=Roles.VIEWER)

    body = _router_app(session, principal).get("/mfa/").json()

    assert body == {"enrolled": False, "confirmed": False, "recovery_codes_remaining": 0}


def test_status_counts_only_the_unspent_recovery_codes(session: Session) -> None:
    """A spent code is still a row, and must not be counted as one the person can use.

    This is the assertion that would catch a count of *all* the enrolment's codes: the
    row stays after it is spent (``used_at`` is stamped rather than the row deleted), so
    a naive count keeps reporting ten long after the last one is gone.
    """
    service = MfaService()
    user = uuid.uuid4()
    issued = service.begin_enrolment(session, user, account="a@x.test", issuer="Acme")
    service.confirm_enrolment(session, user, totp.generate(issued.secret))
    client = _router_app(session, Principal(id=user, role=Roles.VIEWER))

    before = client.get("/mfa/").json()
    assert before == {
        "enrolled": True,
        "confirmed": True,
        "recovery_codes_remaining": len(issued.recovery_codes),
    }

    assert service.verify(session, user, issued.recovery_codes[0]) is True

    after = client.get("/mfa/").json()
    assert after["recovery_codes_remaining"] == len(issued.recovery_codes) - 1


def test_enrolling_over_http_issues_a_secret_the_stored_row_does_not_hold(
    session: Session,
) -> None:
    """The one response carrying a plaintext secret, and the row it never reaches."""
    user = uuid.uuid4()
    client = _router_app(session, Principal(id=user, role=Roles.VIEWER))

    response = client.post("/mfa/")

    assert response.status_code == 201
    body = response.json()
    assert body["provisioning_uri"].startswith("otpauth://totp/")
    assert body["recovery_codes"]
    row = session.exec(select(MfaEnrolment).where(MfaEnrolment.user_id == user)).first()
    assert row is not None
    assert row.secret != body["secret"]
    assert unseal_secret(row.secret) == body["secret"]


def test_confirming_over_http_makes_the_factor_live_without_echoing_the_secret(
    session: Session,
) -> None:
    user = uuid.uuid4()
    client = _router_app(session, Principal(id=user, role=Roles.VIEWER))
    issued = client.post("/mfa/").json()

    response = client.post("/mfa/confirm", json={"code": totp.generate(issued["secret"])})

    assert response.status_code == 200
    body = response.json()
    assert body["confirmed_at"] is not None
    # The read DTO has no secret field at all; asserted on the wire because that is where
    # it would leak, and a field added to the model later would not fail the type check.
    assert "secret" not in body


def test_a_wrong_code_over_http_leaves_the_factor_unconfirmed(session: Session) -> None:
    user = uuid.uuid4()
    client = _router_app(session, Principal(id=user, role=Roles.VIEWER))
    client.post("/mfa/")

    response = client.post("/mfa/confirm", json={"code": "000000"})

    assert response.status_code == 401
    assert client.get("/mfa/").json()["confirmed"] is False


def test_disabling_over_http_removes_the_factor_and_its_codes(session: Session) -> None:
    user = uuid.uuid4()
    client = _router_app(session, Principal(id=user, role=Roles.VIEWER))
    issued = client.post("/mfa/").json()
    client.post("/mfa/confirm", json={"code": totp.generate(issued["secret"])})

    response = client.delete("/mfa/")

    assert response.status_code == 204
    assert client.get("/mfa/").json() == {
        "enrolled": False,
        "confirmed": False,
        "recovery_codes_remaining": 0,
    }
    assert session.exec(select(MfaRecoveryCode)).all() == []


# --------------------------------------------------------------------------- #
# The issuer an authenticator app shows
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _default_issuer() -> Iterator[None]:
    """Put the issuer back, so a test that names one cannot label the next test's codes."""
    from terp.capabilities.mfa import reset_mfa_issuer

    yield
    reset_mfa_issuer()


def test_an_unconfigured_deployment_falls_back_to_the_frameworks_own_name() -> None:
    from terp.capabilities.mfa import DEFAULT_ISSUER, active_mfa_issuer

    assert active_mfa_issuer() == DEFAULT_ISSUER


def test_a_configured_issuer_labels_the_codes_a_person_enrols(session: Session) -> None:
    """The issuer is the only thing telling one six-digit row from another on a phone."""
    from terp.capabilities.mfa import configure_mfa_issuer

    configure_mfa_issuer("  Acme Industrial  ")
    user = uuid.uuid4()
    client = _router_app(session, Principal(id=user, role=Roles.VIEWER))

    uri = client.post("/mfa/").json()["provisioning_uri"]

    # Surrounding whitespace is stripped rather than encoded into the label: a trailing
    # space in a deployment's config file would otherwise ship as %20 in every QR code.
    assert "issuer=Acme+Industrial" in uri
    assert uri.startswith("otpauth://totp/Acme%20Industrial%3A")


@pytest.mark.parametrize("name", ["", "   "])
def test_a_blank_issuer_is_refused_when_it_is_configured(name: str) -> None:
    """Refused at the composition root, not at the first enrolment.

    A blank issuer produces a QR code that scans cleanly and then appears in the
    authenticator app as an unlabelled row — a failure nobody notices until a person has
    two of them.
    """
    from terp.capabilities.mfa import active_mfa_issuer, configure_mfa_issuer

    with pytest.raises(ValueError, match="non-empty"):
        configure_mfa_issuer(name)
    assert active_mfa_issuer() != name
