"""What the log redacts: secrets, and the fields a model declares personal.

Lifted out of ``terp.core.logging`` so the record format and the redaction read as two
things, which they are: the formatter decides what a line looks like, this decides what
a line may never contain. Both the :class:`~terp.core.logging.RedactingFilter` and the
formatter call :func:`scrub`.

**Secrets** are recognised by key name and by shape in free text. **Personal data** is
recognised by declaration only (ADR 0190): a model handed to the log is rendered with each
:func:`~terp.core.Personal` field withheld, and a value under a declared field's name in a
mapping is replaced with ``[PERSONAL]``. An address with no declaration behind it -- a bare
string, an f-string -- has no shape to find, and passes through.
"""

from __future__ import annotations

import functools
import re
from typing import Any, Final

from pydantic import BaseModel

from terp.core.personal import PERSONAL, MaskedModel, is_personal_name

REDACTED: Final[str] = "[REDACTED]"

# Field / key names that may carry secrets (case-insensitive substring match).
SENSITIVE_KEY_PATTERNS: Final[tuple[str, ...]] = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "cookie",
)

# Credential values inside free text. Group 1 is the label that stays, so the line still
# says what was there; group 2 is the secret. ``(?!%)`` leaves a ``%s`` placeholder in a
# message template alone: the formatter scrubs the message again once its arguments are
# in, which is where the value actually appears.
_TEXT_SECRETS: Final[tuple[re.Pattern[str], ...]] = (
    # "Authorization: Bearer <credential>": the scheme word is not the secret. Until this
    # pattern consumed it, the scheme word was what got redacted and the credential stayed.
    re.compile(
        r"(authorization[\"']?\s*[:=]\s*[\"']?"
        r"(?:(?:bearer|basic|digest|negotiate|token|apikey)\s+)?)((?!%)[^\s\"',;]+)",
        re.IGNORECASE,
    ),
    re.compile(r"(bearer\s+)((?!%)[^\s\"',;]+)", re.IGNORECASE),
    # A cookie header's whole value: every pair in it is a session credential.
    re.compile(r"((?:set-)?cookie[\"']?\s*[:=]\s*[\"']?)((?!%)[^\r\n\"']+)", re.IGNORECASE),
    # "scheme://user:password@host": the password, never the host.
    re.compile(r"([a-z][a-z0-9+.\-]*://[^\s/:@]*:)((?!%)[^\s/@]+)(?=@)", re.IGNORECASE),
    # "password=...", "client_secret: ...", "api_key='...'".
    re.compile(
        r"((?:password|passwd|secret|token|api[_-]?key)[\w.\-]*[\"']?\s*[:=]\s*[\"']?)"
        r"((?!%)[^\s\"',;&]+)",
        re.IGNORECASE,
    ),
)
_REDACT_VALUE: Final[str] = r"\g<1>" + REDACTED

# Every pattern above needs one of these words (or a URL's "://") to match at all. Most
# text holds none of them, so one search for the words is the whole cost of most strings;
# the five substitutions run only where one could change something.
_TRIGGER: Final[re.Pattern[str]] = re.compile(
    r"authorization|bearer|cookie|://|password|passwd|secret|token|api[_-]?key",
    re.IGNORECASE,
)
_SENSITIVE_KEY: Final[re.Pattern[str]] = re.compile(
    "|".join(re.escape(pattern) for pattern in SENSITIVE_KEY_PATTERNS), re.IGNORECASE
)


@functools.lru_cache(maxsize=4096)
def looks_sensitive(key: str) -> bool:
    """Whether a key name is one a secret travels under (cached: key names repeat)."""
    return _SENSITIVE_KEY.search(key) is not None


def scrub_text(value: str) -> str:
    """*value* with every credential-shaped substring replaced by ``[REDACTED]``."""
    if _TRIGGER.search(value) is None:
        return value
    for pattern in _TEXT_SECRETS:
        value = pattern.sub(_REDACT_VALUE, value)
    return value


#: Values that cannot hold text, returned as they are without a closer look.
_INERT: Final[frozenset[type]] = frozenset({int, float, bool, type(None)})


def withheld_under(key: object) -> str | None:
    """What replaces a value logged under *key*: a secret's mark, a personal one, or ``None``."""
    name = key if type(key) is str else str(key)
    if looks_sensitive(name):
        return REDACTED
    if is_personal_name(name):
        return PERSONAL
    return None


class LoggedModel(MaskedModel):
    """A model as the log renders it: declared personal fields withheld, secret text redacted.

    It renders where the record is rendered -- ``%s`` and ``%r`` in the message, the JSON
    encoder for a field -- in pydantic's own shape, so a line reads as it always did, minus
    the values it may not hold.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return scrub_text(super().__repr__())

    def __str__(self) -> str:
        return scrub_text(super().__str__())


def scrub(value: Any) -> Any:
    """Recursively redact *value*: secrets by name and shape, personal fields by declaration.

    Runs on every field of every record, so the common shapes are tested first and by
    exact type; a subclass of one of them takes the slower ``isinstance`` path below.
    """
    kind = type(value)
    if kind is str:
        return scrub_text(value)
    if kind in _INERT:
        return value
    if isinstance(value, dict):
        return {
            key: mark if (mark := withheld_under(key)) is not None else scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub(item) for item in value)
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, BaseModel):
        return LoggedModel(value)
    return value


__all__ = [
    "REDACTED",
    "SENSITIVE_KEY_PATTERNS",
    "LoggedModel",
    "looks_sensitive",
    "scrub",
    "scrub_text",
    "withheld_under",
]
