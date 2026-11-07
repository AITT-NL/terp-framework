"""Short-lived links to a file's bytes, and the header a download hands out with them (ADR 0201).

A link is how a client that cannot send a bearer — an ``<audio>`` or ``<video>`` element, a
PDF viewer, a native client's media stack — reaches one file for a bounded time. Where the
file rests in a store that signs URLs, the store's link is used; where it does not (the local
adapter), the capability signs one itself: a token sealed under a sealing domain of its own,
carrying the file id and the expiry, served by the capability's one public route. The token is
the secret: whoever holds it reads until it expires, which is also the posture of a store's
signed URL. Expiry is the control; a link is not single-use, because a player makes many range
requests over one listening session.

The sealed form is the same ``enc:v1:`` Fernet token every other sealed value uses, under
``SECRET_KEY`` with the decrypt fallbacks of a rotation, so a link survives a key rotation for
exactly as long as the retired key is still listed, and no longer.
"""

from __future__ import annotations

import json
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from terp.core import SealingDomain

from terp.capabilities.files.content_types import _one_media_type

#: The lifetime a link gets when nothing selects one: long enough for a listening session.
DEFAULT_LINK_TTL: Final[timedelta] = timedelta(hours=1)

#: The longest lifetime any link may have, whoever asks: a link outlives nothing by days.
LINK_TTL_MAX: Final[timedelta] = timedelta(hours=24)

#: Where an app-signed link is served from: the capability's own public route, under its fixed
#: ``/api/v1/files`` mount. Path-absolute on purpose: the single-page app uses it as it is, and
#: a native client resolves it against the base URL it already holds, so no reverse-proxy
#: guesswork about scheme or host enters a link.
SIGNED_LINK_PATH: Final[str] = "/api/v1/files/link"

#: Media types a browser renders without running anything in them: the only ones a link may
#: ask to be shown inline. Everything else is an attachment whatever was asked, so a stored
#: HTML page can never be rendered on the API's own origin. The image family is admitted by
#: prefix, except an XML image (``image/svg+xml``): that is a document with script and event
#: handlers in it, and no magic signature pins what bytes declared as it really are.
_INLINE_TYPES: Final[tuple[str, ...]] = ("image/", "audio/", "video/", "application/pdf")
_INLINE_REFUSED_SUFFIXES: Final[tuple[str, ...]] = ("+xml", "/xml")

_DEFAULT_FILENAME: Final[str] = "upload"

_domain = SealingDomain("files.link", b"terp-cap-files link")


@dataclass(frozen=True)
class FileLink:
    """One link to a file's bytes: the URL, and when it stops working.

    ``url`` is absolute for a store's own signed URL and path-absolute
    (:data:`SIGNED_LINK_PATH`) for a link the capability signed itself.
    """

    url: str
    expires_at: datetime


def link_ttl(ttl: timedelta | None) -> timedelta:
    """The lifetime a link gets: *ttl*, or the default; refused outside ``(0, LINK_TTL_MAX]``."""
    lifetime = DEFAULT_LINK_TTL if ttl is None else ttl
    if lifetime <= timedelta(0) or lifetime > LINK_TTL_MAX:
        raise ValueError(
            f"a file link lives for a positive time of at most {LINK_TTL_MAX} (asked: {lifetime})"
        )
    return lifetime


def inline_allowed(content_type: str) -> bool:
    """Whether a link to a file of *content_type* may ask to be shown inline."""
    media_type = _one_media_type(content_type)
    if media_type is None or media_type.endswith(_INLINE_REFUSED_SUFFIXES):
        return False  # a list of types, or a row stored before 0.39.0 refused one, is not shown
    return any(media_type.startswith(prefix) for prefix in _INLINE_TYPES)


def content_disposition(filename: str, *, inline: bool = False) -> str:
    """A header-safe disposition for *filename* (RFC 5987 / RFC 6266).

    The stored filename is caller-supplied, so it is never emitted raw: the primary
    ``filename*`` value is fully percent-encoded (no CR/LF/quote can survive), and the
    ASCII ``filename`` fallback keeps only a conservative character set. ``inline`` is the
    caller's to decide only for a type :func:`inline_allowed` admits.
    """
    fallback = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in "._-") else "_" for ch in filename
    )
    encoded = urllib.parse.quote(filename, safe="")
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{fallback or _DEFAULT_FILENAME}\"; filename*=UTF-8''{encoded}"


def seal_link(file_id: uuid.UUID, expires_at: datetime, *, inline: bool) -> str:
    """The token of an app-signed link: the file id, its expiry and its disposition, sealed."""
    claims = {"f": file_id.hex, "e": int(expires_at.timestamp()), "i": int(inline)}
    return _domain.seal(json.dumps(claims, separators=(",", ":")))


def open_link(token: str, *, now: datetime | None = None) -> tuple[uuid.UUID, bool] | None:
    """``(file id, inline)`` for a live *token*, or ``None`` for one that cannot be honoured.

    ``None`` covers an altered token, one sealed by another domain or under a key no longer
    configured, one whose claims are not a link's, and an expired one alike: the route
    answers each with the same 404, and says nothing about which it was.
    """
    opened = _domain.open(token)
    if opened is None:
        return None
    try:
        claims = json.loads(opened[0])
        file_id = uuid.UUID(hex=claims["f"])
        expires_at = datetime.fromtimestamp(int(claims["e"]), tz=UTC)
        inline = bool(int(claims["i"]))
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    if (now or datetime.now(UTC)) >= expires_at:
        return None
    return file_id, inline


__all__ = [
    "DEFAULT_LINK_TTL",
    "LINK_TTL_MAX",
    "SIGNED_LINK_PATH",
    "FileLink",
    "content_disposition",
    "inline_allowed",
    "link_ttl",
    "open_link",
    "seal_link",
]
