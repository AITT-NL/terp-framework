"""Structured logging: a request-id context var + secrets/PII redaction.

Two responsibilities, both *secure by default*:

1. A :data:`request_id_ctx` context var, set per request by the request-id
   middleware, so every log line emitted while handling a request carries the
   same correlation id — even in code that has no access to the ``Request``.
2. A :class:`RedactingFilter` installed on the root logger *and every handler*
   that scrubs obvious secrets (``Authorization``/``Bearer`` values,
   password/token-like keys, and sensitive ``extra=`` fields) out of every log
   record, so a careless ``log.info`` — on any logger — cannot leak a credential.

:func:`configure_logging` wires both plus a :class:`StructuredFormatter` (one
JSON object per line) and is idempotent — the composition root calls it once.

This is the runtime half of a two-layer control: the matching build-time rule
(``terp.arch`` ``no_adhoc_logging_config``) forbids a module from configuring
logging itself, so redaction is never silently bypassed.
"""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from typing import Any, Final

# Request-scoped correlation id. Set by the request-id middleware; read by
# :class:`RequestContextFilter` and :func:`get_request_id`. Outside a request the
# value is ``None`` and renders as ``"-"``.
request_id_ctx: ContextVar[str | None] = ContextVar("terp_request_id", default=None)

_REDACTED: Final[str] = "[REDACTED]"

# Field / key names that may carry secrets (case-insensitive substring match).
_SENSITIVE_KEY_PATTERNS: Final[tuple[str, ...]] = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "cookie",
)

# Substrings inside free-form messages that name a credential value to redact.
_AUTHORIZATION_RE: Final[re.Pattern[str]] = re.compile(
    r"(authorization\s*[:=]\s*)([A-Za-z0-9_\-.+/=]+)",
    re.IGNORECASE,
)
_BEARER_RE: Final[re.Pattern[str]] = re.compile(
    r"(bearer\s+)([A-Za-z0-9_\-.+/=]+)",
    re.IGNORECASE,
)

# The built-in ``LogRecord`` attributes; anything else on a record is an
# application-supplied ``extra=`` field and is subject to redaction.
_STANDARD_LOGRECORD_ATTRS: Final[frozenset[str]] = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName", "message", "asctime", "request_id",
    }
)


def get_request_id() -> str | None:
    """Return the current request's correlation id, or ``None`` outside a request."""
    return request_id_ctx.get()


def _looks_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(pattern in lowered for pattern in _SENSITIVE_KEY_PATTERNS)


def _scrub(value: Any) -> Any:
    """Recursively redact secrets from *value* (dicts, sequences, and strings)."""
    if isinstance(value, dict):
        return {
            key: (_REDACTED if _looks_sensitive(str(key)) else _scrub(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub(item) for item in value)
    if isinstance(value, str):
        scrubbed = _AUTHORIZATION_RE.sub(r"\1" + _REDACTED, value)
        return _BEARER_RE.sub(r"\1" + _REDACTED, scrubbed)
    return value


class RedactingFilter(logging.Filter):
    """Redact obvious secrets from a record's message, ``args``, and ``extra`` fields."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _scrub(record.msg)
        if isinstance(record.args, dict):
            record.args = _scrub(record.args)
        elif isinstance(record.args, tuple):
            record.args = tuple(_scrub(arg) for arg in record.args)
        for key, value in list(record.__dict__.items()):
            if key in _STANDARD_LOGRECORD_ATTRS:
                continue
            if _looks_sensitive(key):
                setattr(record, key, _REDACTED)
            elif isinstance(value, (str, dict, list, tuple)):
                setattr(record, key, _scrub(value))
        return True


class RequestContextFilter(logging.Filter):
    """Inject the current ``request_id`` from the context var into every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get() or "-"
        return True


class StructuredFormatter(logging.Formatter):
    """Render each record as a single JSON line (machine-parseable, structured).

    Application-supplied ``extra=`` fields (anything that is not a built-in
    ``LogRecord`` attribute) are emitted under a nested ``"extra"`` object so the
    structured context a caller attached actually reaches the log line -- e.g. the
    audit log-only sink's ``audit_action`` / ``audit_target_*``. Those fields have
    already passed through :class:`RedactingFilter` on the handler, so secrets are
    masked before they ever reach this formatter.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", None) or "-",
            "message": record.getMessage(),
        }
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_LOGRECORD_ATTRS
        }
        if extra:
            payload["extra"] = extra
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _protect_handler(handler: logging.Handler) -> logging.Handler:
    """Ensure *handler* renders structured JSON and redacts + injects request context.

    Redaction must live on the **handler**: a record emitted by a child logger is
    filtered by each handler it reaches during propagation, not by an ancestor
    logger's filters. Installing the filter only on the root logger would let a
    child logger bypass redaction through a pre-existing root/uvicorn handler.
    """
    handler.setFormatter(StructuredFormatter())
    if not any(isinstance(f, RedactingFilter) for f in handler.filters):
        handler.addFilter(RedactingFilter())
    if not any(isinstance(f, RequestContextFilter) for f in handler.filters):
        handler.addFilter(RequestContextFilter())
    return handler


def configure_logging(
    level: int = logging.INFO, *, logger: logging.Logger | None = None
) -> None:
    """Idempotently install redaction + request-context logging on *logger*.

    Adds a :class:`RedactingFilter` and :class:`RequestContextFilter` to the
    logger and to **every handler** (so child-logger records cannot bypass
    redaction), and renders records through a :class:`StructuredFormatter`. Safe
    to call repeatedly — the composition root calls it once at boot. *logger*
    defaults to the root logger; tests may pass a throwaway logger.
    """
    target = logger if logger is not None else logging.getLogger()
    target.setLevel(level)

    if not any(isinstance(existing, RedactingFilter) for existing in target.filters):
        target.addFilter(RedactingFilter())
    if not any(isinstance(existing, RequestContextFilter) for existing in target.filters):
        target.addFilter(RequestContextFilter())

    if not target.handlers:
        target.addHandler(_protect_handler(logging.StreamHandler()))
    else:
        for handler in target.handlers:
            _protect_handler(handler)


__all__ = [
    "RedactingFilter",
    "RequestContextFilter",
    "StructuredFormatter",
    "configure_logging",
    "get_request_id",
    "request_id_ctx",
]
