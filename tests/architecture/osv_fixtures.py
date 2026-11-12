"""A vulnerability database on this machine's loopback, answering OSV's API for real.

The tests of ``terp.cli.release._osv`` and of ``terp maintenance`` ask it over HTTP through
the declared egress client, exactly as they ask ``https://api.osv.dev``: only the address
differs, and the client allows plain HTTP to the loopback alone.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class FakeOSV:
    """What the database holds and how it answers: advisories by id, ids by package URL."""

    advisories: dict[str, dict[str, Any]] = field(default_factory=dict)
    matches: dict[str, list[str]] = field(default_factory=dict)
    #: Package URLs answered one id per page, with a continuation token until the last.
    paged: set[str] = field(default_factory=set)
    #: A status every request answers with instead (500, 429, ...), or None.
    status: int | None = None
    #: Raw bytes every request answers with instead of JSON, or None.
    body: bytes | None = None
    batches: list[list[dict[str, Any]]] = field(default_factory=list)
    fetched: list[str] = field(default_factory=list)
    url: str = ""

    def add(self, advisory_id: str, purls: list[str], **record: Any) -> None:
        self.advisories[advisory_id] = {"id": advisory_id, **record}
        for purl in purls:
            self.matches.setdefault(purl, []).append(advisory_id)

    def _result(self, query: dict[str, Any]) -> dict[str, Any]:
        purl = query["package"]["purl"]
        ids = sorted(self.matches.get(purl, []))
        if purl not in self.paged:
            return {"vulns": [{"id": found, "modified": "2026-01-01T00:00:00Z"} for found in ids]} if ids else {}
        page = int(query.get("page_token") or 0)
        result: dict[str, Any] = {"vulns": [{"id": ids[page], "modified": "2026-01-01T00:00:00Z"}]}
        if page + 1 < len(ids):
            result["next_page_token"] = str(page + 1)
        return result

    def answer(self, method: str, path: str, body: bytes) -> tuple[int, bytes]:
        if self.status is not None:
            return self.status, b"{}"
        if self.body is not None:
            return 200, self.body
        if method == "POST" and path == "/v1/querybatch":
            queries = json.loads(body)["queries"]
            self.batches.append(queries)
            return 200, json.dumps({"results": [self._result(query) for query in queries]}).encode()
        if method == "GET" and path.startswith("/v1/vulns/"):
            advisory_id = path.removeprefix("/v1/vulns/")
            self.fetched.append(advisory_id)
            if advisory_id not in self.advisories:
                return 404, b'{"code": 5, "message": "Bug not found."}'
            return 200, json.dumps(self.advisories[advisory_id]).encode()
        return 404, b"{}"


@contextmanager
def serving(database: FakeOSV) -> Iterator[FakeOSV]:
    """*database* served on an ephemeral loopback port for the length of the block."""

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            status, payload = database.answer(method, self.path, self.rfile.read(length))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # BaseHTTPRequestHandler's interface
            self._reply("GET")

        def do_POST(self) -> None:  # BaseHTTPRequestHandler's interface
            self._reply("POST")

        def log_message(self, *args: object) -> None:  # the suite's output stays the suite's
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    database.url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield database
    finally:
        server.shutdown()
        server.server_close()


def affected(ecosystem: str, name: str, *events: dict[str, str]) -> dict[str, Any]:
    """One ``affected`` entry of an advisory: a package and one ECOSYSTEM range of *events*."""
    kind = "SEMVER" if ecosystem == "npm" else "ECOSYSTEM"
    return {"package": {"ecosystem": ecosystem, "name": name}, "ranges": [{"type": kind, "events": list(events)}]}
