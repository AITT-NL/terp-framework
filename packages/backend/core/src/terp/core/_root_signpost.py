"""``GET /``: a signpost at the API's root, instead of a bare not-found document."""

from __future__ import annotations

from html import escape

from fastapi import FastAPI
from fastapi.responses import HTMLResponse


def mount_root_signpost(app: FastAPI, *, title: str, docs: bool) -> None:
    """Answer ``GET /`` with a signpost instead of a bare not-found document.

    A Terp app is two published ports in development and an interface in front
    of an API in production, and the API's root belongs to nobody: no module
    mounts there (every module router is prefixed ``/api/v1/<name>``), and
    route registration is frozen after composition, so nothing else can claim
    it either. FastAPI therefore answered it with ``{"detail":"Not Found"}`` —
    a correct 404 that reads, to the person who opened the wrong one of two
    addresses in a browser, as an application that is broken. It is the most
    reliably reachable dead end the platform has, and everything about it
    invites the reader to go looking for a bug in code they did not write.

    So it says where they are and where the interface is. Deliberately plain:

    * **HTML, not JSON.** The visitor arriving here is a browser, and a
      document is what a browser is for. Machines have the contract.
    * **No styling at all.** The security middleware serves
      ``default-src 'none'``, which blocks an inline stylesheet as surely as a
      remote one — and weakening a real header to decorate an error page would
      be a bad trade. Unstyled HTML still reads.
    * **Out of the contract** (``include_in_schema=False``). This is a landing
      page for a human, not API surface; putting it in the document would add
      a route to every generated client for something no client calls.

    *docs* is false where the docs endpoints are hidden (production, unless
    the security config opts in), and the link is then simply absent: pointing
    at ``/docs`` when it 404s would make this page a second dead end.

    Public, on the same footing as ``/health`` and for the same reason — an
    unauthenticated visitor is precisely who reaches it — and it carries
    nothing that authentication would be protecting: the app's own title, which
    the contract and the interface both publish already, plus two paths that are
    fixed for every Terp app. It answers ``GET`` only, so it adds no verb.
    """

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    def root() -> HTMLResponse:
        docs_line = (
            '<p>Interactive API documentation: <a href="/docs">/docs</a>.</p>'
            if docs
            else ""
        )
        return HTMLResponse(
            "<!doctype html>"
            f"<html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<title>{escape(title)} API</title></head><body>"
            f"<h1>{escape(title)} API</h1>"
            "<p>This is the API. It has no pages of its own; the user "
            "interface is served separately, on its own address.</p>"
            f"{docs_line}"
            '<p>Health: <a href="/health/live">/health/live</a> and '
            '<a href="/health/ready">/health/ready</a>.</p>'
            "</body></html>"
        )


__all__ = ["mount_root_signpost"]
