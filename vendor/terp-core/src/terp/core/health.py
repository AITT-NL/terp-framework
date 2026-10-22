"""Built-in health endpoints for orchestrators and load balancers (ADR 0024, ADR 0191).

``create_app`` mounts these at ``/health`` — **public** (no token, outside the
policy guard), so a Kubernetes / load-balancer probe can always reach them. Note
that probes still pass through the application's middleware stack (CORS, rate
limiting, and capability middleware), but do not require authentication.

* ``GET /health/live`` — *liveness*: the process is up and serving. No dependency
  is checked, so a transient database blip never restarts an otherwise-healthy pod.
* ``GET /health/ready`` — *readiness*: the app can serve traffic. The database is
  reachable (a cheap ``SELECT 1`` through the same ``SessionDep`` seam the app uses, so
  tests and overrides apply), and so is **every shared store this deployment made
  mandatory** (ADR 0191): a store a ``require_shared_*`` guard requires is one without
  which this instance cannot do what it promised, so it is part of the answer. Returns
  200 when every check passes, 503 otherwise, so a load balancer withholds traffic until
  the dependency recovers. Workers and schedulers are deliberately **not** part of it:
  an undrained queue does not make this instance unable to serve, and failing readiness on
  it would turn a delivery problem into an outage. They report through a heartbeat of
  their own (``terp guide jobs``).
* ``GET /health/detail`` — *observation*: everything a registered capability can say
  about itself, and **never** a verdict. **Opt-in**, and mounted only when
  ``create_app(expose_health_detail=True)`` asks for it. See
  :func:`register_health_detail`.

**A store probe is bounded.** Each is asked through its own ``ping()`` on a worker
thread, given :data:`READINESS_PROBE_TIMEOUT_SECONDS` to answer, and asked again only once
its previous probe has returned: a store that accepts connections and never answers makes
readiness say ``error`` within the bound instead of holding the probe, and cannot pile up a
thread per probe while it hangs.

The detail surface exists because of a shape the platform had in its own capability:
a durable queue with no consumer running looks exactly like a durable queue with idle
consumers — a table of pending rows either way — and nothing anywhere reported the
difference. That is not a readiness question (an undrained queue does not make this
instance unable to serve traffic, and failing readiness on it would turn a delivery
problem into an outage), so it gets a surface of its own where a monitor can watch it.

It is off by default because **this whole router is public**: it is mounted outside
the policy guard so an orchestrator probe can always reach it, and ``terp.core`` sits
below every authentication capability, so there is nothing here to gate it with. Queue
depths and timestamps are business signal — volume, activity, when work stopped — and
an unauthenticated endpoint is the wrong place for them by default. Enable it where
``/health`` is already restricted to an internal network or an ingress rule, and use
``terp outbox backlog`` everywhere else: the CLI reports the same numbers from the
same function, through the operator's own credentials.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from threading import Lock
from typing import Final

import anyio
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from terp.core.db import SessionDep

_logger = logging.getLogger("terp.core.health")

#: A health detail: given a session, describe your own state as JSON-safe data.
#: It answers "what is true right now", never "should this instance serve traffic".
HealthDetail = Callable[[Session], object]

#: A readiness probe: returns when its dependency answers, raises when it does not.
ReadinessProbe = Callable[[], object]

#: How long readiness waits for one store's probe before it calls that store unreachable.
#: Under the five seconds an orchestrator's probe commonly allows, and the probes of
#: several stores run side by side, so the whole answer stays inside it.
READINESS_PROBE_TIMEOUT_SECONDS: Final[float] = 2.0

_details: dict[str, HealthDetail] = {}

#: Capability stores readiness asks about whenever their capability says they are mandatory.
_mandatory_stores: dict[str, Callable[[], ReadinessProbe | None]] = {}


def register_health_detail(name: str, detail: HealthDetail) -> None:
    """Register *detail* under *name*, reported by ``GET /health/detail``.

    For a fact about a capability that an operator or a monitor needs and no other
    surface carries — a queue's backlog, a consumer's last heartbeat. Registration is
    idempotent per name and refuses a second, different registration under the same
    name, so two capabilities cannot silently overwrite each other's report.

    A detail is deliberately NOT part of readiness. Readiness answers "route traffic
    here", and a growing backlog is a reason to page someone rather than to take this
    instance out of the load balancer — doing the latter would convert a delivery
    problem into an outage, which is the failure mode this seam is meant to expose,
    not to cause.
    """
    existing = _details.get(name)
    if existing is not None and existing is not detail:
        raise ValueError(f"health detail {name!r} is already registered")
    _details[name] = detail


def health_details() -> dict[str, HealthDetail]:
    """Every registered detail, in name order (a stable order for tests and output)."""
    return {name: _details[name] for name in sorted(_details)}


def reset_health_details() -> None:
    """Clear the registry (a test seam; owners re-register at import).

    Deliberately NOT a per-app runtime seam, for the reason the lease reaper registry
    is not one either: this is a CAPABILITY registration, made once at import by the
    package that owns the fact. Resetting it between apps would delete a registration
    nothing re-runs, and the surface would then report an empty set on a process where
    the capability is installed and working.
    """
    _details.clear()


def register_mandatory_store(
    name: str, mandatory: Callable[[], ReadinessProbe | None]
) -> None:
    """Register a capability's shared store, part of readiness whenever it is mandatory.

    For a store a capability configures outside ``create_app`` (the realtime broker, which
    ``configure_realtime(require_shared_broker=True)`` makes mandatory). *mandatory* is asked
    on every readiness probe: it returns the store's probe while this deployment requires
    the store, and ``None`` while it does not, so the promise and the check cannot drift.
    The kernel's own stores are not registered here; ``create_app`` derives them from its
    ``require_shared_*`` arguments. Idempotent per name; a second, different registration
    under one name is refused, as :func:`register_health_detail` refuses one.
    """
    existing = _mandatory_stores.get(name)
    if existing is not None and existing is not mandatory:
        raise ValueError(f"mandatory store {name!r} is already registered")
    _mandatory_stores[name] = mandatory


def mandatory_stores() -> dict[str, Callable[[], ReadinessProbe | None]]:
    """Every registered capability store, in name order."""
    return {name: _mandatory_stores[name] for name in sorted(_mandatory_stores)}


def reset_mandatory_stores() -> None:
    """Clear the capability-store registry (a test seam, like :func:`reset_health_details`)."""
    _mandatory_stores.clear()


class _BoundedProbe:
    """One store readiness asks about: on a worker thread, within a bound, one ask at a time.

    A store that never answers must not hold the readiness answer, and must not cost a thread
    per probe while it hangs: the thread of a probe that ran past the bound is abandoned, and
    until it returns every later ask is answered "not ready" at once, without a new thread.
    """

    def __init__(self, name: str, timeout: float) -> None:
        self.name = name
        self._timeout = timeout
        self._lock = Lock()
        self._running = False

    def _call(self, probe: ReadinessProbe) -> None:
        with self._lock:
            self._running = True
        try:
            probe()
        finally:
            with self._lock:
                self._running = False

    async def passes(self, probe: ReadinessProbe) -> bool:
        with self._lock:
            running = self._running
        if running:
            _logger.error(
                "readiness check %r failed: its previous probe has not answered yet", self.name
            )
            return False
        try:
            with anyio.fail_after(self._timeout):
                await anyio.to_thread.run_sync(self._call, probe, abandon_on_cancel=True)
        except TimeoutError:
            _logger.error(
                "readiness check %r failed: no answer within %.1fs", self.name, self._timeout
            )
            return False
        except Exception as exc:
            _logger.error("readiness check %r failed", self.name, exc_info=exc)
            return False
        return True


def _database_answers(session: Session) -> bool:
    """The database check of ADR 0024: ``SELECT 1`` through the app's own session seam."""
    try:
        session.exec(select(1)).one()
    except Exception as exc:
        # Any failure to reach the database means "not ready" — report it so the
        # load balancer routes around this instance until it recovers.
        _logger.error("database readiness check failed", exc_info=exc)
        return False
    return True


def build_health_router(
    *,
    expose_detail: bool = False,
    readiness: Mapping[str, ReadinessProbe] | None = None,
    probe_timeout: float = READINESS_PROBE_TIMEOUT_SECONDS,
) -> APIRouter:
    """Build the ``/health`` router (liveness + readiness, and optionally detail).

    *expose_detail* mounts ``GET /health/detail``. Off by default: this router is
    public by design, and the details a capability registers are business signal.
    *readiness* names the shared stores this app made mandatory, each with its probe
    (``create_app`` passes one per ``require_shared_*`` it was given); every capability
    store registered with :func:`register_mandatory_store` joins them while it is
    mandatory. *probe_timeout* bounds each store's probe.
    """
    router = APIRouter(tags=["health"])
    app_stores = dict(readiness or {})
    bounded: dict[str, _BoundedProbe] = {}

    def _bounded(name: str) -> _BoundedProbe:
        if name not in bounded:
            bounded[name] = _BoundedProbe(name, probe_timeout)
        return bounded[name]

    @router.get("/live")
    def live() -> dict[str, str]:
        """Liveness: the process is up. No dependency is checked."""
        return {"status": "alive"}

    async def _ask_all(stores: dict[str, ReadinessProbe]) -> dict[str, bool]:
        """Ask every store at once, each within its bound, on the event loop's own threads."""
        passed: dict[str, bool] = {}

        async def _ask(name: str, probe: ReadinessProbe) -> None:
            passed[name] = await _bounded(name).passes(probe)

        async with anyio.create_task_group() as group:
            for name, probe in stores.items():
                group.start_soon(_ask, name, probe)
        return passed

    @router.get("/ready")
    def ready(session: SessionDep) -> JSONResponse:
        """Readiness: 200 when the database and every mandatory store answer, else 503.

        A plain function, so the database is asked exactly as ADR 0024 asks it: on the
        request's own session, in the worker thread that serves the request. The stores are
        then asked together from the event loop, each on a thread of its own.
        """
        stores = dict(app_stores)
        for name, mandatory in mandatory_stores().items():
            probe = mandatory()
            if probe is not None:
                stores[name] = probe
        database = _database_answers(session)
        passed: dict[str, bool] = {}
        if stores:
            # The request's session is closed after the response, on whichever worker
            # thread is free then, and asking the stores frees several: give its
            # connection back here, on the thread that took it (SQLite holds one per
            # thread and refuses it anywhere else).
            session.close()
            passed = anyio.from_thread.run(_ask_all, stores)
        checks = {"database": "ok" if database else "error"}
        checks.update(
            (name, "ok" if passed[name] else "error") for name in sorted(passed)
        )
        ok = database and all(passed.values())
        return JSONResponse(
            status_code=200 if ok else 503,
            content={"status": "ready" if ok else "not_ready", "checks": checks},
        )

    if expose_detail:

        @router.get("/detail")
        def detail(session: SessionDep) -> JSONResponse:
            """What each registered capability says about itself. Always 200.

            Always 200 because this is an observation and not a verdict: a monitor
            reads the numbers and decides. One detail that raises is reported as an
            error in its own slot and does not suppress the others — a broken probe
            must not blind the operator to every working one, which is the same
            failure this surface exists to remove.
            """
            reported: dict[str, object] = {}
            for name, probe in health_details().items():
                try:
                    reported[name] = probe(session)
                except Exception as exc:
                    _logger.error("health detail %r failed", name, exc_info=exc)
                    # The probes share one session, and on PostgreSQL a failed
                    # statement aborts the transaction: without this rollback the
                    # FIRST failure would make every probe after it fail too, which
                    # is exactly the blinding this handler claims to prevent.
                    try:
                        session.rollback()
                    except Exception:  # pragma: no cover - a dead session
                        _logger.error("health detail session rollback failed")
                    reported[name] = {"error": "unavailable"}
            return JSONResponse(status_code=200, content={"details": reported})

    return router


__all__ = [
    "READINESS_PROBE_TIMEOUT_SECONDS",
    "HealthDetail",
    "ReadinessProbe",
    "build_health_router",
    "health_details",
    "mandatory_stores",
    "register_health_detail",
    "register_mandatory_store",
    "reset_health_details",
    "reset_mandatory_stores",
]
