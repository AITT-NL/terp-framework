"""Failed-credential backoff — brute force is slowed, an account is never disabled.

A credential-specific complement to the generic rate limiter, which counts all requests
from all callers and so never bites on a patient guesser working one account.

**This used to be a lockout, and the lockout was a weapon.** Five failures disabled an
identifier for fifteen minutes, and while it was disabled *a correct password was
refused too*. That is the property that makes a lockout attackable rather than
defensive: anybody who knows an email address could take its owner offline on demand,
indefinitely, by failing five logins every quarter of an hour. The control aimed at an
attacker was reachable by the attacker and pointed at the user.

What replaces it is **exponential backoff on the attempt**, not a state on the account.
A caller that keeps failing waits longer and longer before another attempt is looked at;
nothing is ever marked unusable, and the moment a wait elapses a correct credential
works. The costs land on the two parties very differently, which is the whole design:

* a person who mistypes twice notices nothing, and on the third notices two seconds;
* a guesser doubles its wait with every attempt and is quickly spending minutes per try.

**The backoff is keyed by (identifier, source), not by identifier alone.** This is the
part that disarms the weapon. An attacker hammering an address from their own network
slows *themselves* down; the account's real owner, arriving from somewhere else, has a
counter of zero and is unaffected. Under the old lockout both parties shared one piece
of state, so one could always spend it on the other.

A distributed guesser spreading attempts across many sources would sail past a purely
per-source control, so an identifier-wide backstop remains — but tuned so that it is a
poor lever rather than a good one. It needs **fifty** failures to engage and then costs
**five minutes**, against the old five failures for fifteen. That is ten times the work
for a third of the effect, and it heals on its own; an account is still never disabled.
Both numbers are arguable and both are constructor arguments.

State lives in the pluggable :class:`~terp.core.ThrottleStore` (ADR 0036): the default
in-memory store is per process, while a multi-instance deployment passes the shared store
the rate limiter uses so the counters are correct across workers. A store error fails
closed (the attempt is refused). The control is on by default; an app turns it off only
through an explicit, reason-bearing :meth:`LoginThrottle.disabled`.
"""

from __future__ import annotations

import datetime
import logging

from terp.core import AppError, InMemoryThrottleStore, ThrottleStore

_logger = logging.getLogger("terp.capabilities.auth.throttle")


class TooManyAttemptsError(AppError):
    """429 — too many failed attempts recently; wait, then try again.

    Deliberately says *wait*, not *locked*. Nothing has been disabled and nobody needs to
    contact support: the next attempt after the backoff elapses is accepted on its merits.
    The remaining wait goes to ``log_context`` and not to the client — telling a caller
    exactly how long they have left is telling a guesser precisely how hard they are being
    slowed, which is the one audience that can act on it.
    """

    status_code = 429
    code = "too_many_attempts"
    default_message = (
        "Too many failed attempts. Please wait a moment and try again."
    )


#: Deprecated alias for :class:`TooManyAttemptsError`, kept so an existing ``except
#: AccountLockedError`` keeps compiling. The name is wrong now in a way that matters —
#: no account is locked — and the wire ``code`` has changed with it, so a client
#: dispatching on ``"account_locked"`` must move to ``"too_many_attempts"``.
AccountLockedError = TooManyAttemptsError


def _utc_now() -> datetime.datetime:
    """UTC ``now`` provider — kept private so tests can monkeypatch the clock."""
    return datetime.datetime.now(datetime.UTC)


class LoginThrottle:
    """Exponential backoff on failed credential attempts, over a pluggable store.

    The first *free_attempts* failures from one ``(identifier, source)`` pair cost
    nothing — people mistype. Each failure after that sets a backoff of
    ``base_delay * 2 ** n``, capped at *max_delay*, during which another attempt from
    that pair is refused before the password is verified. A success clears the pair.

    *identifier_attempts* failures for one identifier **from any source** within *window*
    engage the identifier-wide backstop for *max_delay*. It is set high on purpose: it is
    the only piece of state an attacker can spend on somebody else, so it should be
    expensive to reach and cheap to recover from.

    Identifiers are normalized (trimmed, lower-cased) so case variants of an email cannot
    dodge the count. *source* is the caller's address where the route knows one; passing
    ``None`` collapses to identifier-only backoff, which is correct for a caller whose
    identifier already carries the source.
    """

    def __init__(
        self,
        *,
        free_attempts: int = 2,
        base_delay: datetime.timedelta = datetime.timedelta(seconds=2),
        max_delay: datetime.timedelta = datetime.timedelta(minutes=5),
        window: datetime.timedelta = datetime.timedelta(minutes=15),
        identifier_attempts: int = 50,
        store: ThrottleStore | None = None,
    ) -> None:
        if free_attempts < 0:
            raise ValueError("LoginThrottle.free_attempts must be >= 0")
        if base_delay.total_seconds() < 1:
            raise ValueError("LoginThrottle.base_delay must be at least one second")
        if max_delay < base_delay:
            raise ValueError("LoginThrottle.max_delay must be >= base_delay")
        if identifier_attempts <= free_attempts:
            raise ValueError(
                "LoginThrottle.identifier_attempts must exceed free_attempts; the "
                "identifier-wide backstop is meant to sit far above the per-caller one"
            )
        self.enabled = True
        self.disabled_reason = ""
        self._free_attempts = free_attempts
        self._base_delay = int(base_delay.total_seconds())
        self._max_delay = int(max_delay.total_seconds())
        self._window = int(window.total_seconds())
        self._identifier_attempts = identifier_attempts
        self._store = store if store is not None else InMemoryThrottleStore(
            clock=lambda: _utc_now().timestamp()
        )

    @classmethod
    def disabled(cls, *, reason: str) -> LoginThrottle:
        """An explicitly-disabled throttle (no backoff). *reason* is required (fail-closed).

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

    def check(self, identifier: str, *, source: str | None = None) -> None:
        """Refuse the attempt if this caller — or this identifier — is still in backoff.

        Called *before* the credential is verified, which is half the point: a refused
        attempt must not reach the password hash. Verification is deliberately expensive
        (a memory-hard KDF, and equally expensive on the miss path so it cannot be used
        as an oracle), so an endpoint that hashes before it throttles is an unauthenticated
        way to spend the server's CPU and memory whatever the credentials are.
        """
        if not self.enabled:
            return
        try:
            remaining = max(
                self._store.locked(self._pair_key(identifier, source)),
                self._store.locked(self._identifier_key(identifier)),
            )
        except Exception as exc:  # a shared store outage fails closed
            raise TooManyAttemptsError() from exc
        if remaining > 0:
            raise TooManyAttemptsError(
                log_context={"retry_after_seconds": remaining}
            )

    def record_failure(self, identifier: str, *, source: str | None = None) -> None:
        """Count one failed attempt and extend this caller's backoff.

        Both counters advance on every failure: the pair's, which is what actually slows
        a guesser, and the identifier's, which only matters once a guess arrives from
        enough different places to look distributed.
        """
        if not self.enabled:
            return
        try:
            pair_failures, _ = self._store.hit(
                self._pair_key(identifier, source), self._window
            )
            if pair_failures > self._free_attempts:
                self._store.lock(
                    self._pair_key(identifier, source),
                    self._backoff_seconds(pair_failures),
                )
            identifier_failures, _ = self._store.hit(
                self._identifier_key(identifier), self._window
            )
            if identifier_failures >= self._identifier_attempts:
                self._store.lock(self._identifier_key(identifier), self._max_delay)
        except Exception as exc:  # a shared store outage fails closed
            raise TooManyAttemptsError() from exc

    def record_success(self, identifier: str, *, source: str | None = None) -> None:
        """Clear both counters after a verified credential."""
        if not self.enabled:
            return
        try:
            self._store.clear(self._pair_key(identifier, source))
            self._store.clear(self._identifier_key(identifier))
        except Exception as exc:  # best-effort cleanup: never block an already-valid login
            _logger.warning("login_throttle_clear_failed", exc_info=exc)

    def reset(self) -> None:
        """Clear all tracked state (a test seam; per-instance state otherwise persists)."""
        reset = getattr(self._store, "reset", None)
        if callable(reset):
            reset()

    def _backoff_seconds(self, failures: int) -> int:
        """The wait after *failures* failures: doubling from ``base_delay``, capped.

        The exponent is bounded on both sides before the shift. Above, because
        ``2 ** failures`` on a counter an attacker drives is an arbitrarily large
        integer built on the request path — the cap makes the result right, but only
        after the machine has done the work. Below, because a negative exponent makes
        ``2 ** steps`` a *float*, and this value goes on to be a lock duration: the
        caller guards against it today, so the floor is a guard against the next
        caller rather than this one.
        """
        steps = min(max(failures - self._free_attempts - 1, 0), 32)
        return min(self._base_delay * (2**steps), self._max_delay)

    @staticmethod
    def _normalized(identifier: str) -> str:
        return identifier.strip().lower()

    @classmethod
    def _pair_key(cls, identifier: str, source: str | None) -> str:
        """The per-caller counter's key.

        A source-less caller gets a literal ``-`` rather than falling back to the
        identifier key. Sharing one key would make ``record_failure`` count the same
        failure twice into the same counter and reach the backstop at half the stated
        number — the kind of bug that looks like nothing and silently doubles the
        strength of the one control an attacker can aim at somebody else.
        """
        return f"lt:p:{cls._normalized(identifier)}:{source if source is not None else '-'}"

    @classmethod
    def _identifier_key(cls, identifier: str) -> str:
        return f"lt:i:{cls._normalized(identifier)}"


__all__ = ["AccountLockedError", "LoginThrottle", "TooManyAttemptsError"]
