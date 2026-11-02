"""Readiness turns 503 within 30 seconds of losing the database, and 200 within 30 of its return.

The database half of ADR 0191's readiness bound (the shared-store half is in
``test_readiness.py``). It needs a real server, so it runs where ``TERP_TEST_POSTGRES_URL``
names one: CI's PostgreSQL lane runs this module, and anywhere else it skips. The app reaches
the server through a TCP relay the test owns, so losing the database is what a deployment
sees when its database goes away: every connection the pool holds is reset and a new one is
refused, and then the same address answers again.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from terp.core import create_app

_BOUND_SECONDS = 30.0


class _Relay:
    """A TCP relay to the database server that can be cut and restored on one port."""

    def __init__(self, host: str, port: int) -> None:
        self._target = (host, port)
        self.port = 0
        self._listener: socket.socket | None = None
        self._sockets: list[socket.socket] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", self.port))
        listener.listen(16)
        self.port = listener.getsockname()[1]
        self._listener = listener
        threading.Thread(target=self._accept, args=(listener,), daemon=True).start()

    def cut(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            # Shut down before closing: on Linux, closing a listener another thread is
            # blocked accepting on leaves it listening until that accept returns, so the
            # relay went on accepting and readiness never saw the database go. Shutting it
            # down wakes the accept. Windows refuses to shut down a listener (it is not
            # connected), and there the close alone wakes the accept.
            try:
                listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            listener.close()
        with self._lock:
            sockets, self._sockets = self._sockets, []
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def _accept(self, listener: socket.socket) -> None:
        while True:
            try:
                client, _address = listener.accept()
            except OSError:
                return
            try:
                server = socket.create_connection(self._target)
            except OSError:
                client.close()
                continue
            with self._lock:
                self._sockets += [client, server]
            for source, sink in ((client, server), (server, client)):
                threading.Thread(target=self._pump, args=(source, sink), daemon=True).start()

    @staticmethod
    def _pump(source: socket.socket, sink: socket.socket) -> None:
        try:
            while data := source.recv(65536):
                sink.sendall(data)
        except OSError:
            pass
        finally:
            for sock in (source, sink):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass


@pytest.fixture
def relayed_database(terp_pg_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Relay]:
    from terp.core._internal.engine import reset_engine
    from terp.core.config import settings

    url = make_url(terp_pg_url)
    relay = _Relay(url.host or "127.0.0.1", url.port or 5432)
    relay.start()
    relayed_url = url.set(host="127.0.0.1", port=relay.port)
    if sys.platform == "win32":
        # psycopg on Windows never sees a refused connection: it waits out its connect
        # timeout, 130 s by default, where Linux (every container a deployment runs)
        # fails at once. Measured against a real server; the bound is the driver's there,
        # so the test gives the driver the bound a deployment would (ADR 0191, *Open*).
        relayed_url = relayed_url.update_query_dict({"connect_timeout": "5"})
    relayed = relayed_url.render_as_string(hide_password=False)
    monkeypatch.setattr(settings, "DATABASE_URL", relayed)
    reset_engine()
    yield relay
    relay.cut()
    reset_engine()


def _until(client: TestClient, status: int) -> float:
    """Seconds until readiness answers *status*, each answer held to the bound.

    The bound is on the answer, not on the gap between two polls: a probe that blocks for
    two minutes and then answers 503 has not answered within 30 seconds."""
    started = time.monotonic()
    while True:
        answered = client.get("/health/ready").status_code
        elapsed = time.monotonic() - started
        assert elapsed < _BOUND_SECONDS, (
            f"readiness answered {answered} after {elapsed:.1f}s, waiting for {status}"
        )
        if answered == status:
            return elapsed
        time.sleep(0.2)


def test_readiness_follows_the_database_away_and_back(relayed_database: _Relay) -> None:
    client = TestClient(create_app([]))
    assert client.get("/health/ready").json() == {"status": "ready", "checks": {"database": "ok"}}

    relayed_database.cut()
    lost = _until(client, 503)
    assert client.get("/health/ready").json()["checks"] == {"database": "error"}

    relayed_database.start()
    back = _until(client, 200)
    print(f"database lost: 503 after {lost:.2f}s; database back: 200 after {back:.2f}s")
