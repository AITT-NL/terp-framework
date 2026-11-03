"""Composition and request context for authorizing stored responses."""

from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
from inspect import isasyncgenfunction, iscoroutinefunction, isgeneratorfunction

from fastapi import Depends, Request
from fastapi.routing import APIRoute
from starlette.responses import Response

from terp.core.errors import ConflictError, ValidationFailedError
from terp.core.idempotency import StoredResponse, _NO_IDEMPOTENCY, _REPLAY_AUTHORIZER

replay_response: ContextVar[StoredResponse | None] = ContextVar(
    "terp_idempotency_replay_response", default=None
)


class ReplayNotAuthorized(ConflictError):
    code = "idempotency_replay_not_authorized"
    default_message = "This route has not declared authorization for replaying a stored response."


class IdempotencyNotSupported(ValidationFailedError):
    code = "idempotency_not_supported"
    default_message = "This route does not accept Idempotency-Key."


def prepare_idempotency_route(route: APIRoute) -> None:
    """Prepare a declaring route before FastAPI builds its inclusion contexts.

    A replay reaches the endpoint wrapper only AFTER FastAPI resolves all route
    dependencies. Unmarked routes are refused by a dependency before their handler
    can execute. Marking the route keeps multiple app compositions idempotent.
    """
    if getattr(route, "_terp_idempotency_prepared", False):
        return
    endpoint = route.endpoint
    authorizer = getattr(endpoint, _REPLAY_AUTHORIZER, None)

    def check_mode(request: Request) -> None:
        if getattr(endpoint, _NO_IDEMPOTENCY, False) and "idempotency-key" in request.headers:
            raise IdempotencyNotSupported()
        if replay_response.get() is not None and authorizer is None:
            raise ReplayNotAuthorized()

    route.dependencies.insert(0, Depends(check_mode))
    if authorizer is not None:
        if isgeneratorfunction(endpoint) or isasyncgenfunction(endpoint):
            raise ValueError("idempotent_replay does not support streaming generator endpoints")
        route.dependencies.append(Depends(authorizer))

        def stored_response() -> Response | None:
            stored = replay_response.get()
            if stored is None:
                return None
            response = Response(content=stored.body, status_code=stored.status_code)
            response.raw_headers = [
                (name.encode("latin-1"), value.encode("latin-1"))
                for name, value in stored.headers
            ] + [(b"idempotency-replayed", b"true")]
            return response

        if iscoroutinefunction(endpoint):
            @wraps(endpoint)
            async def wrapped(**kwargs):
                response = stored_response()
                return response if response is not None else await endpoint(**kwargs)
        else:
            @wraps(endpoint)
            def wrapped(**kwargs):
                response = stored_response()
                return response if response is not None else endpoint(**kwargs)

        route.endpoint = wrapped
    setattr(route, "_terp_idempotency_prepared", True)
