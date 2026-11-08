"""What an upload may claim to be: the content-type allowlist (ADR 0068) and the magic-byte
check (ADR 0076), both enforced in the service chokepoint so no upload path can bypass them.

A declared content type is client input. The allowlist is the deployment's answer to *which*
types it stores at all — ``None``, the shipped default, allows every type, and a composition
root narrows it with one :func:`configure_allowed_content_types` line. The signature check is
the answer to *whether the bytes are what they claim*: for a media type whose file format has
a well-known signature, the upload's bytes must carry it, so a later consumer choosing a
decoder by the stored type is never handed mislabeled bytes. Both refuse with a typed 415
before any byte lands.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from terp.core import AppError


class UnsupportedContentTypeError(AppError):
    """415 — the upload's content type is not in the deployment's allowlist (ADR 0068)."""

    status_code = 415
    code = "content_type_not_allowed"
    default_message = "The uploaded file's content type is not allowed."


class ContentTypeMalformedError(AppError):
    """415 — the upload's content type is not one media type (ADR 0201)."""

    status_code = 415
    code = "content_type_malformed"
    default_message = "The uploaded file's content type must be one media type, such as image/png."


class ContentTypeMismatchError(AppError):
    """415 — the upload's bytes do not carry the declared content type's signature (ADR 0076)."""

    status_code = 415
    code = "content_type_mismatch"
    default_message = "The uploaded bytes do not match the declared content type."


_TCHARS = r"[!#$%&'*+.^_`|~0-9A-Za-z-]+"

#: One media type (RFC 9110, section 8.3.1): a type and a subtype, then parameters, each a token
#: or a quoted string. Never a list of types: a browser handed ``image/png, text/html`` takes the
#: last of them, so the type a check judged would not be the one the browser renders. No comma at
#: all, then, not even quoted, where one reader of the header could split on it.
_ONE_MEDIA_TYPE = re.compile(rf'{_TCHARS}/{_TCHARS}(?:[ \t]*;[ \t]*(?:{_TCHARS}=(?:{_TCHARS}|"[^"\\,\r\n]*"))?)*')


def one_media_type(value: str) -> str | None:
    """The bare media type *value* names, lowercased, when it is one media type; else ``None``."""
    if not _ONE_MEDIA_TYPE.fullmatch(value.strip()):
        return None
    return _normalized_media_type(value)


def served_media_type(content_type: str) -> str:
    """The ``Content-Type`` a stored file is served with: its own, unless it is not one type.

    Upload refuses such a type from 0.39.0; a row stored before then is served as bytes.
    """
    return content_type if one_media_type(content_type) is not None else "application/octet-stream"


def ensure_one_media_type(content_type: str) -> None:
    """Fail closed when *content_type* is not exactly one media type (ADR 0201).

    Stored, it is served back as the download's ``Content-Type``, and judged by the allowlist,
    the signature check and the inline rule first. A list of types, or anything a header could
    read otherwise, would let those judge one type while the browser renders another.
    """
    if one_media_type(content_type) is None:
        raise ContentTypeMalformedError(log_context={"content_type": content_type[:200]})


def _normalized_media_type(value: str) -> str:
    """The bare, lowercased media type: parameters stripped (``TEXT/Plain; q=1`` → ``text/plain``)."""
    return value.split(";", 1)[0].strip().lower()


# The deployment's upload content-type allowlist (ADR 0068). ``None`` — the default —
# allows every type (content type is descriptive metadata; ADR 0056's shipped posture).
# A composition root narrows it with one line; the check is enforced in the service
# chokepoint so no upload path (router or programmatic ``store``) can bypass it.
_allowed_content_types: tuple[str, ...] | None = None


def configure_allowed_content_types(allowed: Iterable[str]) -> None:
    """Restrict uploads to *allowed* media types (a composition-root line, ADR 0068).

    Entries are exact media types (``"application/pdf"``) or whole-subtype wildcards
    (``"image/*"``); they are normalized (lowercased, parameters stripped) and validated
    eagerly — an empty allowlist or a shapeless entry raises ``ValueError`` at boot, not
    at the first upload. Allow-everything is expressed by *not* configuring an allowlist
    (or :func:`reset_allowed_content_types`), never by a ``*/*`` entry — a visible,
    greppable default rather than a wildcard that reads like a restriction.
    """
    global _allowed_content_types
    normalized = tuple(dict.fromkeys(_normalized_media_type(item) for item in allowed))
    if not normalized:
        raise ValueError("the content-type allowlist must name at least one media type")
    for entry in normalized:
        base, separator, subtype = entry.partition("/")
        if not base or base == "*" or not separator or not subtype:
            raise ValueError(
                f"content-type allowlist entry {entry!r} must be 'type/subtype' or 'type/*'"
            )
    _allowed_content_types = normalized


def active_allowed_content_types() -> tuple[str, ...] | None:
    """The configured allowlist, or ``None`` when every content type is allowed."""
    return _allowed_content_types


def reset_allowed_content_types() -> None:
    """Restore the allow-everything default (the test-isolation reset)."""
    global _allowed_content_types
    _allowed_content_types = None


def ensure_content_type_allowed(content_type: str) -> None:
    """Fail closed when an allowlist is configured and *content_type* is not on it."""
    allowed = _allowed_content_types
    if allowed is None:
        return
    media_type = _normalized_media_type(content_type)
    for entry in allowed:
        if media_type == entry:
            return
        if entry.endswith("/*") and media_type.startswith(entry[:-1]):
            return
    raise UnsupportedContentTypeError(log_context={"content_type": media_type})


# Magic-byte sniffing (ADR 0076): for a media type whose file format carries a
# well-known signature, the upload's *bytes* must actually carry it — a declared
# content type is client input, and a later consumer (a browser rendering the
# stored `content_type`, a downstream parser choosing a decoder by it) must not
# be handed mislabeled bytes. Each entry maps a media type to its accepted
# signature alternatives; an alternative is a set of (offset, bytes) constraints
# that must **all** hold. A type not listed here has no canonical signature
# (text/*, application/json, …) and is not sniffed — the control refuses proven
# mismatches, never guesses.
_MAGIC_SIGNATURES: dict[str, tuple[tuple[tuple[int, bytes], ...], ...]] = {
    "image/png": (((0, b"\x89PNG\r\n\x1a\n"),),),
    "image/jpeg": (((0, b"\xff\xd8\xff"),),),
    "image/gif": (((0, b"GIF87a"),), ((0, b"GIF89a"),)),
    "image/webp": (((0, b"RIFF"), (8, b"WEBP")),),
    "image/bmp": (((0, b"BM"),),),
    "image/tiff": (((0, b"II*\x00"),), ((0, b"MM\x00*"),)),
    "application/pdf": (((0, b"%PDF-"),),),
    "application/zip": (((0, b"PK\x03\x04"),), ((0, b"PK\x05\x06"),), ((0, b"PK\x07\x08"),)),
    "application/gzip": (((0, b"\x1f\x8b"),),),
}

#: How many leading bytes the signature check reads: the longest constraint ends at offset
#: 8 + len(b"WEBP") = 12, and 16 keeps headroom.
SNIFF_LEN = 16


def ensure_bytes_match_declared_type(content_type: str, head: bytes) -> None:
    """Fail closed when the declared type has a known signature the bytes lack (ADR 0076)."""
    alternatives = _MAGIC_SIGNATURES.get(_normalized_media_type(content_type))
    if alternatives is None:
        return
    for constraints in alternatives:
        if all(
            head[offset : offset + len(signature)] == signature
            for offset, signature in constraints
        ):
            return
    raise ContentTypeMismatchError(
        log_context={"content_type": _normalized_media_type(content_type)}
    )


__all__ = [
    "SNIFF_LEN",
    "ContentTypeMalformedError",
    "ContentTypeMismatchError",
    "UnsupportedContentTypeError",
    "active_allowed_content_types",
    "configure_allowed_content_types",
    "ensure_bytes_match_declared_type",
    "ensure_content_type_allowed",
    "ensure_one_media_type",
    "one_media_type",
    "reset_allowed_content_types",
    "served_media_type",
]
