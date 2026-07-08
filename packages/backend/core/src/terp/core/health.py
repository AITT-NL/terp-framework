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
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlmodel import select

from terp.core.db import SessionDep

_logger = logging.getLogger("terp.core.health")


def build_health_router() -> APIRouter:
    """Build the ``/health`` router (liveness + readiness)."""
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

    return router


__all__ = ["build_health_router"]
