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

# Credential values inside free text, as (label, value) pairs. The label is group 1 and
# stays, so the line still says what was there; the value is group 2, one or more
# characters of the class given, and is the secret.
_SECRET_SHAPES: Final[tuple[tuple[str, str, str], ...]] = (
    # "Authorization: Bearer <credential>": the scheme word is not the secret. Until this
    # pattern consumed it, the scheme word was what got redacted and the credential stayed.
    (
        r"(authorization[\"']?\s*[:=]\s*[\"']?"
        r"(?:(?:bearer|basic|digest|negotiate|token|apikey)\s+)?)",
        r"[^\s\"',;]",
        "",
    ),
    (r"(bearer\s+)", r"[^\s\"',;]", ""),
    # A cookie header's whole value: every pair in it is a session credential.
    (r"((?:set-)?cookie[\"']?\s*[:=]\s*[\"']?)", r"[^\r\n\"']", ""),
    # "scheme://user:password@host": the password, never the host. A password may hold an
    # unencoded "/" where a driver prints it raw, so only whitespace and "@" end it.
    (r"([a-z][a-z0-9+.\-]*://[^\s/:@]*:)", r"[^\s@]", "(?=@)"),
    # "password=...", "client_secret: ...", "api_key='...'".
    (
        r"((?:password|passwd|secret|token|api[_-]?key)[\w.\-]*[\"']?\s*[:=]\s*[\"']?)",
        r"[^\s\"',;&]",
        "",
    ),
)

# A printf-style placeholder as ``%`` formatting reads one: "%s", "%d", "%(name)s",
# "%-8.2f", "%%". Only a message *template* still holds placeholders, and only while its
# arguments are out of it; once rendered, a "%" is just a character of the value.
_PLACEHOLDER: Final[str] = (
    r"%(?:\([^)]*\))?[#0+\- ]*(?:\*|\d+)?(?:\.(?:\*|\d*))?[hlL]?[diouxXeEfFgGcrsa%]"
)

# Rendered text: every value goes, a "%-encoded" one included ("%40bc", "%2F...").
_TEXT_SECRETS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(f"{label}({value}+){after}", re.IGNORECASE)
    for label, value, after in _SECRET_SHAPES
)
# A template whose arguments are still to come: a value that starts with a placeholder is
# where an argument goes, and redacting it would break the format string. The formatter
# scrubs the message again once the arguments are in, which is where that value appears.
_TEMPLATE_SECRETS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(f"{label}((?!{_PLACEHOLDER}){value}+){after}", re.IGNORECASE)
    for label, value, after in _SECRET_SHAPES
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


def _substitute(value: str, patterns: tuple[re.Pattern[str], ...]) -> str:
    if _TRIGGER.search(value) is None:
        return value
    for pattern in patterns:
        value = pattern.sub(_REDACT_VALUE, value)
    return value


def scrub_text(value: str) -> str:
    """*value* with every credential-shaped substring replaced by ``[REDACTED]``."""
    return _substitute(value, _TEXT_SECRETS)


def scrub_template(template: str) -> str:
    """A ``%``-format *template* scrubbed as :func:`scrub_text`, its placeholders spared.

    Only for a message whose arguments have not been rendered into it yet: a value that
    starts with an actual placeholder (``password=%s``) is where an argument goes, so it
    stays for the arguments to fill. A value that merely starts with ``%`` is redacted.
    """
    return _substitute(template, _TEMPLATE_SECRETS)


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


def _scrub(value: Any, render: bool) -> Any:
    kind = type(value)
    if kind is str:
        return scrub_text(value)
    if kind in _INERT:
        return value
    if isinstance(value, dict):
        return {
            key: mark if (mark := withheld_under(key)) is not None else _scrub(item, render)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item, render) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub(item, render) for item in value)
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, BaseModel):
        return LoggedModel(value)
    if not render or isinstance(value, (int, float)):
        # A number of any subclass is written as a number, never as its text.
        return value
    return scrub_text(str(value))


def scrub(value: Any) -> Any:
    """Recursively redact *value*: secrets by name and shape, personal fields by declaration.

    A str is scrubbed, a dict loses the value under a credential-like or a declared personal
    key and is scrubbed item by item, as is a list or a tuple; a number, a bool and ``None``
    come back as they are, and a model comes back as a :class:`LoggedModel`. Anything else
    (an exception, a set, an object with its own ``__str__``) reaches the line through
    ``str()``, so its text is what is scrubbed and its text is what comes back: an object
    that kept its own form would be rendered after redaction.

    Runs on every field of every record, so the common shapes are tested first and by
    exact type; a subclass of one of them takes the slower ``isinstance`` path.
    """
    return _scrub(value, render=True)


def scrub_argument(value: Any) -> Any:
    """:func:`scrub` for a message's ``%`` arguments: an object keeps its own form.

    A conversion such as ``%d`` or ``%.2f`` needs the object itself, not its text, and the
    formatter scrubs the message once the arguments are rendered into it, which is where an
    object's text first exists. A credential-like or personal key in a mapping argument
    still goes here, and a model is still a :class:`LoggedModel`.
    """
    return _scrub(value, render=False)


__all__ = [
    "REDACTED",
    "SENSITIVE_KEY_PATTERNS",
    "LoggedModel",
    "looks_sensitive",
    "scrub",
    "scrub_argument",
    "scrub_template",
    "scrub_text",
    "withheld_under",
]
