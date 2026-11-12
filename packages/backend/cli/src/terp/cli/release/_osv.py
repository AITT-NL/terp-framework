"""The vulnerability database, asked through the declared egress client (ADR 0187, ADR 0214).

Two callers ask the same database the same way. ``sign`` records which advisories each
package of a release's images matched when it was signed (:mod:`._sandbox`'s ``scan`` task),
and ``terp maintenance`` asks again later, so a finding in a report and the list a signed
manifest carries come from one database by one route.

The database is OSV's API (``/v1/querybatch``, ``/v1/vulns/<id>``) at a base URL the caller
names: ``https://api.osv.dev`` by default, or a mirror. Every request goes through
:mod:`terp.capabilities.egress`: an allowlist of exactly the base URL's host, HTTPS (plain HTTP
only on this machine's loopback), a timeout and a bounded read. Whatever cannot be asked is a
:class:`~._common.ReleaseError`, never an empty answer: a database that did not answer has not
said a package is clean.
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable
from typing import Any

from terp.cli.release._common import ReleaseError, egress_client

#: OSV's public API, the default database of ``sign`` and ``terp maintenance``.
DEFAULT_OSV = "https://api.osv.dev"

#: How many packages one batch request asks about (OSV accepts up to 1000).
BATCH = 500

#: What one batch answer and one advisory may weigh.
BATCH_LIMIT = 64 * 1024 * 1024
ADVISORY_LIMIT = 8 * 1024 * 1024

#: How many times a package's own continuation is followed before the answer is refused.
_PAGES = 20

#: Makes the client for one URL: ``(url, response limit) -> client``. Injectable, so every
#: path is held without a network.
ClientFor = Callable[[str, int], Any]


def _answer(send: Callable[[], Any]) -> dict[str, Any]:
    """The JSON object one request answered, or a refusal that says why there is none."""
    from terp.capabilities.egress import EgressFailedError, EgressRefusedError

    try:
        answer = send()
    except (EgressFailedError, EgressRefusedError) as exc:
        raise ReleaseError("the vulnerability database could not be asked", cause=str(exc.log_context)) from exc
    if answer.status_code != 200:
        raise ReleaseError(f"the vulnerability database answered {answer.status_code}")
    try:
        loaded = json.loads(answer.content)
    except ValueError as exc:
        raise ReleaseError("the vulnerability database answered no JSON") from exc
    if not isinstance(loaded, dict):
        raise ReleaseError("the vulnerability database answered no JSON object")
    return loaded


def query_batch(osv: str, purls: list[str], *, client_for: ClientFor | None = None) -> dict[str, list[str]]:
    """The advisory ids OSV answers for each package URL in *purls*; a clean one is left out.

    Asked :data:`BATCH` at a time. A package with more advisories than one answer holds comes
    back with a continuation token and is asked again with it until it has none, so a long
    list is never cut short.
    """
    url = osv.rstrip("/") + "/v1/querybatch"
    client = (client_for or egress_client)(url, BATCH_LIMIT)
    found: dict[str, set[str]] = {}
    #: (package URL, continuation token, how many pages of it were already read)
    pending: list[tuple[str, str | None, int]] = [(purl, None, 0) for purl in purls]
    while pending:
        chunk, pending = pending[:BATCH], pending[BATCH:]
        queries = [
            {"package": {"purl": purl}, **({"page_token": token} if token else {})} for purl, token, _ in chunk
        ]
        body = json.dumps({"queries": queries}).encode()
        results = _answer(
            lambda body=body: client.post(url, body=body, headers={"Content-Type": "application/json"})
        ).get("results", [])
        if not isinstance(results, list) or len(results) != len(chunk):
            raise ReleaseError("the vulnerability database answered for other packages than asked")
        for (purl, _token, pages), result in zip(chunk, results, strict=True):
            result = result if isinstance(result, dict) else {}
            ids = {str(vuln["id"]) for vuln in result.get("vulns") or [] if isinstance(vuln, dict) and "id" in vuln}
            if ids:
                found.setdefault(purl, set()).update(ids)
            if result.get("next_page_token"):
                if pages + 1 >= _PAGES:
                    raise ReleaseError(f"the vulnerability database kept answering {purl} with another page")
                pending.append((purl, str(result["next_page_token"]), pages + 1))
    return {purl: sorted(ids) for purl, ids in sorted(found.items())}


def advisory(osv: str, advisory_id: str, *, client_for: ClientFor | None = None) -> dict[str, Any]:
    """One advisory as OSV records it: its summary, aliases, severity and affected ranges."""
    url = osv.rstrip("/") + "/v1/vulns/" + urllib.parse.quote(advisory_id, safe="")
    client = (client_for or egress_client)(url, ADVISORY_LIMIT)
    found = _answer(lambda: client.get(url))
    if str(found.get("id")) != advisory_id:
        raise ReleaseError(f"the vulnerability database answered another advisory than {advisory_id}")
    return found


__all__ = ["ADVISORY_LIMIT", "BATCH", "BATCH_LIMIT", "DEFAULT_OSV", "ClientFor", "advisory", "query_batch"]
