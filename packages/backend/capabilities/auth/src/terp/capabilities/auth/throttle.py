"""Per-account login lockout — a fail-closed brute-force throttle (ADR 0031, L3).

A login-specific complement to the generic rate limiter: it counts *failed* logins per
account and locks the account for a window once a threshold is crossed, so credential
stuffing against a single user is throttled even when the generic rate limit (which
counts all requests from all callers) would not bite.

The lockout state lives in a pluggable :class:`~terp.core.ThrottleStore` (ADR 0036):
the default :class:`~terp.core.InMemoryThrottleStore` is per app instance / in process —
unchanged behaviour — while a multi-instance deployment passes the same shared store the
rate limiter uses, so the lockout is correct across workers. A store error fails closed
(the account is treated as locked). It is on by default; an app turns it off only with
an explicit, reason-bearing :meth:`LoginThrottle.disabled`.
"""

from __future__ import annotations

import datetime
import logging

from terp.core import AppError, InMemoryThrottleStore, ThrottleStore

_logger = logging.getLogger("terp.capabilities.auth.throttle")


class AccountLockedError(AppError):
    """429 — too many failed login attempts; the account is temporarily locked."""

    status_code = 429
    code = "account_locked"
    default_message = (
        "Too many failed login attempts. This account is temporarily locked; "
        "please wait and try again."
    )


def _utc_now() -> datetime.datetime:
    """UTC ``now`` provider — kept private so tests can monkeypatch the clock."""
    return datetime.datetime.now(datetime.UTC)


class LoginThrottle:
    """Per-account failed-login lockout over a pluggable :class:`ThrottleStore`.

    After *max_attempts* failed logins for one identifier within *window*, the
    identifier is locked for *lockout*; while locked, even a correct credential is
    refused (the login route calls :meth:`check` *before* verifying the password). A
    successful login clears the counter. State is keyed by a normalized identifier
    (trimmed + lower-cased) so case variants of an email cannot dodge the count. With no
    *store* the default per-instance in-memory store is used (clocked off :func:`_utc_now`
    so tests can drive it); a multi-instance app passes a shared store for one correct
    global counter.
    """

    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window: datetime.timedelta = datetime.timedelta(minutes=15),
        lockout: datetime.timedelta = datetime.timedelta(minutes=15),
        store: ThrottleStore | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("LoginThrottle.max_attempts must be >= 1")
        self.enabled = True
        self.disabled_reason = ""
        self._max_attempts = max_attempts
        self._window = int(window.total_seconds())
        self._lockout = int(lockout.total_seconds())
        self._store = store if store is not None else InMemoryThrottleStore(
            clock=lambda: _utc_now().timestamp()
        )

    @classmethod
    def disabled(cls, *, reason: str) -> LoginThrottle:
        """An explicitly-disabled throttle (no lockout). *reason* is required (fail-closed).

        Mirrors ``CorsPolicy.disabled`` / ``AuditPolicy.disabled``: turning a
        secure-by-default control off is a visible, justified act, never a silent
        omission, so an empty reason is refused.
        """
        if not reason.strip():
            raise ValueError("LoginThrottle.disabled requires a non-empty reason")
        throttle = cls()
        throttle.enabled = False
        throttle.disabled_reason = reason
        return throttle

    def check(self, identifier: str) -> None:
        """Raise :class:`AccountLockedError` if *identifier* is currently locked."""
        if not self.enabled:
            return
        try:
            locked = self._store.locked(self._key(identifier)) > 0
        except Exception as exc:  # a shared store outage fails closed
            raise AccountLockedError() from exc
        if locked:
            raise AccountLockedError()

    def record_failure(self, identifier: str) -> None:
        """Record a failed attempt; lock *identifier* once the threshold is reached."""
        if not self.enabled:
            return
        key = self._key(identifier)
        try:
            count, _ = self._store.hit(key, self._window)
            if count >= self._max_attempts:
                self._store.lock(key, self._lockout)
        except Exception as exc:  # a shared store outage fails closed
            raise AccountLockedError() from exc

    def record_success(self, identifier: str) -> None:
        """Clear *identifier*'s failure state after a successful login."""
        if not self.enabled:
            return
        try:
            self._store.clear(self._key(identifier))
        except Exception as exc:  # best-effort cleanup: never block an already-valid login
            _logger.warning("login_throttle_clear_failed", exc_info=exc)

    def reset(self) -> None:
        """Clear all tracked state (a test seam; per-instance state otherwise persists)."""
        reset = getattr(self._store, "reset", None)
        if callable(reset):
            reset()

    @staticmethod
    def _key(identifier: str) -> str:
        return f"lt:{identifier.strip().lower()}"


__all__ = ["AccountLockedError", "LoginThrottle"]
