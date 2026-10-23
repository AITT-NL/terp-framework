"""Readiness asks the database and every shared store this deployment made mandatory (ADR 0191).

ADR 0024's readiness answered for the database alone, so an instance that could not reach the
shared store it had been told to require still reported ready, while every request that needed
the store failed. A store a ``require_shared_*`` guard requires is now part of the answer:

* **which stores**: exactly those a ``require_shared_*`` made mandatory, each asked through
  its own ``ping()``; a required store that cannot be asked refuses the boot, and a store
  that is wired but not required is never asked. Workers and the outbox backlog stay out;
* **how it is asked**: on a worker thread, within a bound, and never twice at once, so a
  store that accepts connections and never answers turns readiness 503 within the bound and
  cannot pile up a thread per probe;
* **the timing** ADR 0191 holds it to: 503 within 30 seconds of losing a mandatory store, and
  200 within 30 seconds of its recovery. Measured here against a store
  that really goes away: terp-cap-redis' own stores, over redis-py's own client and real
  sockets, to an in-test server speaking the Redis protocol, which is stopped, made silent
  and started again on the same port. The database half needs a
  server, so it runs in the PostgreSQL lane (``test_readiness_postgres.py``).
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from terp.core import (
    BootError,
    InMemoryCacheStore,
    InMemoryIdempotencyStore,
    InMemoryThrottleStore,
    create_app,
    mark_shared_cache_store,
    mark_shared_idempotency_store,
    mark_shared_throttle_store,
    register_mandatory_store,
)
from terp.core.db import get_session
from terp.core.health import (
    READINESS_PROBE_TIMEOUT_SECONDS,
    build_health_router,
    mandatory_stores,
    reset_mandatory_stores,
)

from terp.capabilities.redis import RedisCacheStore, RedisIdempotencyStore, RedisThrottleStore

#: ADR 0191's bound on both transitions.
_BOUND_SECONDS = 30.0


class _RespServer:
    """A Redis-protocol server that answers PING, and can be stopped, silenced and restarted.

    Enough of the protocol for redis-py's client to connect and ping through its own code:
    every command is read as a RESP array and answered ``+PONG`` for PING and ``+OK`` for
    anything else (the client's own ``CLIENT SETINFO`` on connect). *silent* accepts and
    reads but never answers, as a paused server does.
    """

    def __init__(self) -> None:
        self.port = 0
        self.silent = False
        self._listener: socket.socket | None = None
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_REUSEADDR") and not hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", self.port))
        listener.listen(16)
        self.port = listener.getsockname()[1]
        self._listener = listener
        threading.Thread(target=self._accept, args=(listener,), daemon=True).start()

    def stop(self) -> None:
        """Gone: the listener closed and every connection reset, as a stopped container."""
        listener, self._listener = self._listener, None
        if listener is not None:
            listener.close()
        with self._lock:
            clients, self._clients = self._clients, []
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            client.close()

    def _accept(self, listener: socket.socket) -> None:
        while True:
            try:
                client, _address = listener.accept()
            except OSError:
                return
            with self._lock:
                self._clients.append(client)
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    @staticmethod
    def _answer(words: list[bytes]) -> bytes:
        command = words[0].upper() if words else b""
        if command == b"PING":
            return b"+PONG\r\n"
        if command == b"HELLO":
            # The RESP3 handshake redis-py opens with: a map naming the protocol agreed.
            version = words[1] if len(words) > 1 else b"2"
            return b"%1\r\n$5\r\nproto\r\n:" + version + b"\r\n"
        return b"+OK\r\n"

    def _serve(self, client: socket.socket) -> None:
        reader = client.makefile("rb")
        try:
            while True:
                header = reader.readline()
                if not header:
                    return
                count = int(header[1:].strip()) if header.startswith(b"*") else 0
                words = []
                for _ in range(count):
                    size = int(reader.readline()[1:].strip())
                    words.append(reader.read(size + 2)[:size])
                while self.silent:
                    time.sleep(0.05)
                client.sendall(self._answer(words))
        except (OSError, ValueError):
            return


@pytest.fixture
def store_server() -> Iterator[_RespServer]:
    server = _RespServer()
    server.start()
    yield server
    server.silent = False
    server.stop()


@pytest.fixture(autouse=True)
def file_database(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:  # type: ignore[no-untyped-def]
    """A file database, as a deployment has: the in-memory default keeps one connection per
    thread, and readiness asks the stores on threads of their own."""
    from terp.core._internal.engine import reset_engine
    from terp.core.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{tmp_path / 'ready.db'}")
    reset_engine()
    yield
    reset_engine()


def _until(client: TestClient, status: int, *, within: float) -> float:
    """Poll readiness until it answers *status*; return how long that took."""
    started = time.monotonic()
    while True:
        if client.get("/health/ready").status_code == status:
            return time.monotonic() - started
        elapsed = time.monotonic() - started
        assert elapsed < within, f"readiness did not answer {status} within {within}s"
        time.sleep(0.2)


class _Probed:
    """A store standing in for a shared one: it says how to reach it, and can go away."""

    def __init__(self) -> None:
        self.down = False
        self.asked = 0

    def ping(self) -> None:
        self.asked += 1
        if self.down:
            raise ConnectionError("the store is gone")


class _ProbedThrottle(_Probed, InMemoryThrottleStore):
    def __init__(self) -> None:
        _Probed.__init__(self)
        InMemoryThrottleStore.__init__(self)


class _ProbedCache(_Probed, InMemoryCacheStore):
    def __init__(self) -> None:
        _Probed.__init__(self)
        InMemoryCacheStore.__init__(self)


class _ProbedIdempotency(_Probed, InMemoryIdempotencyStore):
    def __init__(self) -> None:
        _Probed.__init__(self)
        InMemoryIdempotencyStore.__init__(self)


def _shared_probed() -> tuple[_ProbedThrottle, _ProbedCache, _ProbedIdempotency]:
    return (
        mark_shared_throttle_store(_ProbedThrottle()),
        mark_shared_cache_store(_ProbedCache()),
        mark_shared_idempotency_store(_ProbedIdempotency()),
    )


def _required(throttle, cache, idempotency) -> FastAPI:  # type: ignore[no-untyped-def]
    return create_app(
        [],
        throttle_store=throttle,
        require_shared_throttle_store=True,
        cache_store=cache,
        require_shared_cache_store=True,
        idempotency_store=idempotency,
        require_shared_idempotency_store=True,
    )


# --------------------------------------------------------------------------- #
# which stores                                                                  #
# --------------------------------------------------------------------------- #
def test_without_a_required_store_readiness_is_the_database_alone() -> None:
    throttle, cache, idempotency = _shared_probed()
    client = TestClient(
        create_app([], throttle_store=throttle, cache_store=cache, idempotency_store=idempotency)
    )
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "checks": {"database": "ok"}}
    assert (throttle.asked, cache.asked, idempotency.asked) == (0, 0, 0), "wired is not required"


def test_every_required_store_is_asked_beside_the_database() -> None:
    throttle, cache, idempotency = _shared_probed()
    client = TestClient(_required(throttle, cache, idempotency))
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {
        "database": "ok",
        "cache_store": "ok",
        "idempotency_store": "ok",
        "throttle_store": "ok",
    }
    for store, name in ((throttle, "throttle_store"), (cache, "cache_store"),
                        (idempotency, "idempotency_store")):
        store.down = True
        gone = client.get("/health/ready")
        assert gone.status_code == 503, name
        assert gone.json()["status"] == "not_ready"
        assert gone.json()["checks"][name] == "error"
        assert gone.json()["checks"]["database"] == "ok", "the store, not the database"
        store.down = False
    assert client.get("/health/ready").status_code == 200


def test_a_database_that_cannot_answer_still_reports_every_store() -> None:
    throttle, cache, idempotency = _shared_probed()
    app = _required(throttle, cache, idempotency)

    def _broken_session():  # type: ignore[no-untyped-def]
        class _Session:
            def exec(self, statement):  # type: ignore[no-untyped-def]
                raise RuntimeError("database down")

            def close(self) -> None:
                return None

        yield _Session()

    app.dependency_overrides[get_session] = _broken_session
    answer = TestClient(app).get("/health/ready")
    assert answer.status_code == 503
    assert answer.json()["checks"] == {
        "database": "error",
        "cache_store": "ok",
        "idempotency_store": "ok",
        "throttle_store": "ok",
    }


@pytest.mark.parametrize(
    ("flag", "argument", "store"),
    [
        ("require_shared_throttle_store", "throttle_store", lambda: mark_shared_throttle_store(InMemoryThrottleStore())),
        ("require_shared_cache_store", "cache_store", lambda: mark_shared_cache_store(InMemoryCacheStore())),
        ("require_shared_idempotency_store", "idempotency_store", lambda: mark_shared_idempotency_store(InMemoryIdempotencyStore())),
    ],
    ids=["throttle", "cache", "idempotency"],
)
def test_a_required_store_readiness_cannot_ask_refuses_the_boot(
    flag: str, argument: str, store: Callable[[], object]
) -> None:
    """A shared store with no ping() of its own would be reported reachable by a check that
    cannot fail; the boot refuses it instead, naming the fix."""
    with pytest.raises(BootError, match=rf"{flag}=True makes the .* part of readiness .*ping\(\)"):
        create_app([], **{argument: store(), flag: True})


def test_the_in_process_stores_have_nothing_to_reach() -> None:
    assert InMemoryThrottleStore().ping() is None
    assert InMemoryCacheStore().ping() is None
    assert InMemoryIdempotencyStore().ping() is None


def test_a_capability_store_is_asked_while_its_capability_says_it_is_mandatory() -> None:
    probed = _Probed()
    mandatory = {"now": False}

    def _resolve():  # type: ignore[no-untyped-def]
        return probed.ping if mandatory["now"] else None

    register_mandatory_store("test_store", _resolve)
    try:
        register_mandatory_store("test_store", _resolve)  # the same registration again
        with pytest.raises(ValueError, match="already registered"):
            register_mandatory_store("test_store", lambda: None)
        assert list(mandatory_stores()) == sorted(mandatory_stores())
        client = TestClient(create_app([]))
        assert "test_store" not in client.get("/health/ready").json()["checks"]
        mandatory["now"] = True
        assert client.get("/health/ready").json()["checks"]["test_store"] == "ok"
        probed.down = True
        assert client.get("/health/ready").status_code == 503
    finally:
        saved = {name: resolve for name, resolve in mandatory_stores().items() if name != "test_store"}
        reset_mandatory_stores()
        for name, resolve in saved.items():
            register_mandatory_store(name, resolve)


# --------------------------------------------------------------------------- #
# how it is asked                                                               #
# --------------------------------------------------------------------------- #
def _hanging() -> tuple[Callable[[], None], threading.Event, list[int]]:
    release = threading.Event()
    calls: list[int] = []

    def _probe() -> None:
        calls.append(1)
        release.wait(10)

    return _probe, release, calls


def _router_app(probe: Callable[[], object], timeout: float) -> TestClient:
    app = FastAPI()
    app.include_router(
        build_health_router(readiness={"cache_store": probe}, probe_timeout=timeout),
        prefix="/health",
    )
    return TestClient(app)


def test_a_store_that_never_answers_is_not_ready_within_the_bound_and_asked_once() -> None:
    probe, release, calls = _hanging()
    client = _router_app(probe, timeout=0.3)
    try:
        started = time.monotonic()
        first = client.get("/health/ready")
        assert first.status_code == 503 and first.json()["checks"]["cache_store"] == "error"
        assert time.monotonic() - started < 2.0, "the bound, not the store, decides"
        again = client.get("/health/ready")
        assert again.status_code == 503
        assert calls == [1], "a probe still running is not asked again"
    finally:
        release.set()
    deadline = time.monotonic() + 5
    while client.get("/health/ready").status_code != 200:
        assert time.monotonic() < deadline, "the store answered, so readiness must recover"
        time.sleep(0.05)
    assert len(calls) == 2


def test_the_default_bound_is_two_seconds() -> None:
    assert READINESS_PROBE_TIMEOUT_SECONDS == 2.0


# --------------------------------------------------------------------------- #
# the rate limiter does not hide it                                             #
# --------------------------------------------------------------------------- #
class _Failing(_ProbedThrottle):
    def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        raise ConnectionError("the throttle store is gone")


def test_a_throttle_store_that_fails_lets_the_health_router_answer_and_nothing_else() -> None:
    """The rate limiter fails closed on a store error, and still does for every other path;
    on /health it lets the request through, so liveness stays up and readiness says 503 and
    names the store, instead of 429 for both."""
    store = mark_shared_throttle_store(_Failing())
    store.down = True
    client = TestClient(create_app([], throttle_store=store, require_shared_throttle_store=True))
    assert client.get("/health/live").status_code == 200
    ready = client.get("/health/ready")
    assert ready.status_code == 503 and ready.json()["checks"]["throttle_store"] == "error"
    assert client.get("/health").status_code == 404, "the bare prefix: passed through, unrouted"
    assert client.get("/docs").status_code == 429
    assert client.get("/healthz").status_code == 429, "a prefix match, not a string prefix"


# --------------------------------------------------------------------------- #
# the timing, against a store that really goes away                             #
# --------------------------------------------------------------------------- #
def _redis_app(server: _RespServer) -> TestClient:
    url = f"redis://127.0.0.1:{server.port}/0"
    return TestClient(
        create_app(
            [],
            throttle_store=RedisThrottleStore.from_url(url),
            require_shared_throttle_store=True,
            cache_store=RedisCacheStore.from_url(url),
            require_shared_cache_store=True,
            idempotency_store=RedisIdempotencyStore.from_url(url),
            require_shared_idempotency_store=True,
        )
    )


def test_readiness_turns_503_within_30s_of_losing_a_mandatory_store_and_200_after(
    store_server: _RespServer,
) -> None:
    client = _redis_app(store_server)
    ready = client.get("/health/ready")
    assert ready.status_code == 200, ready.json()
    assert set(ready.json()["checks"]) == {
        "database", "cache_store", "idempotency_store", "throttle_store"
    }

    store_server.stop()
    lost = _until(client, 503, within=_BOUND_SECONDS)
    assert client.get("/health/ready").json()["checks"]["cache_store"] == "error"

    store_server.start()  # the same port: the store is back where the app looks for it
    recovered = _until(client, 200, within=_BOUND_SECONDS)
    print(f"store lost: 503 after {lost:.2f}s; store back: 200 after {recovered:.2f}s")


def test_a_store_that_stops_answering_turns_readiness_503_within_the_bound(
    store_server: _RespServer,
) -> None:
    """A paused server: connections are accepted and nothing comes back. The rate limiter
    is kept off this store (a blocked counter would hold every request, readiness
    included), so what is measured is readiness alone."""
    url = f"redis://127.0.0.1:{store_server.port}/0"
    client = TestClient(
        create_app(
            [],
            cache_store=RedisCacheStore.from_url(url),
            require_shared_cache_store=True,
            idempotency_store=RedisIdempotencyStore.from_url(url),
            require_shared_idempotency_store=True,
        )
    )
    assert client.get("/health/ready").status_code == 200
    store_server.silent = True
    silenced = _until(client, 503, within=_BOUND_SECONDS)
    assert silenced < READINESS_PROBE_TIMEOUT_SECONDS + 2.0
    started = time.monotonic()
    assert client.get("/health/ready").status_code == 503
    assert time.monotonic() - started < 1.0, "a probe still waiting is not asked again"
    store_server.silent = False
    answered = _until(client, 200, within=_BOUND_SECONDS)
    print(f"store silent: 503 after {silenced:.2f}s; answering again: 200 after {answered:.2f}s")
