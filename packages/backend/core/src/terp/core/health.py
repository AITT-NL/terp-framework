"""Built-in health endpoints for orchestrators and load balancers (ADR 0024).

``create_app`` mounts these at ``/health`` — **public** (no token, outside the
policy guard), so a Kubernetes / load-balancer probe can always reach them. Note
that probes still pass through the application's middleware stack (CORS, rate
limiting, and capability middleware), but do not require authentication.

* ``GET /health/live`` — *liveness*: the process is up and serving. No dependency
  is checked, so a transient database blip never restarts an otherwise-healthy pod.
* ``GET /health/ready`` — *readiness*: the app can serve traffic — the database is
  reachable (a cheap ``SELECT 1`` through the same ``SessionDep`` seam the app
  uses, so tests and overrides apply). Returns 200 when ready, 503 otherwise, so a
  load balancer withholds traffic until the dependency recovers.
* ``GET /health/detail`` — *observation*: everything a registered capability can say
  about itself, and **never** a verdict. **Opt-in**, and mounted only when
  ``create_app(expose_health_detail=True)`` asks for it. See
  :func:`register_health_detail`.

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
from collections.abc import Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from terp.core.db import SessionDep

_logger = logging.getLogger("terp.core.health")

#: A health detail: given a session, describe your own state as JSON-safe data.
#: It answers "what is true right now", never "should this instance serve traffic".
HealthDetail = Callable[[Session], object]

_details: dict[str, HealthDetail] = {}


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


def build_health_router(*, expose_detail: bool = False) -> APIRouter:
    """Build the ``/health`` router (liveness + readiness, and optionally detail).

    *expose_detail* mounts ``GET /health/detail``. Off by default: this router is
    public by design, and the details a capability registers are business signal.
    """
    router = APIRouter(tags=["health"])

    @router.get("/live")
    def live() -> dict[str, str]:
        """Liveness: the process is up. No dependency is checked."""
        return {"status": "alive"}

    @router.get("/ready")
    def ready(session: SessionDep) -> JSONResponse:
        """Readiness: 200 when the database answers ``SELECT 1``, else 503."""
        try:
            session.exec(select(1)).one()
        except Exception as exc:
            # Any failure to reach the database means "not ready" — report it so the
            # load balancer routes around this instance until it recovers.
            _logger.error("database readiness check failed", exc_info=exc)
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "checks": {"database": "error"}},
            )
        return JSONResponse(
            status_code=200,
            content={"status": "ready", "checks": {"database": "ok"}},
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
    "HealthDetail",
    "build_health_router",
    "health_details",
    "register_health_detail",
    "reset_health_details",
]
