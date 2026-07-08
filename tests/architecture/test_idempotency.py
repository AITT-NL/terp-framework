"""Idempotency keys: replayed retries, fail-closed store, boot guard, default unchanged.

Covers the kernel side of the quadruple (shaped like the throttle-/cache-store suites,
ADR 0036 / ADR 0077): the in-memory default's claim/replay/expiry semantics, the
``IdempotencyMiddleware`` request flow end-to-end through ``create_app`` (replay,
mismatch, in-flight, invalid key, fail-closed store errors, at-least-once fallbacks),
and the ``create_app(idempotency_store=…, require_shared_idempotency_store=…)``
wiring — including the fail-closed boot refusal of an unmarked per-instance store.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from terp.core import (
    BeginOutcome,
    BootError,
    IdempotencyStore,
    InMemoryIdempotencyStore,
    ModuleSpec,
    Policy,
    StoredResponse,
    create_app,
    is_shared_idempotency_store,
    mark_shared_idempotency_store,
)
from terp.core._internal.middleware import IdempotencyMiddleware

_RESPONSE = StoredResponse(status_code=201, headers=(("content-type", "application/json"),), body=b"{}")


class _PassThrough(IdempotencyStore):
    """Exercises the abstract bodies via ``super()`` (they are no-ops/None)."""

    def begin(self, key: str, fingerprint: str, *, ttl_seconds: int) -> BeginOutcome:
        super().begin(key, fingerprint, ttl_seconds=ttl_seconds)
        return BeginOutcome(state="started", lease="lease")

    def complete(
        self, key: str, lease: str, response: StoredResponse, *, ttl_seconds: int
    ) -> None:
        super().complete(key, lease, response, ttl_seconds=ttl_seconds)

    def release(self, key: str, lease: str) -> None:
        super().release(key, lease)


# --------------------------------------------------------------------------- #
# InMemoryIdempotencyStore — the safe default
# --------------------------------------------------------------------------- #
def test_in_memory_begin_complete_replay_lifecycle() -> None:
    store = InMemoryIdempotencyStore()
    first = store.begin("k", "fp", ttl_seconds=60)
    assert first.state == "started"
    assert first.lease is not None
    # While executing, a duplicate is in-flight; a different request is a mismatch.
    assert store.begin("k", "fp", ttl_seconds=60).state == "in_flight"
    assert store.begin("k", "other-fp", ttl_seconds=60).state == "mismatch"
    store.complete("k", first.lease, _RESPONSE, ttl_seconds=60)
    replay = store.begin("k", "fp", ttl_seconds=60)
    assert replay.state == "replay"
    assert replay.response == _RESPONSE
    # A completed key under a different fingerprint is still a mismatch, never a replay.
    assert store.begin("k", "other-fp", ttl_seconds=60).state == "mismatch"


def test_in_memory_release_lets_a_retry_re_execute() -> None:
    store = InMemoryIdempotencyStore()
    first = store.begin("k", "fp", ttl_seconds=60)
    assert first.lease is not None
    store.release("k", first.lease)
    assert store.begin("k", "fp", ttl_seconds=60).state == "started"


def test_in_memory_release_and_complete_are_lease_guarded() -> None:
    store = InMemoryIdempotencyStore()
    first = store.begin("k", "fp", ttl_seconds=60)
    assert first.lease is not None
    store.release("k", "stale-lease")  # a stale release is a no-op…
    assert store.begin("k", "fp", ttl_seconds=60).state == "in_flight"
    store.complete("k", "stale-lease", _RESPONSE, ttl_seconds=60)  # …and so is a stale complete
    assert store.begin("k", "fp", ttl_seconds=60).state == "in_flight"
    store.release("absent", "lease")  # releasing an absent key never raises
    store.complete("absent", "lease", _RESPONSE, ttl_seconds=60)  # completing one neither


def test_in_memory_entries_expire_on_access() -> None:
    now = [0.0]
    store = InMemoryIdempotencyStore(clock=lambda: now[0])
    first = store.begin("k", "fp", ttl_seconds=10)
    assert first.lease is not None
    store.complete("k", first.lease, _RESPONSE, ttl_seconds=10)
    now[0] = 10  # replay TTL elapsed → the retry re-executes (at-least-once)
    assert store.begin("k", "fp", ttl_seconds=10).state == "started"


def test_in_memory_stale_lease_after_expiry_cannot_clobber_a_new_claim() -> None:
    now = [0.0]
    store = InMemoryIdempotencyStore(clock=lambda: now[0])
    first = store.begin("k", "fp", ttl_seconds=10)
    assert first.lease is not None
    now[0] = 10  # the execution claim expired mid-flight…
    second = store.begin("k", "fp", ttl_seconds=10)
    assert second.state == "started"  # …and a retry re-claimed the key
    store.complete("k", first.lease, _RESPONSE, ttl_seconds=60)  # the slow finisher is stale
    assert store.begin("k", "fp", ttl_seconds=10).state == "in_flight"  # new claim untouched


def test_in_memory_sweeps_expired_entries_interval_gated() -> None:
    now = [0.0]
    store = InMemoryIdempotencyStore(clock=lambda: now[0])
    store.begin("old", "fp", ttl_seconds=1)  # first begin sweeps; the gate closes
    now[0] = 0.5
    store.begin("young", "fp", ttl_seconds=60)  # inside the gate → no scan
    now[0] = 2  # "old" expired and the gate reopened
    store.begin("later", "fp", ttl_seconds=60)  # → sweep drops "old"
    assert "old" not in store._entries
    assert "young" in store._entries


def test_in_memory_expired_entry_is_dropped_on_access_even_inside_the_sweep_gate() -> None:
    now = [0.0]
    store = InMemoryIdempotencyStore(clock=lambda: now[0])
    store.begin("k", "fp", ttl_seconds=1)
    store._next_sweep_at = 100.0  # hold the gate closed so the sweep cannot run
    now[0] = 5  # "k" is expired…
    assert store.begin("k", "fp", ttl_seconds=60).state == "started"  # …per-key expiry drops it


def test_in_memory_overflow_evicts_the_soonest_expiring_entry() -> None:
    now = [0.0]
    store = InMemoryIdempotencyStore(max_entries=2, clock=lambda: now[0])
    store.begin("soon", "fp", ttl_seconds=10)
    store.begin("late", "fp", ttl_seconds=100)
    store.begin("new", "fp", ttl_seconds=100)  # full → "soon" is evicted
    assert "soon" not in store._entries
    assert {"late", "new"} <= set(store._entries)


def test_in_memory_reset_drops_all_entries() -> None:
    store = InMemoryIdempotencyStore()
    store.begin("k", "fp", ttl_seconds=60)
    store.reset()
    assert store.begin("k", "fp", ttl_seconds=60).state == "started"


def test_in_memory_validates_its_inputs() -> None:
    with pytest.raises(ValueError, match="positive max_entries"):
        InMemoryIdempotencyStore(max_entries=0)
    store = InMemoryIdempotencyStore()
    with pytest.raises(ValueError, match="positive ttl_seconds"):
        store.begin("k", "fp", ttl_seconds=0)
    with pytest.raises(ValueError, match="positive ttl_seconds"):
        store.complete("k", "lease", _RESPONSE, ttl_seconds=-1)


def test_abstract_bodies_are_callable() -> None:
    store = _PassThrough()
    assert store.begin("k", "fp", ttl_seconds=1).state == "started"
    store.complete("k", "lease", _RESPONSE, ttl_seconds=1)
    store.release("k", "lease")


# --------------------------------------------------------------------------- #
# The shared-store boot marker
# --------------------------------------------------------------------------- #
def test_shared_marker_roundtrip() -> None:
    store = InMemoryIdempotencyStore()
    assert is_shared_idempotency_store(store) is False
    assert is_shared_idempotency_store(None) is False
    marked = mark_shared_idempotency_store(store)
    assert marked is store
    assert is_shared_idempotency_store(store) is True


# --------------------------------------------------------------------------- #
# IdempotencyMiddleware — end-to-end through create_app
# --------------------------------------------------------------------------- #
def _build_client(store: IdempotencyStore) -> tuple[TestClient, list[int]]:
    """A tiny app whose POST/DELETE handlers count their executions."""
    router = APIRouter()
    executions: list[int] = []

    @router.post("/things", response_model=dict)
    def create_thing(payload: dict) -> dict:
        executions.append(1)
        return {"execution": len(executions)}

    @router.put("/things", response_model=dict)
    def replace_thing(payload: dict) -> dict:
        executions.append(1)
        return {"execution": len(executions)}

    @router.patch("/things", response_model=dict)
    def update_thing(payload: dict) -> dict:
        executions.append(1)
        return {"execution": len(executions)}

    @router.post("/broken", response_model=dict)
    def broken(payload: dict) -> dict:
        executions.append(1)
        raise RuntimeError("boom")

    @router.delete("/things", response_model=dict)
    def delete_thing() -> dict:
        executions.append(1)
        return {"execution": len(executions)}

    spec = ModuleSpec(
        name="probe", router=router, policy=Policy.public_write(reason="idempotency test")
    )
    app = create_app([spec], idempotency_store=store)
    return TestClient(app, raise_server_exceptions=False), executions


def test_a_request_without_the_header_is_untouched() -> None:
    client, executions = _build_client(InMemoryIdempotencyStore())
    assert client.post("/api/v1/probe/things", json={}).json() == {"execution": 1}
    assert client.post("/api/v1/probe/things", json={}).json() == {"execution": 2}
    assert len(executions) == 2


def test_a_retry_with_the_same_key_replays_without_re_executing() -> None:
    client, executions = _build_client(InMemoryIdempotencyStore())
    headers = {"Idempotency-Key": "key-1"}
    first = client.post("/api/v1/probe/things", headers=headers, json={"a": 1})
    retry = client.post("/api/v1/probe/things", headers=headers, json={"a": 1})
    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json() == {"execution": 1}
    assert len(executions) == 1
    assert "idempotency-replayed" not in first.headers
    assert retry.headers["idempotency-replayed"] == "true"
    # The replay carries the app's own headers but a *fresh* request id.
    assert retry.headers["content-type"] == first.headers["content-type"]
    assert retry.headers["x-request-id"] != first.headers["x-request-id"]


def test_delete_requests_are_deduplicated_too() -> None:
    client, executions = _build_client(InMemoryIdempotencyStore())
    headers = {"Idempotency-Key": "key-del"}
    assert client.delete("/api/v1/probe/things", headers=headers).json() == {"execution": 1}
    assert client.delete("/api/v1/probe/things", headers=headers).json() == {"execution": 1}
    assert len(executions) == 1


@pytest.mark.parametrize("method", ["put", "patch"])
def test_all_unsafe_methods_are_deduplicated(method: str) -> None:
    client, executions = _build_client(InMemoryIdempotencyStore())
    headers = {"Idempotency-Key": f"key-{method}"}
    first = getattr(client, method)("/api/v1/probe/things", headers=headers, json={"a": 1})
    retry = getattr(client, method)("/api/v1/probe/things", headers=headers, json={"a": 1})
    assert first.json() == retry.json() == {"execution": 1}
    assert len(executions) == 1


def test_key_reuse_for_a_different_request_is_a_typed_422() -> None:
    client, _ = _build_client(InMemoryIdempotencyStore())
    headers = {"Idempotency-Key": "key-2"}
    assert client.post("/api/v1/probe/things", headers=headers, json={"a": 1}).status_code == 200
    changed_body = client.post("/api/v1/probe/things", headers=headers, json={"a": 2})
    assert changed_body.status_code == 422
    assert changed_body.json()["code"] == "idempotency_key_mismatch"
    changed_path = client.delete("/api/v1/probe/things", headers=headers)
    assert changed_path.status_code == 422
    assert changed_path.json()["code"] == "idempotency_key_mismatch"


def test_key_reuse_for_a_different_query_string_is_a_typed_422() -> None:
    client, _ = _build_client(InMemoryIdempotencyStore())
    headers = {"Idempotency-Key": "key-query"}
    first = client.post("/api/v1/probe/things?variant=a", headers=headers, json={})
    changed_query = client.post("/api/v1/probe/things?variant=b", headers=headers, json={})
    assert first.status_code == 200
    assert changed_query.status_code == 422
    assert changed_query.json()["code"] == "idempotency_key_mismatch"


def test_the_key_is_scoped_to_the_presented_credential() -> None:
    client, executions = _build_client(InMemoryIdempotencyStore())
    key = {"Idempotency-Key": "shared-key"}
    token_a = "-".join(["credential", "a"])
    token_b = "-".join(["credential", "b"])
    caller_a = {**key, "Authorization": token_a}
    caller_b = {**key, "Authorization": token_b}
    a = client.post("/api/v1/probe/things", headers=caller_a, json={})
    b = client.post("/api/v1/probe/things", headers=caller_b, json={})
    # Different callers never share a replay — caller B's identical request re-executes.
    assert a.json() == {"execution": 1}
    assert b.json() == {"execution": 2}
    assert len(executions) == 2


def test_a_malformed_key_is_a_typed_400() -> None:
    client, executions = _build_client(InMemoryIdempotencyStore())
    for bad in ("bad key!", "x" * 129, ""):
        response = client.post(
            "/api/v1/probe/things", headers={"Idempotency-Key": bad}, json={}
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_idempotency_key"
    assert executions == []


def test_a_concurrent_duplicate_is_a_typed_409() -> None:
    class _InFlight(InMemoryIdempotencyStore):
        def begin(self, key: str, fingerprint: str, *, ttl_seconds: int) -> BeginOutcome:
            return BeginOutcome(state="in_flight")

    client, executions = _build_client(_InFlight())
    response = client.post(
        "/api/v1/probe/things", headers={"Idempotency-Key": "key-3"}, json={}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "idempotency_in_flight"
    assert response.headers["retry-after"] == "1"
    assert executions == []


def test_a_failing_store_fails_closed_with_a_typed_503() -> None:
    class _Broken(InMemoryIdempotencyStore):
        def begin(self, key: str, fingerprint: str, *, ttl_seconds: int) -> BeginOutcome:
            raise RuntimeError("store down")

    client, executions = _build_client(_Broken())
    response = client.post(
        "/api/v1/probe/things", headers={"Idempotency-Key": "key-4"}, json={}
    )
    assert response.status_code == 503
    assert response.json()["code"] == "idempotency_unavailable"
    assert executions == []  # the mutation never ran without the dedup claim


def test_a_raising_handler_releases_the_key_so_a_retry_re_executes() -> None:
    client, executions = _build_client(InMemoryIdempotencyStore())
    headers = {"Idempotency-Key": "key-5"}
    first = client.post("/api/v1/probe/broken", headers=headers, json={})
    assert first.status_code == 500
    retry = client.post("/api/v1/probe/broken", headers=headers, json={})
    assert retry.status_code == 500
    assert "idempotency-replayed" not in retry.headers
    assert len(executions) == 2  # at-least-once: the failure is never replayed


# --------------------------------------------------------------------------- #
# IdempotencyMiddleware — ASGI edge cases (raw invocation)
# --------------------------------------------------------------------------- #
def _run_middleware(
    middleware: IdempotencyMiddleware,
    scope: dict,
    inbound: list[dict],
) -> list[dict]:
    """Drive *middleware* with scripted receive messages; return the sent messages."""
    sent: list[dict] = []
    pending = list(inbound)

    async def receive() -> dict:
        return pending.pop(0)

    async def send(message: dict) -> None:
        sent.append(message)

    asyncio.run(middleware(scope, receive, send))
    return sent


def _http_scope(method: str = "POST", key: bytes = b"key") -> dict:
    return {
        "type": "http",
        "method": method,
        "path": "/api/v1/probe/things",
        "headers": [(b"idempotency-key", key)],
    }


def _echo_app(
    *, status: int = 200, body: bytes = b"ok", chunks: int = 1, send_response: bool = True
) -> Callable:
    async def app(scope: dict, receive: Callable, send: Callable) -> None:
        while True:  # drain the request body like a real handler
            message = await receive()
            if message["type"] != "http.request" or not message.get("more_body", False):
                break
        if not send_response:
            return
        await send({"type": "http.response.start", "status": status, "headers": []})
        for index in range(chunks):
            await send(
                {
                    "type": "http.response.body",
                    "body": body,
                    "more_body": index < chunks - 1,
                }
            )

    return app


def test_non_http_scopes_pass_through() -> None:
    seen: list[str] = []

    async def app(scope: dict, receive: Callable, send: Callable) -> None:
        seen.append(scope["type"])

    middleware = IdempotencyMiddleware(app, store=InMemoryIdempotencyStore())
    asyncio.run(middleware({"type": "lifespan"}, None, None))
    assert seen == ["lifespan"]


def test_safe_methods_pass_through_even_with_the_header() -> None:
    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(_echo_app(), store=store)
    sent = _run_middleware(
        middleware, _http_scope(method="GET"), [{"type": "http.request", "body": b""}]
    )
    assert sent[0]["status"] == 200
    assert store._entries == {}  # no claim was made


def test_a_chunked_request_body_is_buffered_and_replayed_to_the_app() -> None:
    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(_echo_app(), store=store)
    inbound = [
        {"type": "http.request", "body": b"part-1", "more_body": True},
        {"type": "http.request", "body": b"part-2", "more_body": False},
    ]
    sent = _run_middleware(middleware, _http_scope(), inbound)
    assert sent[0]["status"] == 200
    assert len(store._entries) == 1  # claimed, executed, and completed
    entry = next(iter(store._entries.values()))
    assert entry.done is True


def test_header_matching_is_case_insensitive() -> None:
    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(_echo_app(), store=store)
    scope = _http_scope()
    scope["headers"] = [(b"Idempotency-Key", b"case-key")]
    sent = _run_middleware(middleware, scope, [{"type": "http.request", "body": b"{}"}])
    assert sent[0]["status"] == 200
    assert len(store._entries) == 1


def test_an_over_large_request_body_is_a_typed_413() -> None:
    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(_echo_app(), store=store, max_body_bytes=4)
    sent = _run_middleware(
        middleware, _http_scope(), [{"type": "http.request", "body": b"too big"}]
    )
    assert sent[0]["status"] == 413
    assert b"idempotency_body_too_large" in sent[1]["body"]
    assert store._entries == {}


def test_a_disconnect_mid_body_passes_through_unprocessed() -> None:
    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(_echo_app(), store=store)
    inbound = [
        {"type": "http.request", "body": b"partial", "more_body": True},
        {"type": "http.disconnect"},
    ]
    sent = _run_middleware(middleware, _http_scope(), inbound)
    assert sent[0]["status"] == 200  # the app still saw the request…
    assert store._entries == {}  # …but no claim was made for a dead request


def test_a_5xx_response_is_released_not_replayed() -> None:
    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(_echo_app(status=502), store=store)
    _run_middleware(middleware, _http_scope(), [{"type": "http.request", "body": b"{}"}])
    assert store._entries == {}  # released → a retry re-executes


def test_an_over_large_response_is_released_not_replayed() -> None:
    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(
        _echo_app(body=b"chunk", chunks=3), store=store, max_stored_response_bytes=8
    )
    sent = _run_middleware(middleware, _http_scope(), [{"type": "http.request", "body": b"{}"}])
    assert [m["body"] for m in sent if m["type"] == "http.response.body"] == [b"chunk"] * 3
    assert store._entries == {}  # too large to store → at-least-once fallback


def test_a_response_that_never_completes_is_released() -> None:
    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(_echo_app(send_response=False), store=store)
    sent = _run_middleware(middleware, _http_scope(), [{"type": "http.request", "body": b"{}"}])
    assert sent == []  # the app sent nothing…
    assert store._entries == {}  # …so nothing was stored


def test_the_replayed_receive_delegates_past_the_buffered_body() -> None:
    """An app that keeps listening after the body (e.g. for a disconnect) still can."""
    seen: list[str] = []

    async def listening_app(scope: dict, receive: Callable, send: Callable) -> None:
        await receive()  # the buffered body message
        seen.append((await receive())["type"])  # delegated to the real channel
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(listening_app, store=store)
    inbound = [{"type": "http.request", "body": b"{}"}, {"type": "http.disconnect"}]
    _run_middleware(middleware, _http_scope(), inbound)
    assert seen == ["http.disconnect"]


# --------------------------------------------------------------------------- #
# create_app wires the seam (fail-closed guard; default unchanged)
# --------------------------------------------------------------------------- #
def _spec() -> ModuleSpec:
    router = APIRouter()

    @router.get("/ping", response_model=str)
    def ping() -> str:
        return "pong"

    return ModuleSpec(
        name="probe", router=router, policy=Policy.public(reason="idempotency test")
    )


def test_create_app_uses_the_supplied_idempotency_store() -> None:
    store = InMemoryIdempotencyStore()
    client, _ = _build_client(store)
    client.post("/api/v1/probe/things", headers={"Idempotency-Key": "key-9"}, json={})
    assert len(store._entries) == 1  # the wired store holds the completed claim


def test_create_app_without_a_store_defaults_to_in_memory() -> None:
    create_app([_spec()])  # boots — the per-instance default needs no wiring


def test_boot_refuses_an_unmarked_store_when_a_shared_one_is_required() -> None:
    # Fail closed: a multi-instance promise with a per-instance backend refuses to boot…
    with pytest.raises(BootError, match="require_shared_idempotency_store"):
        create_app(
            [_spec()],
            idempotency_store=InMemoryIdempotencyStore(),
            require_shared_idempotency_store=True,
        )
    with pytest.raises(BootError, match="require_shared_idempotency_store"):
        create_app([_spec()], require_shared_idempotency_store=True)  # …and so does none at all.


def test_boot_accepts_a_marked_shared_store() -> None:
    shared = mark_shared_idempotency_store(InMemoryIdempotencyStore())
    create_app([_spec()], idempotency_store=shared, require_shared_idempotency_store=True)
