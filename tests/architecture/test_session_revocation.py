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
    LoginThrottle,
    build_get_principal,
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
# LoginThrottle — the per-account lockout state machine
# --------------------------------------------------------------------------- #
def test_throttle_allows_under_the_threshold() -> None:
    throttle = LoginThrottle(max_attempts=3)
    throttle.record_failure("a@x.test")
    throttle.record_failure("a@x.test")
    throttle.check("a@x.test")  # 2 < 3 → no lock


def test_throttle_locks_at_the_threshold_and_refuses_even_a_valid_credential() -> None:
    throttle = LoginThrottle(max_attempts=3)
    for _ in range(3):
        throttle.check("a@x.test")
        throttle.record_failure("a@x.test")
    with pytest.raises(AccountLockedError):
        throttle.check("a@x.test")


def test_throttle_success_clears_the_counter() -> None:
    throttle = LoginThrottle(max_attempts=3)
    throttle.record_failure("a@x.test")
    throttle.record_failure("a@x.test")
    throttle.record_success("a@x.test")
    # Counter reset: two fresh failures are again under the threshold.
    throttle.record_failure("a@x.test")
    throttle.record_failure("a@x.test")
    throttle.check("a@x.test")


def test_throttle_normalizes_the_identifier() -> None:
    throttle = LoginThrottle(max_attempts=1)
    throttle.record_failure("  USER@X.test ")
    with pytest.raises(AccountLockedError):
        throttle.check("user@x.test")


def test_throttle_lock_expires_after_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    now = _at(monkeypatch)
    throttle = LoginThrottle(
        max_attempts=2,
        window=datetime.timedelta(minutes=10),
        lockout=datetime.timedelta(minutes=5),
    )
    throttle.record_failure("a@x.test")
    throttle.record_failure("a@x.test")
    with pytest.raises(AccountLockedError):
        throttle.check("a@x.test")
    now[0] += datetime.timedelta(minutes=6)  # past the lockout
    throttle.check("a@x.test")  # cleared → allowed again


def test_throttle_window_resets_stale_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    now = _at(monkeypatch)
    throttle = LoginThrottle(
        max_attempts=3,
        window=datetime.timedelta(minutes=10),
        lockout=datetime.timedelta(minutes=5),
    )
    throttle.record_failure("a@x.test")
    throttle.record_failure("a@x.test")
    now[0] += datetime.timedelta(minutes=11)  # the window lapsed
    throttle.record_failure("a@x.test")  # starts a fresh window (count = 1)
    throttle.check("a@x.test")  # not locked


def test_throttle_reset_clears_all_state() -> None:
    throttle = LoginThrottle(max_attempts=1)
    throttle.record_failure("a@x.test")
    with pytest.raises(AccountLockedError):
        throttle.check("a@x.test")
    throttle.reset()
    throttle.check("a@x.test")


def test_disabled_throttle_is_inert() -> None:
    throttle = LoginThrottle.disabled(reason="single instance behind a shared WAF limiter")
    assert throttle.enabled is False
    assert "WAF" in throttle.disabled_reason
    for _ in range(50):
        throttle.record_failure("a@x.test")
    throttle.check("a@x.test")  # never locks
    throttle.record_success("a@x.test")  # also a no-op


def test_disabled_requires_a_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        LoginThrottle.disabled(reason="   ")


def test_throttle_rejects_a_nonpositive_threshold() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        LoginThrottle(max_attempts=0)


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
