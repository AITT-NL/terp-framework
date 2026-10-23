"""The records a request writes: its access line, its guard decision, its error.

:class:`AccessLogMiddleware` writes **one** ``http.access`` line per HTTP request, once
the response has gone: the method, the route *template* (never the raw path, which holds
ids and sometimes a query-string token), the status, the duration, the request id and,
when the request was authenticated, the actor and tenant. It sits just inside the
request-id middleware, so the line carries the request's correlation id.

The guard does not write a line of its own for such a request: it notes its decision —
which policy, which rule, the outcome — on the request (:func:`note_guard_decision`), and
the access line carries it. Every allow and every deny is therefore in the log at the
access line's level, for the price of no extra line. A connection without an access line
(a WebSocket) gets the decision as its own ``guard.decision`` record instead: a deny at
INFO, an allow at DEBUG.

An error is written once, by the envelope's exception handlers
(:func:`terp.core.app.register_error_handlers`): an ``AppError`` as one ``error.app``
record with its code, status and redacted ``log_context``, an unexpected exception as one
``error.unhandled`` record with its redacted traceback.

None of this ever breaks a request: a failure to record is reported as a
``log.failure`` record, and the response goes out as it would have.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from terp.core._log_capture import mark_logged
from terp.core.logging import active_log_tenant, log_fields, request_id_ctx

#: The scope key the access middleware keeps the request's notes under.
ACCESS_SCOPE_KEY: Final[str] = "terp.access"

#: The status written when the client went away before any response started (nginx's
#: convention for "client closed request"; nothing was sent, so no real status exists).
CLIENT_CLOSED: Final[int] = 499

_access_logger = logging.getLogger("terp.access")
_guard_logger = logging.getLogger("terp.guard")
_error_logger = logging.getLogger("terp.errors")
# The unexpected-exception record has always been written on the kernel's own logger;
# a reader may already key on it, so it keeps it.
_unhandled_logger = logging.getLogger("terp.core")

# The rule that decided, for the outcomes ``decide`` reaches before selecting a
# requirement. Every other outcome names the requirement itself (``role:editor``,
# ``permission:notes.publish``).
_RULE_BY_REASON: Final[dict[str, str]] = {
    "public": "public",
    "no_policy": "no_policy",
    "unauthenticated": "authenticated",
    "unregistered_role": "registered_role",
}


def _uuid_text(value: object) -> str | None:
    """*value* as a canonical UUID string, or ``None`` when it is not one.

    The actor and the tenant are identifiers, and holding them to the UUID shape is
    what keeps a raw credential out of those two fields whatever a principal provider
    happens to put in a principal's id.
    """
    try:
        return str(value if isinstance(value, uuid.UUID) else uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _report_failure(logger: logging.Logger, what: str, exc: Exception) -> None:
    logger.warning(
        "%s could not be recorded", what,
        extra=log_fields(event="log.failure", error={"type": type(exc).__name__}),
    )


def guard_fields(
    decision: Any, *, module: str | None, policy: str, tier: str
) -> dict[str, str]:
    """The ``guard`` object of a line: outcome, reason slug, rule, policy source, tier."""
    requirement = decision.requirement
    fields = {
        "outcome": "allow" if decision.allowed else "deny",
        "reason": decision.reason,
        "rule": (
            requirement.label
            if requirement is not None
            else _RULE_BY_REASON.get(decision.reason, decision.reason)
        ),
        "policy": policy,
        "tier": tier,
    }
    if module is not None:
        fields["module"] = module
    return fields


def note_guard_decision(
    scope: object,
    decision: Any,
    *,
    module: str | None,
    policy: str,
    tier: str,
    actor_id: object | None,
) -> None:
    """Record one guard decision: on the request's access line, or as its own record.

    *actor_id* is the authenticated principal's id, or ``None`` when there is none; the
    tenant is read only beside an actor, so an unauthenticated request never names one.
    """
    try:
        guard = guard_fields(decision, module=module, policy=policy, tier=tier)
        actor = _uuid_text(actor_id) if actor_id is not None else None
        tenant = _uuid_text(active_log_tenant()) if actor is not None else None
        notes = scope.get(ACCESS_SCOPE_KEY) if isinstance(scope, dict) else None
        if isinstance(notes, dict):
            notes["guard"] = guard
            notes["actor"] = actor
            notes["tenant"] = tenant
            return
        _guard_logger.log(
            logging.DEBUG if decision.allowed else logging.INFO,
            "guard %s on %s: %s", guard["outcome"], tier, guard["rule"],
            extra=log_fields(event="guard.decision", guard=guard, actor=actor, tenant=tenant),
        )
    except Exception as exc:  # noqa: BLE001 - recording a decision never changes it
        _report_failure(_guard_logger, "a guard decision", exc)


def _route_template(scope: Scope) -> str | None:
    """The matched route's full template (``/api/v1/notes/{note_id}``), or ``None``.

    Recent FastAPI includes a router lazily: the route left in ``scope["route"]`` is the
    one the module declared, with a path relative to its router, and the template with
    the mount prefix in it is kept in FastAPI's per-request route context. Earlier
    releases copied every route onto the app with the prefix already in its path. The
    context is read where it exists and the route otherwise; both are templates, so the
    requested path, ids and all, is never what this returns.
    """
    fastapi_scope = scope.get("fastapi")
    context = (
        fastapi_scope.get("effective_route_context") if isinstance(fastapi_scope, dict) else None
    )
    for candidate in (context, scope.get("route")):
        template = getattr(candidate, "path_format", None) or getattr(candidate, "path", None)
        if isinstance(template, str) and template:
            return template
    return None


def write_access_line(scope: Scope, notes: dict[str, Any], elapsed: float) -> None:
    """Write the request's one ``http.access`` line."""
    try:
        method = scope.get("method", "-")
        route = _route_template(scope)
        status = notes.get("status", CLIENT_CLOSED)
        http: dict[str, Any] = {
            "method": method,
            "status": status,
            "duration_ms": round(elapsed * 1000, 3),
        }
        if route is not None:
            http["route"] = route
        _access_logger.info(
            "%s %s %s", method, route or "-", status,
            extra=log_fields(
                event="http.access",
                http=http,
                actor=notes.get("actor"),
                tenant=notes.get("tenant"),
                guard=notes.get("guard"),
            ),
        )
    except Exception as exc:  # noqa: BLE001 - the access line never breaks a response
        _report_failure(_access_logger, "an access line", exc)


def log_app_error(exc: Any) -> None:
    """Write the one ``error.app`` record for an ``AppError`` the envelope answered.

    A client error (4xx) is an expected outcome and is written at INFO, beside the access
    line that already carries its status; a server error (5xx) at ERROR, with its
    traceback, because something the app relies on is broken. ``log_context`` -- the
    reason the envelope deliberately does not tell the client -- goes in ``context``,
    redacted like every other field.
    """
    status = exc.status_code
    server_error = status >= 500
    _error_logger.log(
        logging.ERROR if server_error else logging.INFO,
        "%s %s: %s", status, exc.code, exc.message,
        exc_info=exc if server_error else None,
        extra=log_fields(
            event="error.app",
            error={"type": type(exc).__name__, "code": exc.code, "status": status},
            context=dict(exc.log_context) or None,
        ),
    )


def log_unhandled_error(exc: BaseException, request_id: str) -> None:
    """Write the one ``error.unhandled`` record for an exception answered with a 500.

    The handler for an unexpected exception runs outside the request-id middleware, which
    has already reset the correlation id by then; binding it again for this one record is
    what lets a reader join the error to the request's access line by ``request_id``. The
    exception is marked as written, because Starlette re-raises it to the server after this
    handler has answered, and the server would otherwise write it a second time.
    """
    mark_logged(exc)
    token = request_id_ctx.set(request_id)
    try:
        _unhandled_logger.error(
            "unhandled exception [request_id=%s]", request_id,
            exc_info=exc,
            extra=log_fields(
                event="error.unhandled",
                error={"type": type(exc).__name__, "code": "internal_error", "status": 500},
            ),
        )
    finally:
        request_id_ctx.reset(token)


class AccessLogMiddleware:
    """Pure-ASGI middleware writing one ``http.access`` line per HTTP request.

    Pure ASGI rather than ``BaseHTTPMiddleware``: it adds no task and no stream copy to
    every request, which is what keeps its cost to a clock read and one record.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        notes: dict[str, Any] = {}
        scope[ACCESS_SCOPE_KEY] = notes
        started = time.perf_counter()

        async def send_and_note(message: Message) -> None:
            if message["type"] == "http.response.start":
                notes["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_note)
        except Exception:
            # The server answers an exception that escaped every handler with a 500.
            notes.setdefault("status", 500)
            raise
        finally:
            write_access_line(scope, notes, time.perf_counter() - started)


__all__ = [
    "ACCESS_SCOPE_KEY",
    "AccessLogMiddleware",
    "CLIENT_CLOSED",
    "guard_fields",
    "log_app_error",
    "log_unhandled_error",
    "note_guard_decision",
    "write_access_line",
]
