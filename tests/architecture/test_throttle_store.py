"""Distributed throttle-store seam (ADR 0036): shared backend, fail-closed, default unchanged.

Covers the kernel-side of the quadruple: the in-memory default's window/lock semantics, a
shared store driving both the rate limiter and the login throttle, the fail-closed branch
(a raising store denies), and the ``create_app(throttle_store=…)`` wiring.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from terp.core import (
    AuditPolicy,
    ControlPlane,
    CorsPolicy,
    InMemoryThrottleStore,
    ModuleSpec,
    Policy,
    SecurityConfig,
    ThrottleStore,
    create_app,
    mark_shared_throttle_store,
    settings,
)
from terp.core._internal.middleware import RateLimitMiddleware
from terp.capabilities.auth import AccountLockedError, LoginThrottle


class _RaisingStore(ThrottleStore):
    """A store whose every op fails — to prove callers fail closed, never open."""

    def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        raise RuntimeError("backend down")

    def lock(self, key: str, seconds: int) -> None:
        raise RuntimeError("backend down")

    def locked(self, key: str) -> int:
        raise RuntimeError("backend down")

    def clear(self, key: str) -> None:
        raise RuntimeError("backend down")


class _PassThrough(ThrottleStore):
    """Exercises the abstract bodies via ``super()`` (they are no-ops/None)."""

    def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        super().hit(key, window_seconds)
        return 1, 1

    def lock(self, key: str, seconds: int) -> None:
        super().lock(key, seconds)

    def locked(self, key: str) -> int:
        super().locked(key)
        return 0

    def clear(self, key: str) -> None:
        super().clear(key)


def _starlette_app() -> Starlette:
    async def ok(_request: object) -> PlainTextResponse:
        return PlainTextResponse("ok")

    return Starlette(routes=[Route("/", ok)])


# --------------------------------------------------------------------------- #
# InMemoryThrottleStore — the safe default
# --------------------------------------------------------------------------- #
def test_in_memory_counter_window_and_lock_lifecycle() -> None:
    now = [0.0]
    store = InMemoryThrottleStore(clock=lambda: now[0])
    assert store.hit("k", 60) == (1, 60)
    assert store.hit("k", 60)[0] == 2
    now[0] = 60  # window rolls over
    assert store.hit("k", 60)[0] == 1
    store.lock("k", 30)
    assert store.locked("k") == 30
    now[0] = 91  # lock expired
    assert store.locked("k") == 0
    assert store.locked("absent") == 0


def test_clear_drops_counter_and_lock() -> None:
    store = InMemoryThrottleStore()
    store.hit("k", 60)
    store.lock("k", 60)
    store.clear("k")
    assert store.locked("k") == 0


def test_abstract_bodies_are_callable() -> None:
    store = _PassThrough()
    assert store.hit("k", 1) == (1, 1)
    store.lock("k", 1)
    assert store.locked("k") == 0
    store.clear("k")


# --------------------------------------------------------------------------- #
# One shared store drives both controls (multi-instance correctness)
# --------------------------------------------------------------------------- #
def test_shared_store_serves_rate_limit_and_throttle_without_key_collision() -> None:
    shared = InMemoryThrottleStore()
    throttle = LoginThrottle(max_attempts=2, store=shared)
    throttle.record_failure("a@x.test")
    throttle.record_failure("a@x.test")  # locks "lt:a@x.test"
    with pytest.raises(AccountLockedError):
        throttle.check("a@x.test")
    # The rate limiter keys "rl:*": shares the backend, no collision.
    count, _ = shared.hit("rl:1.2.3.4", 60)
    assert count == 1


# --------------------------------------------------------------------------- #
# Fail-closed: a store outage denies, never silently allows
# --------------------------------------------------------------------------- #
def test_rate_limiter_fails_closed_on_store_error() -> None:
    app = _starlette_app()
    app.add_middleware(RateLimitMiddleware, limit=100, window=60, store=_RaisingStore())
    assert TestClient(app).get("/").status_code == 429


def test_throttle_fails_closed_on_store_error() -> None:
    throttle = LoginThrottle(store=_RaisingStore())
    with pytest.raises(AccountLockedError):
        throttle.check("a@x.test")
    with pytest.raises(AccountLockedError):
        throttle.record_failure("a@x.test")
    throttle.record_success("a@x.test")  # best-effort cleanup never blocks a valid login


def test_throttle_reset_is_noop_for_a_store_without_reset() -> None:
    LoginThrottle(store=_RaisingStore()).reset()  # no AttributeError, no-op


# --------------------------------------------------------------------------- #
# create_app wires the seam (default unchanged)
# --------------------------------------------------------------------------- #
def test_create_app_accepts_a_shared_store() -> None:
    seen: list[str] = []

    class _SpyStore(InMemoryThrottleStore):
        def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
            seen.append(key)
            return super().hit(key, window_seconds)

    router = APIRouter()

    @router.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "1"}

    spec = ModuleSpec(name="probe", router=router, policy=Policy.public(reason="probe"))
    client = TestClient(create_app([spec], throttle_store=_SpyStore()))
    assert client.get("/api/v1/probe/ping").headers["X-RateLimit-Limit"] == "240"
    assert seen == ["rl::testclient"]  # the supplied store actually counted the request


# --------------------------------------------------------------------------- #
# Production states the property it is actually running with
# --------------------------------------------------------------------------- #
def _warning_spec() -> ModuleSpec:
    router = APIRouter()

    @router.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "1"}

    return ModuleSpec(name="probe", router=router, policy=Policy.public(reason="probe"))


def _prod_plane() -> ControlPlane:
    # Security and audit made explicitly production-safe so the throttle store is the
    # only seam that can produce output — isolating the control under test.
    return ControlPlane(
        security=SecurityConfig(cors=CorsPolicy.disabled(reason="api only")),
        audit=AuditPolicy.disabled(reason="trail not required for this probe"),
    )


def test_production_says_out_loud_that_the_throttle_is_per_worker(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The opt-in guard is right; its absence must not be silent (the idempotency case).

    A per-instance store is *correct* for a single production instance, so boot cannot
    refuse it. What it can do is state the property: on a second replica the request
    cap and the per-account failed-login threshold are both multiplied by the worker
    count, and nothing about that is observable until someone is counting attempts.
    """
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with caplog.at_level("WARNING", logger="terp.core"):
        create_app([_warning_spec()], control_plane=_prod_plane())
    message = "\n".join(record.getMessage() for record in caplog.records)
    assert "counted PER WORKER" in message
    # Both promises are named, because a reader who only hears "rate limit" will not
    # connect the line to the lockout, which is the one that matters more.
    assert "login lockout" in message
    # And the way out, not just the condition.
    assert "require_shared_throttle_store=True" in message


def test_a_shared_throttle_store_in_production_warns_about_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A deployment that already holds the guarantee must not be nagged about it."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    shared = mark_shared_throttle_store(InMemoryThrottleStore())
    with caplog.at_level("WARNING", logger="terp.core"):
        create_app([_warning_spec()], throttle_store=shared, control_plane=_prod_plane())
    assert "counted PER WORKER" not in "\n".join(r.getMessage() for r in caplog.records)


def test_declaring_the_requirement_also_silences_the_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``require_shared_throttle_store=True`` is the boot-time guarantee, not a second warning.

    Reaching the warning at all would mean the guard above had let an unshared store
    through, so the two controls have to agree: once the requirement is declared, this
    line has nothing left to say.
    """
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    shared = mark_shared_throttle_store(InMemoryThrottleStore())
    with caplog.at_level("WARNING", logger="terp.core"):
        create_app(
            [_warning_spec()],
            throttle_store=shared,
            require_shared_throttle_store=True,
            control_plane=_prod_plane(),
        )
    assert "counted PER WORKER" not in "\n".join(r.getMessage() for r in caplog.records)


def test_development_is_not_warned_about_a_deployment_property(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Local runs are single-process by definition; the warning would be pure noise."""
    with caplog.at_level("WARNING", logger="terp.core"):
        create_app([_warning_spec()])
    assert "counted PER WORKER" not in "\n".join(r.getMessage() for r in caplog.records)
