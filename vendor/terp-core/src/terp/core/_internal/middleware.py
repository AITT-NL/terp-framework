"""The security middleware stack installed by ``create_app`` (internal).

These ASGI / HTTP middlewares are wired exclusively by the composition root from
the application's :class:`~terp.core.security.SecurityConfig`. They live under
``_internal`` because a module may never construct or attach them itself — the
``terp.arch`` ``no_adhoc_middleware`` rule forbids it, so the security posture is
always the one central declaration.

Order (outermost → innermost), so each response — including a CORS preflight —
carries every control: request-id · security-headers · CORS · client-ip ·
rate-limit · request-size-limit · idempotency · app.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from terp.core.idempotency import IdempotencyStore, StoredResponse
from terp.core.logging import request_id_ctx
from terp.core.security import SecurityConfig, SecurityHeaders, client_ip
from terp.core.throttling import InMemoryThrottleStore, ThrottleStore

_CallNext = Callable[[Request], Awaitable[Response]]


def _envelope(code: str, detail: str) -> dict[str, str]:
    """A middleware-level error body matching the app's ``{code, detail, request_id}``."""
    return {"code": code, "detail": detail, "request_id": request_id_ctx.get() or "-"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set the configured security headers on every response (without clobbering)."""

    def __init__(self, app: ASGIApp, *, headers: SecurityHeaders, include_hsts: bool) -> None:
        super().__init__(app)
        self._headers = headers.as_headers(include_hsts=include_hsts)

    async def dispatch(self, request: Request, call_next: _CallNext) -> Response:
        response = await call_next(request)
        for header, value in self._headers.items():
            response.headers.setdefault(header, value)
        return response


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Stamp every request with a correlation id and propagate it.

    Honours a **well-formed** inbound id header (so an upstream proxy / SDK retry
    correlates the whole chain) or generates one, stashes it on ``request.state``
    and the :data:`~terp.core.logging.request_id_ctx` context var, and echoes it
    back. An inbound id is honoured only when it matches a strict length/charset
    shape — an arbitrary attacker-supplied value would otherwise flow verbatim
    into every structured log line and response header (log injection); a
    malformed id is replaced, never echoed.
    """

    _VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

    def __init__(self, app: ASGIApp, *, header_name: str) -> None:
        super().__init__(app)
        self._header_name = header_name

    async def dispatch(self, request: Request, call_next: _CallNext) -> Response:
        inbound = request.headers.get(self._header_name)
        if inbound is None or not self._VALID_ID.fullmatch(inbound):
            request_id = uuid.uuid4().hex
        else:
            request_id = inbound
        request.state.request_id = request_id
        token = request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
            response.headers[self._header_name] = request_id
            return response
        finally:
            request_id_ctx.reset(token)


def _rate_limit_key(request: Request) -> str:
    """Identify the caller for rate-limiting — the resolved client IP."""
    return client_ip(request)


def _forwarded_client_ip(request: Request, *, trusted_hops: int) -> str | None:
    """The client address *trusted_hops* proxies forwarded, or ``None`` if unresolvable.

    With ``h`` trusted hops, the last ``h`` entries of ``X-Forwarded-For`` were
    appended by our own proxies, so the ``h``-th entry from the right is the address
    the outermost trusted proxy saw — the real client. Anything left of it is
    client-supplied and never trusted. A missing header, too few entries, or a
    value that does not parse as an IP address resolves to ``None`` (the caller
    falls back to the direct peer — fail toward the stricter key, never toward an
    attacker-chosen one).
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded is None:
        return None
    entries = [entry.strip() for entry in forwarded.split(",")]
    if len(entries) < trusted_hops:
        return None
    candidate = entries[-trusted_hops]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


class ClientIpMiddleware(BaseHTTPMiddleware):
    """Resolve the caller's client IP once, honouring the trusted-proxy declaration.

    Stashes the resolved address on ``request.state.client_ip``, where the public
    :func:`terp.core.security.client_ip` helper (and every per-caller control built
    on it — the rate limiter, the OIDC callback throttle) reads it. With
    ``trusted_proxy_hops=0`` (the default) forwarding headers are ignored entirely:
    they are attacker-supplied absent a trust declaration. With ``h > 0`` hops the
    ``X-Forwarded-For`` entry appended by the outermost trusted proxy identifies
    the caller, so a deployment behind the shipped same-origin proxy does not
    collapse every client onto the proxy's address (one abusive caller must not
    rate-limit everyone).
    """

    def __init__(self, app: ASGIApp, *, trusted_proxy_hops: int) -> None:
        super().__init__(app)
        self._trusted_proxy_hops = trusted_proxy_hops

    async def dispatch(self, request: Request, call_next: _CallNext) -> Response:
        resolved: str | None = None
        if self._trusted_proxy_hops > 0:
            resolved = _forwarded_client_ip(request, trusted_hops=self._trusted_proxy_hops)
        if resolved is None:
            resolved = request.client.host if request.client is not None else "anonymous"
        request.state.client_ip = resolved
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Reject a caller exceeding the configured request rate (HTTP 429).

    Counter state lives in the pluggable :class:`~terp.core.throttling.ThrottleStore`
    (default :class:`InMemoryThrottleStore`, per-process — the historical behaviour). A
    multi-instance deployment supplies a shared store so the limit is one global cap, not
    N× the instance count. A store error fails **closed**: the caller is rate-limited
    rather than silently waved through.
    """

    def __init__(
        self, app: ASGIApp, *, limit: int, window: int, store: ThrottleStore | None = None
    ) -> None:
        super().__init__(app)
        self._limit = limit
        self._window = window
        self._store = store if store is not None else InMemoryThrottleStore()

    def _check(self, key: str) -> tuple[bool, int, int]:
        """Register a hit; return ``(allowed, remaining, reset)``, fail-closed on error."""
        try:
            count, reset = self._store.hit(f"rl:{key}", self._window)
        except Exception:
            return False, 0, self._window
        if count > self._limit:
            return False, 0, reset
        return True, self._limit - count, reset

    async def dispatch(self, request: Request, call_next: _CallNext) -> Response:
        allowed, remaining, reset = self._check(_rate_limit_key(request))
        if not allowed:
            return JSONResponse(
                status_code=429,
                content=_envelope("rate_limited", "Too many requests; please retry later."),
                headers={
                    "Retry-After": str(reset),
                    "X-RateLimit-Limit": str(self._limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset),
                },
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset)
        return response


def _declared_length(scope: Scope) -> int | None:
    """The request's declared ``Content-Length`` as an int, or ``None`` if absent/malformed."""
    for key, value in scope.get("headers", []):
        if key == b"content-length":
            try:
                return int(value.decode("latin-1"))
            except ValueError:
                return None
    return None


async def _send_too_large(send: Send, max_bytes: int) -> None:
    await _send_json_error(
        send, 413, "request_too_large", f"Request body exceeds the {max_bytes}-byte limit."
    )


async def _send_json_error(
    send: Send,
    status: int,
    code: str,
    detail: str,
    *,
    extra_headers: tuple[tuple[bytes, bytes], ...] = (),
) -> None:
    """Send the uniform ``{code, detail, request_id}`` envelope from an ASGI middleware."""
    body = json.dumps(_envelope(code, detail)).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("latin-1")),
                *extra_headers,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequestSizeLimitMiddleware:
    """Reject over-large request bodies before they tie up a worker.

    A declared ``Content-Length`` over the cap is refused up front with a clean
    413. A body with no declared length (chunked/streaming) is counted on the fly
    and the connection is dropped once the cap is exceeded, so an unbounded upload
    cannot exhaust the worker.

    *overrides* maps a path prefix (a module mount, e.g. ``/api/v1/files``) to its
    own cap (ADR 0067): a request whose path equals the prefix or lives under it
    is bounded by that cap instead of the global one — the longest matching prefix
    wins, and every unmatched path keeps the global cap (deny-by-default).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int,
        overrides: Mapping[str, int] | None = None,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        # Longest prefix first, so the most specific mount decides.
        self._overrides = tuple(
            sorted((overrides or {}).items(), key=lambda item: len(item[0]), reverse=True)
        )

    def _cap_for(self, path: str) -> int:
        """The effective byte cap for *path*: its longest override prefix, else the global cap."""
        for prefix, cap in self._overrides:
            if path == prefix or path.startswith(prefix + "/"):
                return cap
        return self.max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        cap = self._cap_for(scope.get("path", ""))
        declared = _declared_length(scope)
        if declared is not None and declared > cap:
            await _send_too_large(send, cap)
            return

        seen = 0

        async def counting_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b"") or b"")
                if seen > cap:
                    return {"type": "http.disconnect"}
            return message

        await self.app(scope, counting_receive, send)


# The unsafe (mutating) HTTP methods the idempotency control applies to. Mirrors the
# composition root's mutating set; safe methods are naturally idempotent already.
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class IdempotencyMiddleware:
    """Deduplicate client-retried unsafe requests carrying an ``Idempotency-Key``.

    A request without the header passes straight through — the control is inert until
    a client opts in. With the header, the first execution's response is stored in the
    pluggable :class:`~terp.core.idempotency.IdempotencyStore` and **replayed** to a
    retry of the same key (marked ``Idempotency-Replayed: true``), so a timed-out
    client can safely retry a POST without double-executing it. Concretely:

    - The store key is scoped to the presented ``Authorization`` credential (hashed,
      never stored raw), so one caller can never replay — or probe — another caller's
      responses.
    - The request **fingerprint** (method + path + body digest) rides the entry; a key
      reused for a different request is refused with a typed 422 rather than answering
      with a response to a request that was never made.
    - A concurrent duplicate (the key is still executing) gets a typed 409 with
      ``Retry-After``, never a second execution.
    - Only completed non-5xx responses are stored; a crash or a 5xx releases the key so
      the retry re-executes (at-least-once, matching the platform's jobs contract).
    - The store failing on claim is **fail closed** (typed 503): without the dedup
      guarantee the mutation is refused, never silently double-executable.

    The middleware sits innermost (inside the request-size cap, so buffering the body
    for fingerprinting is bounded — and independently capped by *max_body_bytes*,
    refused with a typed 413 beyond it, so an over-sized upload never buffers in
    memory). Being innermost also means the stored response carries only the
    application's own headers; request-scoped headers (request id, rate-limit
    counters, security headers) are re-added fresh by the outer stack on a replay.
    """

    _VALID_KEY = re.compile(r"^[A-Za-z0-9._~-]{1,128}$")

    def __init__(
        self,
        app: ASGIApp,
        *,
        store: IdempotencyStore,
        replay_ttl_seconds: int = 24 * 60 * 60,
        execution_ttl_seconds: int = 300,
        max_body_bytes: int = 1 * 1024 * 1024,
        max_stored_response_bytes: int = 256 * 1024,
    ) -> None:
        self.app = app
        self._store = store
        self._replay_ttl = replay_ttl_seconds
        self._execution_ttl = execution_ttl_seconds
        self._max_body_bytes = max_body_bytes
        self._max_stored_response_bytes = max_stored_response_bytes

    @staticmethod
    def _header(scope: Scope, name: bytes) -> bytes | None:
        for key, value in scope.get("headers", []):
            if key.lower() == name:
                return value
        return None

    def _store_key(self, scope: Scope, key: str) -> str:
        """The caller-scoped store key: hash(credential + key), never the raw pieces."""
        credential = self._header(scope, b"authorization") or b""
        digest = hashlib.sha256()
        digest.update(b"terp-idempotency-key\n")
        digest.update(credential)
        digest.update(b"\n")
        digest.update(key.encode("ascii"))
        return digest.hexdigest()

    @staticmethod
    def _fingerprint(scope: Scope, body: bytes) -> str:
        """The request digest a reused key must match: method + path + payload."""
        digest = hashlib.sha256()
        digest.update(scope["method"].encode("ascii"))
        digest.update(b"\n")
        digest.update(scope.get("path", "").encode("utf-8"))
        digest.update(b"\n")
        digest.update(scope.get("query_string", b""))
        digest.update(b"\n")
        digest.update(hashlib.sha256(body).digest())
        return digest.hexdigest()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        raw_key = self._header(scope, b"idempotency-key")
        if raw_key is None:
            await self.app(scope, receive, send)
            return
        key = raw_key.decode("latin-1")
        if not self._VALID_KEY.fullmatch(key):
            await _send_json_error(
                send,
                400,
                "invalid_idempotency_key",
                "The Idempotency-Key header must be 1-128 characters of A-Za-z0-9._~-",
            )
            return

        # Buffer the (already size-capped) body to fingerprint the request before
        # claiming the key; the buffered messages are replayed to the app verbatim.
        buffered: list[Message] = []
        body = bytearray()
        while True:
            message = await receive()
            buffered.append(message)
            if message["type"] != "http.request":
                # The client disconnected mid-request: hand everything to the app
                # unprocessed — there is no response to store for a dead request.
                await self.app(scope, _replay_receive(buffered, receive), send)
                return
            body.extend(message.get("body", b"") or b"")
            if len(body) > self._max_body_bytes:
                await _send_json_error(
                    send,
                    413,
                    "idempotency_body_too_large",
                    f"Idempotent processing buffers the request body; bodies over "
                    f"{self._max_body_bytes} bytes cannot use an Idempotency-Key.",
                )
                return
            if not message.get("more_body", False):
                break

        store_key = self._store_key(scope, key)
        fingerprint = self._fingerprint(scope, bytes(body))
        try:
            outcome = self._store.begin(
                store_key, fingerprint, ttl_seconds=self._execution_ttl
            )
        except Exception:
            # Fail closed: without the dedup claim the mutation is refused — executing
            # anyway could double-apply the very request the client marked idempotent.
            await _send_json_error(
                send,
                503,
                "idempotency_unavailable",
                "The idempotency store is unavailable; the request was not executed. "
                "Retry with the same Idempotency-Key.",
                extra_headers=((b"retry-after", b"1"),),
            )
            return

        if outcome.state == "mismatch":
            await _send_json_error(
                send,
                422,
                "idempotency_key_mismatch",
                "This Idempotency-Key was already used for a different request "
                "(method, path, or body); use a fresh key per distinct request.",
            )
            return
        if outcome.state == "in_flight":
            await _send_json_error(
                send,
                409,
                "idempotency_in_flight",
                "A request with this Idempotency-Key is still executing; retry shortly.",
                extra_headers=((b"retry-after", b"1"),),
            )
            return
        if outcome.state == "replay":
            stored = outcome.response
            assert stored is not None  # the port contract for "replay"
            headers = [
                (name.encode("latin-1"), value.encode("latin-1"))
                for name, value in stored.headers
            ]
            headers.append((b"idempotency-replayed", b"true"))
            await send(
                {"type": "http.response.start", "status": stored.status_code, "headers": headers}
            )
            await send({"type": "http.response.body", "body": stored.body})
            return

        lease = outcome.lease
        assert lease is not None  # the port contract for "started"
        status: int | None = None
        response_headers: tuple[tuple[str, str], ...] = ()
        chunks = bytearray()
        storable = True
        completed = False

        async def capturing_send(message: Message) -> None:
            nonlocal status, response_headers, storable, completed
            if message["type"] == "http.response.start":
                status = message["status"]
                response_headers = tuple(
                    (name.decode("latin-1"), value.decode("latin-1"))
                    for name, value in message.get("headers", [])
                )
            elif message["type"] == "http.response.body":
                if storable:
                    chunks.extend(message.get("body", b"") or b"")
                    if len(chunks) > self._max_stored_response_bytes:
                        storable = False
                        chunks.clear()
                if not message.get("more_body", False):
                    completed = True
            await send(message)

        try:
            await self.app(scope, _replay_receive(buffered, receive), capturing_send)
        except BaseException:
            self._store.release(store_key, lease)
            raise
        if completed and storable and status is not None and status < 500:
            self._store.complete(
                store_key,
                lease,
                StoredResponse(
                    status_code=status, headers=response_headers, body=bytes(chunks)
                ),
                ttl_seconds=self._replay_ttl,
            )
        else:
            # An incomplete, over-large, or 5xx response is never replayed: drop the
            # claim so the client's retry re-executes (at-least-once).
            self._store.release(store_key, lease)


def _replay_receive(buffered: list[Message], receive: Receive) -> Receive:
    """A receive channel that replays *buffered* messages, then delegates."""
    pending = list(buffered)

    async def replay() -> Message:
        if pending:
            return pending.pop(0)
        return await receive()

    return replay


def install_security_middleware(
    app: FastAPI,
    config: SecurityConfig,
    *,
    is_local: bool,
    throttle_store: ThrottleStore,
    idempotency_store: IdempotencyStore,
    request_size_overrides: Mapping[str, int] | None = None,
) -> None:
    """Attach the full security stack to *app* from its central ``SecurityConfig``.

    Added innermost-first so the resulting outer→inner order is request-id,
    security-headers, CORS, client-ip, rate-limit, request-size-limit, idempotency.
    Request-id and the security headers wrap CORS so that even a CORS preflight
    (handled and short-circuited by the CORS middleware) still carries a correlation
    id and the security headers. The client-ip resolver always attaches (it feeds
    every per-caller control via ``terp.core.security.client_ip``) and wraps the rate
    limiter, whose key it supplies. CORS and the rate limiter attach only when
    configured. The rate
    limiter keeps its counter in *throttle_store* (shared across instances when the app
    supplies one; the default is per-process). The idempotency dedup sits innermost —
    inside the request-size cap (so its body fingerprinting is bounded) and inside the
    per-request headers (so a replayed response gets fresh ones) — keeping its state in
    *idempotency_store*. *request_size_overrides* is the
    prefix→cap map the composition root derives from each mounted spec's declared
    ``max_request_bytes`` (ADR 0067); unmatched paths keep the global cap.
    """
    app.add_middleware(IdempotencyMiddleware, store=idempotency_store)
    app.add_middleware(
        RequestSizeLimitMiddleware,
        max_bytes=config.max_request_bytes,
        overrides=request_size_overrides,
    )
    if config.rate_limit.enabled:
        app.add_middleware(
            RateLimitMiddleware,
            limit=config.rate_limit.requests,
            window=config.rate_limit.window_seconds,
            store=throttle_store,
        )
    app.add_middleware(ClientIpMiddleware, trusted_proxy_hops=config.trusted_proxy_hops)
    if config.cors.enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.cors.allow_origins),
            allow_credentials=config.cors.allow_credentials,
            allow_methods=list(config.cors.allow_methods),
            allow_headers=list(config.cors.allow_headers),
            expose_headers=list(config.cors.expose_headers),
        )
    app.add_middleware(
        SecurityHeadersMiddleware, headers=config.headers, include_hsts=not is_local
    )
    app.add_middleware(RequestIdMiddleware, header_name=config.request_id_header)


__all__ = [
    "ClientIpMiddleware",
    "IdempotencyMiddleware",
    "RateLimitMiddleware",
    "RequestIdMiddleware",
    "RequestSizeLimitMiddleware",
    "SecurityHeadersMiddleware",
    "install_security_middleware",
]
