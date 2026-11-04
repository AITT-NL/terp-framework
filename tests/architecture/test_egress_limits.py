"""Outbound resource limits hold on the wire, before decoding and between reads."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import time

import httpx
import pytest

from terp.capabilities.egress import EgressClient, EgressFailedError, EgressPolicy, PinnedTarget
from terp.capabilities.egress.client import send_pinned
from terp.capabilities.egress._transport import Deadline

from .test_egress import _mock_httpx
from .test_mail import _issue


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "identity, gzip", ""])
def test_unnegotiated_compression_is_refused_without_reading_or_decoding(
    monkeypatch: pytest.MonkeyPatch, encoding: str,
) -> None:
    class UnreadBody(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("A compressed body reached the reader")
            yield b""  # pragma: no cover - generator protocol; the assertion always raises

    recorded = _mock_httpx(monkeypatch, lambda _r: httpx.Response(
        200, headers={"content-encoding": encoding}, stream=UnreadBody(),
    ))
    target = PinnedTarget("https://example.test/", "example.test", "93.184.216.34")
    with pytest.raises(EgressFailedError, match="content encoding"):
        send_pinned(target, "GET", None, {"Accept-Encoding": "gzip"}, 1.0, 1024)
    assert recorded[0].headers["accept-encoding"] == "identity"


def test_an_explicit_identity_encoding_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_httpx(monkeypatch, lambda _r: httpx.Response(
        200, headers={"content-encoding": " Identity "}, stream=httpx.ByteStream(b"ok"),
    ))
    target = PinnedTarget("https://example.test/", "example.test", "93.184.216.34")
    assert send_pinned(target, "GET", None, {}, 1.0, 2).content == b"ok"


@pytest.mark.parametrize("timeout,cap", [(0, 10), (float("inf"), 10), (1, 0), (1, 2.5)])
def test_direct_transport_also_requires_finite_bounds(timeout: float, cap: int) -> None:
    target = PinnedTarget("https://example.test/", "example.test", "93.184.216.34")
    with pytest.raises(ValueError):
        send_pinned(target, "GET", None, {}, timeout, cap)


def test_a_resolver_returning_after_the_budget_cannot_start_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    calls = []

    def resolve(_host: str) -> list[str]:
        now[0] = 2.0
        return ["93.184.216.34"]

    client = EgressClient(
        EgressPolicy(allowed_hosts=("example.test",), timeout_seconds=1),
        resolve=resolve, sender=lambda *args: calls.append(args),
    )
    with pytest.raises(EgressFailedError, match="time limit"):
        client.get("https://example.test/")
    assert calls == []


def test_the_deadline_preserves_a_shorter_io_timeout_and_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [10.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    deadline = Deadline(2.0)
    assert deadline.remaining(0.25) == 0.25
    now[0] = 11.0
    assert deadline.remaining() == 1.0
    now[0] = 12.0
    with pytest.raises(EgressFailedError):
        deadline.remaining()


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_regular_small_reads_cannot_extend_the_total_deadline(phase: str) -> None:
    stop = threading.Event()

    class Trickle(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            head = b"HTTP/1.1 200 OK\r\nContent-Length: 20\r\n\r\n"
            try:
                if phase == "body":
                    self.wfile.write(head)
                    content = b"x" * 20
                else:
                    content = head
                for byte in content:
                    if stop.wait(0.05):
                        break
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                stop.set()

        def log_message(self, *args: object) -> None:
            """The synthetic server has no request log."""

    server = HTTPServer(("127.0.0.1", 0), Trickle)
    server.timeout = 1
    worker = threading.Thread(target=server.handle_request, daemon=True)
    worker.start()
    client = EgressClient(EgressPolicy(
        allowed_hosts=("127.0.0.1",), allowed_schemes=("http",),
        allow_private_addresses=True, timeout_seconds=0.3,
    ))
    started = time.monotonic()
    try:
        with pytest.raises(EgressFailedError):
            client.get(f"http://127.0.0.1:{server.server_port}/")
        elapsed = time.monotonic() - started
        assert elapsed < 0.9  # the complete body would take at least a second
    finally:
        stop.set()
        worker.join(timeout=2)
        server.server_close()
    assert not worker.is_alive()


@pytest.mark.parametrize("hostname", ["localhost", "other.example.test"])
def test_deadline_transport_retains_tls_hostname_verification(
    tmp_path, monkeypatch: pytest.MonkeyPatch, hostname: str,
) -> None:
    authority = _issue(tmp_path, "localhost")
    ca_file = tmp_path / "http-authority.pem"
    ca_file.write_text(authority.ca_pem)
    monkeypatch.setenv("SSL_CERT_FILE", str(ca_file))

    class Reply(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args: object) -> None:
            """The synthetic server has no request log."""

    server = HTTPServer(("127.0.0.1", 0), Reply)
    server.timeout = 1
    server.socket = authority.server_context("localhost").wrap_socket(
        server.socket, server_side=True,
    )
    worker = threading.Thread(target=server.handle_request, daemon=True)
    worker.start()
    client = EgressClient(
        EgressPolicy(allowed_hosts=(hostname,), allow_private_addresses=True),
        resolve=lambda _host: ["127.0.0.1"],
    )
    try:
        url = f"https://{hostname}:{server.server_port}/"
        if hostname == "localhost":
            assert client.get(url).content == b"ok"
        else:
            with pytest.raises(EgressFailedError):
                client.get(url)
    finally:
        worker.join(timeout=2)
        server.server_close()
    assert not worker.is_alive()
