"""Images read from a registry as data: manifests and blobs, each held to its digest.

``sign`` never pulls an image into an engine and never starts one (ADR 0187 decision 6). It
reads what the registry holds over the OCI distribution API, through the platform's declared
egress client (:mod:`terp.capabilities.egress`): an allowlist of exactly the release registry,
a timeout, a bounded read, no redirect followed but the one a blob store answers with, and
every address checked against the SSRF denylist, which only a registry on this machine's
loopback relaxes. Whatever comes back is accepted only when its SHA-256 is the digest asked
for, so a registry that answers wrongly is a refusal, never a different image.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from terp.cli.release._common import ReleaseError

#: The manifest kinds a release image may be: an index (choose the platform) or one image.
INDEX_TYPES = frozenset(
    {
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    }
)
IMAGE_TYPES = frozenset(
    {
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    }
)
_ACCEPT = ", ".join(sorted(INDEX_TYPES | IMAGE_TYPES))

#: What a manifest or a config may weigh, and a layer.
MANIFEST_LIMIT = 4 * 1024 * 1024
LAYER_LIMIT = 1024 * 1024 * 1024
_TIMEOUT = 120.0
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_REDIRECTS = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True)
class Response:
    """What came back from one request."""

    status: int
    headers: dict[str, str]
    body: bytes


#: One GET: url, headers, the response limit -> the response. Injectable, so every path of
#: the client is held without a network.
Getter = Callable[[str, dict[str, str], int], Response]


def egress_getter(host: str, *, http: bool) -> Getter:
    """The real transport: a declared egress client per host, built on first use.

    *host* is the registry (``host[:port]``). A blob store's redirect is followed to its own
    host over HTTPS only, under the same denylist: the blob is held to its digest either way.
    A client is made per host and per response limit, because the limit is the client's
    policy: one made for a manifest would hold every layer after it to a manifest's size.
    """
    try:
        from terp.capabilities.egress import EgressClient, EgressPolicy
    except ImportError as exc:
        raise ReleaseError(
            "reading a registry needs the egress capability: install terp-cli[release]"
        ) from exc
    clients: dict[tuple[str, bool, int], Any] = {}

    def get(url: str, headers: dict[str, str], limit: int) -> Response:
        parts = urllib.parse.urlsplit(url)
        own = parts.netloc == host
        key = (parts.hostname or "", own, limit)
        if key not in clients:
            clients[key] = EgressClient(
                EgressPolicy(
                    allowed_hosts=(key[0],),
                    timeout_seconds=_TIMEOUT,
                    max_response_bytes=limit,
                    allow_private_addresses=own and http,
                    allowed_schemes=("http",) if own and http else ("https",),
                )
            )
        from terp.capabilities.egress import EgressFailedError, EgressRefusedError

        try:
            answer = clients[key].get(url, headers=headers)
        except (EgressFailedError, EgressRefusedError) as exc:
            raise ReleaseError(
                f"the registry could not be read at {parts.netloc}", cause=str(exc.log_context)
            ) from exc
        return Response(answer.status_code, {k.lower(): v for k, v in answer.headers.items()}, answer.content)

    return get


@dataclass(frozen=True)
class Reference:
    """``host[:port]/path`` of one repository."""

    host: str
    path: str

    @classmethod
    def parse(cls, repository: str) -> Reference:
        host, _, path = repository.partition("/")
        if not path or "." not in host and ":" not in host and host != "localhost":
            raise ReleaseError(f"{repository!r} names no registry host")
        return cls(host, path)


class Registry:
    """The release registry, read through one :data:`Getter`."""

    def __init__(self, getter: Getter, *, http: bool = False, credentials: tuple[str, str] | None = None) -> None:
        self._get = getter
        self._scheme = "http" if http else "https"
        self._credentials = credentials
        self._tokens: dict[str, str] = {}

    def _url(self, ref: Reference, kind: str, name: str) -> str:
        return f"{self._scheme}://{ref.host}/v2/{ref.path}/{kind}/{name}"

    def _token(self, challenge: str, ref: Reference) -> str:
        """A bearer token for *challenge*, from the realm it names (the registry's own flow)."""
        fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        realm = fields.get("realm", "")
        if not realm.startswith("https://") and not (self._scheme == "http" and realm.startswith("http://")):
            raise ReleaseError(f"the registry asks for a token from {realm!r}, which is no HTTPS realm")
        query = {"service": fields.get("service", ""), "scope": fields.get("scope", f"repository:{ref.path}:pull")}
        headers = {}
        if self._credentials is not None:
            pair = f"{self._credentials[0]}:{self._credentials[1]}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(pair).decode()
        answer = self._get(f"{realm}?{urllib.parse.urlencode(query)}", headers, MANIFEST_LIMIT)
        if answer.status != 200:
            raise ReleaseError(f"the registry's token service answered {answer.status}")
        try:
            loaded = json.loads(answer.body)
            return str(loaded.get("token") or loaded["access_token"])
        except (ValueError, KeyError, AttributeError) as exc:
            raise ReleaseError("the registry's token service answered no token") from exc

    def _fetch(self, ref: Reference, url: str, headers: dict[str, str], limit: int) -> Response:
        sent = dict(headers)
        if ref.host in self._tokens:
            sent["Authorization"] = f"Bearer {self._tokens[ref.host]}"
        answer = self._get(url, sent, limit)
        challenge = answer.headers.get("www-authenticate", "")
        if answer.status == 401 and challenge.lower().startswith("bearer "):
            self._tokens[ref.host] = self._token(challenge[7:], ref)
            answer = self._get(url, {**headers, "Authorization": f"Bearer {self._tokens[ref.host]}"}, limit)
        elif answer.status == 401 and challenge.lower().startswith("basic") and self._credentials:
            pair = f"{self._credentials[0]}:{self._credentials[1]}".encode()
            answer = self._get(url, {**headers, "Authorization": "Basic " + base64.b64encode(pair).decode()}, limit)
        for _hop in range(3):
            if answer.status not in _REDIRECTS or "location" not in answer.headers:
                break
            answer = self._get(urllib.parse.urljoin(url, answer.headers["location"]), {}, limit)
        return answer

    def manifest(self, repository: str, reference: str) -> tuple[str, str, bytes]:
        """``(digest, media type, bytes)`` of the manifest *reference* (a tag or a digest) names."""
        ref = Reference.parse(repository)
        answer = self._fetch(ref, self._url(ref, "manifests", reference), {"Accept": _ACCEPT}, MANIFEST_LIMIT)
        if answer.status != 200:
            raise ReleaseError(f"{repository} has no manifest {reference} (the registry answered {answer.status})")
        digest = "sha256:" + hashlib.sha256(answer.body).hexdigest()
        if _DIGEST.fullmatch(reference) and digest != reference:
            raise ReleaseError(f"{repository} answered {digest} for the manifest {reference}")
        try:
            kind = json.loads(answer.body).get("mediaType") or answer.headers.get("content-type", "")
        except (ValueError, AttributeError) as exc:
            raise ReleaseError(f"the manifest {reference} of {repository} is not JSON") from exc
        return digest, str(kind).split(";")[0].strip(), answer.body

    def blob(self, repository: str, digest: str, limit: int = MANIFEST_LIMIT) -> bytes:
        """The blob *digest* names, refused unless its bytes hash to it."""
        if _DIGEST.fullmatch(digest) is None:
            raise ReleaseError(f"{digest!r} is not a sha256 digest")
        ref = Reference.parse(repository)
        answer = self._fetch(ref, self._url(ref, "blobs", digest), {}, limit)
        if answer.status != 200:
            raise ReleaseError(f"{repository} has no blob {digest} (the registry answered {answer.status})")
        if "sha256:" + hashlib.sha256(answer.body).hexdigest() != digest:
            raise ReleaseError(f"{repository} answered other bytes for the blob {digest}")
        return answer.body

    def image(self, repository: str, digest: str, platform: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
        """``(image manifest digest, manifest, config)`` of *digest*, an index resolved by platform."""
        found, kind, body = self.manifest(repository, digest)
        manifest = json.loads(body)
        if kind in INDEX_TYPES:
            wanted = dict(zip(("os", "architecture"), platform.split("/")[:2], strict=False))
            chosen = [
                entry for entry in manifest.get("manifests", [])
                if {key: entry.get("platform", {}).get(key) for key in wanted} == wanted
            ]
            if len(chosen) != 1:
                raise ReleaseError(f"{repository}@{digest} holds {len(chosen)} images for {platform}")
            found, kind, body = self.manifest(repository, chosen[0]["digest"])
            manifest = json.loads(body)
        if kind not in IMAGE_TYPES:
            raise ReleaseError(f"{repository}@{digest} is a {kind or 'manifest of no type'}, not an image")
        config = json.loads(self.blob(repository, manifest["config"]["digest"]))
        return found, manifest, config


__all__ = [
    "IMAGE_TYPES",
    "INDEX_TYPES",
    "LAYER_LIMIT",
    "Getter",
    "Reference",
    "Registry",
    "Response",
    "egress_getter",
]
