"""HTTPX transport with one deadline shared by every network operation.

HTTPX's ordinary timeout restarts for each read. The public httpcore backend
interface lets the transport reduce that timeout before each socket operation,
including repeated reads of headers. No abandoned request thread keeps a socket
alive after the caller's deadline.
"""
from __future__ import annotations

import ssl
import time
from collections.abc import Iterator
from typing import Any

import httpcore
import httpx  # arch-allow-no-raw-outbound-http: the sanctioned egress transport adapts the public HTTPX/httpcore transport interfaces

from terp.capabilities.egress.errors import EgressFailedError


class Deadline:
    def __init__(self, seconds: float) -> None:
        self.expires = time.monotonic() + seconds

    def remaining(self, timeout: float | None = None) -> float:
        remaining = self.expires - time.monotonic()
        if remaining <= 0:
            raise EgressFailedError("The outbound request exceeded its time limit.")
        return remaining if timeout is None else min(remaining, timeout)


class _DeadlineStream(httpcore.NetworkStream):
    def __init__(self, stream: httpcore.NetworkStream, deadline: Deadline) -> None:
        self.stream = stream
        self.deadline = deadline

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self.stream.read(max_bytes, timeout=self.deadline.remaining(timeout))

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        # SyncStream.write loops over send(), resetting its timeout each time.
        # Python's socket/SSLSocket.sendall instead bounds the entire write.
        sock = self.stream.get_extra_info("socket")
        sock.settimeout(self.deadline.remaining(timeout))
        sock.sendall(buffer)

    def start_tls(
        self, ssl_context: ssl.SSLContext, server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.NetworkStream:
        stream = self.stream.start_tls(
            ssl_context, server_hostname=server_hostname,
            timeout=self.deadline.remaining(timeout),
        )
        return _DeadlineStream(stream, self.deadline)

    def get_extra_info(self, info: str) -> Any:
        return self.stream.get_extra_info(info)

    def close(self) -> None:
        self.stream.close()


class _DeadlineBackend(httpcore.SyncBackend):
    def __init__(self, deadline: Deadline) -> None:
        self.deadline = deadline

    def connect_tcp(
        self, host: str, port: int, timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.NetworkStream:
        stream = super().connect_tcp(
            host, port, timeout=self.deadline.remaining(timeout),
            local_address=local_address, socket_options=socket_options,
        )
        return _DeadlineStream(stream, self.deadline)


class _ResponseStream(httpx.SyncByteStream):
    def __init__(self, response: httpcore.Response) -> None:
        self.response = response

    def __iter__(self) -> Iterator[bytes]:
        yield from self.response.iter_stream()

    def close(self) -> None:
        self.response.close()


class DeadlineTransport(httpx.BaseTransport):
    """One connection, no proxy/redirect/retry, with the original TLS identity."""

    def __init__(self, deadline: Deadline) -> None:
        self.pool = httpcore.ConnectionPool(
            # Keep the deployment's verified CA selection (SSL_CERT_FILE/DIR),
            # while the Client disables environment proxies that would unpin it.
            ssl_context=httpx.create_ssl_context(verify=True, trust_env=True),
            network_backend=_DeadlineBackend(deadline),
            max_connections=1, max_keepalive_connections=0,
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.pool.handle_request(httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme, host=request.url.raw_host,
                port=request.url.port, target=request.url.raw_path,
            ),
            headers=request.headers.raw, content=request.stream,
            extensions=request.extensions,
        ))
        return httpx.Response(
            response.status, headers=response.headers,
            stream=_ResponseStream(response), extensions=response.extensions,
        )

    def close(self) -> None:
        self.pool.close()
