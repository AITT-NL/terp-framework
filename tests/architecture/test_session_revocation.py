"""Session-management unit/branch coverage (ADR 0031): token epoch + login lockout.

Framework-level tests for the revocation/lockout paths that the example end-to-end
slice does not exercise in full: the :class:`LoginThrottle` state machine, the
revocable ``build_get_principal`` provider + its marker, and the
``create_app(require_token_revocation=True)`` boot guard. The behavioural proof that a
token dies on deactivate / role-change / password-reset / logout and that bad logins
lock an account lives in ``apps/example/tests/test_session_revocation_api.py``.
"""

from __future__ import annotations

import datetime
import uuid

import jwt
import pytest
from fastapi import APIRouter
from starlette.requests import Request

from terp.core import (
    BootError,
    ModuleSpec,
    Policy,
    Principal,
    Roles,
    create_app,
    enforces_token_revocation,
)
from terp.core.config import settings

from terp.capabilities.auth import (
    TOKEN_AUDIENCE,
    TOKEN_ISSUER,
    AccountLockedError,
    TooManyAttemptsError,
    LoginThrottle,
    build_get_principal,
    build_realtime_validator,
    create_access_token,
    decode_access_token,
)

_KEY = "terp-session-revocation-secret-key-0123456789"
# A stand-in for the request Session the provider passes the validator: the validators
# below ignore it (they decide purely on the decoded claims), so any object will do.
_SESSION = object()


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    return Request({"type": "http", "headers": raw})


def _at(monkeypatch: pytest.MonkeyPatch) -> list[datetime.datetime]:
    """Install a controllable clock for the throttle; return a 1-list holding 'now'."""
    import terp.capabilities.auth.throttle as throttle_mod

    now = [datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)]
    monkeypatch.setattr(throttle_mod, "_utc_now", lambda: now[0])
    return now


# --------------------------------------------------------------------------- #
# LoginThrottle — failed-credential backoff (ADR 0147)
#
# This block replaced a lockout suite, and one of the tests it replaced is worth
# naming: `test_throttle_locks_at_the_threshold_and_refuses_even_a_valid_credential`
# asserted that a locked identifier was refused **even with the right password**.
# That was a faithful test of the implementation and a pin on the defect — the
# property that made the control usable against the user it protected. Its
# replacement below asserts the opposite, by name, so the old behaviour cannot
# return quietly.
# --------------------------------------------------------------------------- #
def test_the_first_failures_cost_nothing() -> None:
    """People mistype; two attempts in a row is not an attack."""
    throttle = LoginThrottle(free_attempts=2)
    throttle.record_failure("a@x.test", source="198.51.100.7")
    throttle.record_failure("a@x.test", source="198.51.100.7")
    throttle.check("a@x.test", source="198.51.100.7")


def test_a_correct_credential_is_accepted_the_moment_the_backoff_elapses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect the lockout had, asserted as its inverse.

    A lockout refuses a *correct* password for a fixed window, which is what made it
    something an attacker could aim at somebody else. Backoff only ever delays: when the
    wait is over the next attempt is judged on its merits, and no state says otherwise.
    """
    now = _at(monkeypatch)
    throttle = LoginThrottle(
        free_attempts=1, base_delay=datetime.timedelta(seconds=4)
    )
    throttle.record_failure("a@x.test", source="198.51.100.7")
    throttle.record_failure("a@x.test", source="198.51.100.7")
    with pytest.raises(TooManyAttemptsError):
        throttle.check("a@x.test", source="198.51.100.7")

    now[0] += datetime.timedelta(seconds=5)
    throttle.check("a@x.test", source="198.51.100.7")  # no lock survives the wait


def test_one_callers_failures_do_not_delay_another_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The disarmed weapon, stated directly.

    An attacker who knows an address could previously take its owner offline by failing
    a handful of logins. Here the same attacker fails twenty times and the owner, from
    their own address, is not delayed by a second — the counters are different keys.
    """
    _at(monkeypatch)
    throttle = LoginThrottle(free_attempts=1, identifier_attempts=50)
    for _ in range(20):
        throttle.record_failure("victim@x.test", source="203.0.113.9")

    with pytest.raises(TooManyAttemptsError):
        throttle.check("victim@x.test", source="203.0.113.9")  # the attacker waits
    throttle.check("victim@x.test", source="198.51.100.7")  # the owner does not


def test_the_wait_doubles_with_every_further_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exponential, not linear: the guesser's cost grows, the typist's does not."""
    now = _at(monkeypatch)
    throttle = LoginThrottle(
        free_attempts=0,
        base_delay=datetime.timedelta(seconds=2),
        max_delay=datetime.timedelta(hours=1),
    )
    source = "203.0.113.9"

    throttle.record_failure("a@x.test", source=source)  # 1st → 2s
    now[0] += datetime.timedelta(seconds=3)
    throttle.check("a@x.test", source=source)

    throttle.record_failure("a@x.test", source=source)  # 2nd → 4s
    now[0] += datetime.timedelta(seconds=3)
    with pytest.raises(TooManyAttemptsError):
        throttle.check("a@x.test", source=source)
    now[0] += datetime.timedelta(seconds=2)
    throttle.check("a@x.test", source=source)

    # The third failure is where doubling and adding part company, and it is the only
    # place they do: 2, 4 then 8 seconds against 2, 4 then 6. A test that stopped at the
    # second failure would pass against a linear backoff, which is not the control.
    throttle.record_failure("a@x.test", source=source)  # 3rd → 8s, not 6s
    now[0] += datetime.timedelta(seconds=7)
    with pytest.raises(TooManyAttemptsError):
        throttle.check("a@x.test", source=source)
    now[0] += datetime.timedelta(seconds=1)  # exactly at 8s
    throttle.check("a@x.test", source=source)


def test_the_wait_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Doubling without a ceiling would recreate the lockout, only slower to arrive.

    On the boundary deliberately. Twelve failures would be 2 * 2**11 seconds uncapped —
    just over an hour — so if the ceiling were missing this would still be waiting long
    after the assertions below. One second inside the cap is refused; the cap itself has
    elapsed and is allowed.
    """
    now = _at(monkeypatch)
    throttle = LoginThrottle(
        free_attempts=0,
        base_delay=datetime.timedelta(seconds=2),
        max_delay=datetime.timedelta(seconds=10),
    )
    for _ in range(12):  # far past 2 * 2**11 seconds
        throttle.record_failure("a@x.test", source="203.0.113.9")

    now[0] += datetime.timedelta(seconds=9)
    with pytest.raises(TooManyAttemptsError):
        throttle.check("a@x.test", source="203.0.113.9")
    now[0] += datetime.timedelta(seconds=1)  # exactly at the cap
    throttle.check("a@x.test", source="203.0.113.9")


def test_a_distributed_guesser_still_meets_the_identifier_backstop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-source backoff alone is free to anyone with enough addresses.

    Each attempt here comes from its own source, so no pair counter ever passes its
    free allowance; the identifier counter is what finally bites.
    """
    _at(monkeypatch)
    throttle = LoginThrottle(free_attempts=2, identifier_attempts=10)
    for index in range(10):
        throttle.record_failure("a@x.test", source=f"203.0.113.{index}")

    with pytest.raises(TooManyAttemptsError):
        throttle.check("a@x.test", source="198.51.100.7")


def test_the_backstop_sits_far_above_the_per_caller_allowance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nine of ten failures must NOT engage it — the lever has to be expensive.

    The old control could be pulled in five attempts for fifteen minutes. If the
    backstop engaged early this change would have moved the weapon rather than removed
    it, and every other test here would still pass.
    """
    _at(monkeypatch)
    throttle = LoginThrottle(free_attempts=2, identifier_attempts=10)
    for index in range(9):
        throttle.record_failure("a@x.test", source=f"203.0.113.{index}")

    throttle.check("a@x.test", source="198.51.100.7")  # the owner is still served


def test_success_clears_both_counters() -> None:
    throttle = LoginThrottle(free_attempts=1, identifier_attempts=3)
    throttle.record_failure("a@x.test", source="203.0.113.9")
    throttle.record_failure("a@x.test", source="203.0.113.9")
    throttle.record_success("a@x.test", source="203.0.113.9")

    throttle.record_failure("a@x.test", source="203.0.113.9")
    throttle.check("a@x.test", source="203.0.113.9")


def test_throttle_normalizes_the_identifier() -> None:
    """Case variants of an address are one identifier, or the count is trivially dodged."""
    throttle = LoginThrottle(free_attempts=0)
    throttle.record_failure("  USER@X.test ", source="203.0.113.9")
    with pytest.raises(TooManyAttemptsError):
        throttle.check("user@x.test", source="203.0.113.9")


def test_a_source_less_caller_is_still_counted_once() -> None:
    """``source=None`` is for an identifier that already carries the caller (the OIDC key).

    Counted once, not twice: sharing one key between the per-caller counter and the
    backstop would reach the backstop at half its stated number — invisible, and it
    would double the strength of the one control an attacker can aim at somebody else.
    """
    throttle = LoginThrottle(free_attempts=2, identifier_attempts=4)
    for _ in range(3):
        throttle.record_failure("oidc:idp:203.0.113.9")

    # Three failures: past the free allowance (so the caller waits), but nowhere near
    # the backstop of four — which it would have reached had each failure counted twice.
    assert throttle._store.locked(throttle._identifier_key("oidc:idp:203.0.113.9")) == 0


def test_window_resets_stale_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    now = _at(monkeypatch)
    throttle = LoginThrottle(
        free_attempts=2,
        base_delay=datetime.timedelta(seconds=2),
        window=datetime.timedelta(minutes=10),
    )
    throttle.record_failure("a@x.test", source="203.0.113.9")
    throttle.record_failure("a@x.test", source="203.0.113.9")
    now[0] += datetime.timedelta(minutes=11)  # the window lapsed
    throttle.record_failure("a@x.test", source="203.0.113.9")  # a fresh count of 1
    throttle.check("a@x.test", source="203.0.113.9")


def test_throttle_reset_clears_all_state() -> None:
    throttle = LoginThrottle(free_attempts=0)
    throttle.record_failure("a@x.test", source="203.0.113.9")
    with pytest.raises(TooManyAttemptsError):
        throttle.check("a@x.test", source="203.0.113.9")
    throttle.reset()
    throttle.check("a@x.test", source="203.0.113.9")


def test_disabled_throttle_is_inert() -> None:
    throttle = LoginThrottle.disabled(reason="single instance behind a shared WAF limiter")
    assert throttle.enabled is False
    assert "WAF" in throttle.disabled_reason
    for _ in range(50):
        throttle.record_failure("a@x.test", source="203.0.113.9")
    throttle.check("a@x.test", source="203.0.113.9")  # never delays
    throttle.record_success("a@x.test", source="203.0.113.9")  # also a no-op


def test_disabled_requires_a_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        LoginThrottle.disabled(reason="   ")


def test_the_deprecated_alias_still_catches() -> None:
    """``AccountLockedError`` is kept so an existing ``except`` clause keeps compiling."""
    assert AccountLockedError is TooManyAttemptsError
    throttle = LoginThrottle(free_attempts=0)
    throttle.record_failure("a@x.test", source="203.0.113.9")
    with pytest.raises(AccountLockedError):
        throttle.check("a@x.test", source="203.0.113.9")


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"free_attempts": -1}, "free_attempts"),
        ({"base_delay": datetime.timedelta(milliseconds=500)}, "base_delay"),
        (
            {
                "base_delay": datetime.timedelta(seconds=30),
                "max_delay": datetime.timedelta(seconds=10),
            },
            "max_delay",
        ),
        ({"free_attempts": 5, "identifier_attempts": 5}, "identifier_attempts"),
    ],
)
def test_a_misconfigured_throttle_refuses_at_construction(
    kwargs: dict, match: str
) -> None:
    """A mis-tuned control fails at boot, not at the first attempt it mis-handles."""
    with pytest.raises(ValueError, match=match):
        LoginThrottle(**kwargs)


# --------------------------------------------------------------------------- #
# The revocable get_principal provider + its marker
# --------------------------------------------------------------------------- #
def test_build_get_principal_marks_only_the_validated_provider() -> None:
    assert enforces_token_revocation(build_get_principal()) is False
    assert enforces_token_revocation(build_get_principal(token_validator=lambda s, c: True))


def test_validated_provider_rejects_a_token_its_validator_fails() -> None:
    settings.SECRET_KEY = _KEY
    subject = uuid.uuid4()
    token = create_access_token(subject=subject, role=Roles.EDITOR, token_version=2)
    request = _request({"Authorization": f"Bearer {token}"})

    seen: dict[str, int] = {}

    def validator(_session: object, claims) -> bool:  # noqa: ANN001
        seen["tv"] = claims.token_version
        return claims.token_version == 2

    accept = build_get_principal(token_validator=validator)
    assert accept(request, _SESSION) == Principal(id=subject, role=Roles.EDITOR)
    assert seen["tv"] == 2  # the provider handed the validator the decoded claims

    reject = build_get_principal(token_validator=lambda s, c: False)
    assert reject(request, _SESSION) is None  # a failed validator → unauthenticated

    # The stateless provider trusts a validly-signed token (no store lookup); and a
    # missing token is unauthenticated regardless of the validator.
    assert build_get_principal()(request, _SESSION) == Principal(id=subject, role=Roles.EDITOR)
    assert accept(_request(), _SESSION) is None


def test_realtime_validator_rechecks_credential_identity() -> None:
    settings.SECRET_KEY = _KEY
    subject = uuid.uuid4()
    token = create_access_token(subject=subject, role=Roles.EDITOR, token_version=3)
    principal = Principal(id=subject, role=Roles.EDITOR)
    validate = build_realtime_validator()
    assert validate(principal, token) is True
    assert validate(Principal(id=uuid.uuid4(), role=Roles.EDITOR), token) is False
    assert validate(Principal(id=subject, role=Roles.ADMIN), token) is False
    assert validate(principal, "not-a-token") is False
    assert validate(principal, "") is False


def test_realtime_validator_refuses_an_expired_access_token() -> None:
    settings.SECRET_KEY = _KEY
    subject = uuid.uuid4()
    expired = create_access_token(
        subject=subject,
        role=Roles.EDITOR,
        expires_in=datetime.timedelta(seconds=-1),
    )
    validate = build_realtime_validator()
    assert validate(Principal(id=subject, role=Roles.EDITOR), expired) is False


# --------------------------------------------------------------------------- #
# create_app boot guard: require_token_revocation
# --------------------------------------------------------------------------- #
def _probe_spec() -> ModuleSpec:
    return ModuleSpec(
        name="probe", router=APIRouter(), policy=Policy.public(reason="boot-guard probe")
    )


def test_boot_fails_closed_when_revocation_required_but_provider_is_stateless() -> None:
    with pytest.raises(BootError, match="require_token_revocation"):
        create_app([_probe_spec()], require_token_revocation=True)


def test_boot_accepts_a_revocation_enforcing_provider() -> None:
    provider = build_get_principal(token_validator=lambda s, c: True)
    app = create_app(
        [_probe_spec()], principal_provider=provider, require_token_revocation=True
    )
    assert app is not None


# --------------------------------------------------------------------------- #
# token epoch claim round-trip
# --------------------------------------------------------------------------- #
def test_token_version_round_trips_and_old_tokens_decode_to_epoch_zero() -> None:
    settings.SECRET_KEY = _KEY
    subject = uuid.uuid4()
    assert (
        decode_access_token(
            create_access_token(subject=subject, role=Roles.EDITOR, token_version=7)
        ).token_version
        == 7
    )
    assert (
        decode_access_token(
            create_access_token(subject=subject, role=Roles.EDITOR)
        ).token_version
        == 0
    )
    now = datetime.datetime.now(datetime.UTC)
    legacy = jwt.encode(
        {
            "sub": str(subject),
            "role": "editor",
            "rank": 20,
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
            "iat": now,
            "exp": now + datetime.timedelta(minutes=5),
        },
        _KEY,
        algorithm="HS256",
    )
    assert decode_access_token(legacy).token_version == 0  # missing `tv` → 0
