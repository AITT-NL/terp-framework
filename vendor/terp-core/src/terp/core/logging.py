"""Structured logging: one JSON record per line, in a versioned schema, with secrets redacted.

Four responsibilities, all *secure by default*:

1. **One record shape.** Every line is a JSON object in the ``terp-log/1`` schema
   (:data:`LOG_SCHEMA`; the JSON Schema ships beside this module as
   ``log-record.schema.json`` and :func:`log_record_schema` loads it). It always carries
   ``time`` (UTC, RFC 3339, milliseconds), ``schema``, ``level``, ``logger``,
   ``request_id`` and ``message``; framework events add typed fields (``event``,
   ``http``, ``actor``, ``tenant``, ``guard``, ``error``, ``context``). A key is only
   ever *added*: a reader holding an older release's lines beside a newer one's reads
   both, because nothing it already knows changes meaning.
2. A :data:`request_id_ctx` context var, set per request by the request-id
   middleware, so every log line emitted while handling a request carries the
   same correlation id — even in code that has no access to the ``Request``.
3. A :class:`RedactingFilter` installed on the root logger *and every handler*
   that scrubs **secrets** out of every record: credential-like key names
   (``password``, ``token``, ``secret``, ``api_key``, ``cookie``, ``authorization``),
   an ``Authorization`` / ``Bearer`` / cookie value, a URL's password and a
   ``password=...``-shaped pair in free text — in the message, its arguments,
   ``extra=`` fields and exception text. Personal data is withheld where it is
   **declared** (``Personal``, ADR 0190): a model is rendered with its personal fields
   as ``[PERSONAL]``, and so is a value under a declared field's name. An undeclared
   name, address or email has no shape to find, and passes through.
4. :func:`configure_logging` wires both plus a :class:`StructuredFormatter` and is
   idempotent — the composition root calls it once. It also re-points uvicorn's own
   loggers at the same handler and, outside local development, routes uncaught
   exceptions and warnings through it, so a deployed process prints no line in any
   other shape.

A failure *inside* logging never escapes and never prints a plain traceback: a record
that cannot be redacted is withheld, and one that cannot be rendered becomes a
``log.failure`` record in the same schema.

This is the runtime half of a two-layer control: the matching build-time rule
(``terp.arch`` ``no_adhoc_logging_config``) forbids a module from configuring
logging itself, so redaction is never silently bypassed.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from importlib import resources
from typing import Any, Final

from terp.core._redaction import scrub as _scrub
from terp.core._redaction import scrub_text as _scrub_text
from terp.core._redaction import withheld_under as _withheld_under

#: The id of the record shape, carried by every line in its ``schema`` key.
LOG_SCHEMA: Final[str] = "terp-log/1"
_SCHEMA_FILE: Final[str] = "log-record.schema.json"

# Request-scoped correlation id. Set by the request-id middleware; read by
# :class:`RequestContextFilter` and :func:`get_request_id`. Outside a request the
# value is ``None`` and renders as ``"-"``.
request_id_ctx: ContextVar[str | None] = ContextVar("terp_request_id", default=None)

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

# The record attribute framework code attaches its typed fields under (``log_fields``).
# The formatter lifts the known keys to the top level of the line; an app's own
# ``extra=`` stays under ``"extra"``, where it cannot collide with them.
_FIELDS: Final[str] = "_terp_log"
#: The top-level keys an event may add, in the order they are written.
_EVENT_FIELDS: Final[tuple[str, ...]] = (
    "event", "http", "actor", "tenant", "guard", "error", "context",
)
#: Every top-level key a line can carry; the schema declares exactly these.
TOP_LEVEL_FIELDS: Final[tuple[str, ...]] = (
    "time", "schema", "level", "logger", "request_id", "message",
    *_EVENT_FIELDS, "extra", "exc_info", "stack_info",
)
# Attributes that are neither the record's nor the app's context: uvicorn attaches an
# ANSI-coloured copy of its message for its own console formatter.
_NOT_EXTRA: Final[frozenset[str]] = frozenset({_FIELDS, "color_message"})

_PLAIN_FORMATTER = logging.Formatter()


def get_request_id() -> str | None:
    """Return the current request's correlation id, or ``None`` outside a request."""
    return request_id_ctx.get()


def log_record_schema() -> dict[str, Any]:
    """The JSON Schema (draft 2020-12) every line conforms to, shipped with terp-core."""
    text = resources.files("terp.core").joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    return json.loads(text)


def log_fields(**fields: Any) -> dict[str, Any]:
    """The ``extra=`` mapping that attaches framework *fields* to one record."""
    return {_FIELDS: fields}


def _withhold(record: logging.LogRecord, exc: BaseException) -> None:
    """Replace a record that could not be redacted with one that says so.

    Fail closed: when redaction itself fails, the content it was meant to clean is the
    one thing that must not reach the line, so all of it goes — the message, its
    arguments, the app's ``extra=`` fields and the traceback.
    """
    record.msg = "a log record was withheld: redacting it failed"
    record.args = None
    record.exc_info = None
    record.exc_text = None
    record.stack_info = None
    for key in [key for key in record.__dict__ if key not in _STANDARD_LOGRECORD_ATTRS]:
        del record.__dict__[key]
    record.__dict__[_FIELDS] = {"event": "log.failure", "error": {"type": type(exc).__name__}}


class RedactingFilter(logging.Filter):
    """Redact secrets and declared personal fields from a record's message, ``args``,
    ``extra`` fields and exception text."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            self._redact(record)
        except Exception as exc:  # noqa: BLE001 - a failing redaction withholds, never raises
            _withhold(record, exc)
        return True

    def _redact(self, record: logging.LogRecord) -> None:
        if not isinstance(record.msg, str):
            # An exception or an object logged as the message renders through str();
            # rendering it here is what lets its text be scrubbed, and a model renders
            # with its declared personal fields withheld.
            record.msg = str(_scrub(record.msg))
        record.msg = _scrub_text(record.msg)
        if isinstance(record.args, dict):
            record.args = _scrub(record.args)
        elif isinstance(record.args, tuple):
            record.args = tuple(_scrub(arg) for arg in record.args)
        if record.exc_info and not record.exc_text:
            # Render the traceback once, here, so every formatter downstream reads the
            # scrubbed copy (``logging.Formatter`` caches ``exc_text`` and prefers it).
            record.exc_text = _PLAIN_FORMATTER.formatException(record.exc_info)
        if isinstance(record.exc_text, str):
            record.exc_text = _scrub_text(record.exc_text)
        if isinstance(record.stack_info, str):
            record.stack_info = _scrub_text(record.stack_info)
        for key, value in list(record.__dict__.items()):
            if key in _STANDARD_LOGRECORD_ATTRS:
                continue
            if key == _FIELDS and isinstance(value, dict):
                # The framework's own fields are built from declarations and typed values
                # (a route template, a rule label, an id, a status); the one that carries
                # what an app handed over is ``context``, an error's log_context.
                if "context" in value:
                    setattr(record, key, {**value, "context": _scrub(value["context"])})
            elif (mark := _withheld_under(key)) is not None:
                setattr(record, key, mark)
            else:
                setattr(record, key, _scrub(value))


class RequestContextFilter(logging.Filter):
    """Inject the current ``request_id`` from the context var into every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get() or "-"
        return True


# The last second rendered, and its text: records arrive many to a second, and the
# seconds are the expensive part. A tuple is replaced whole, so a thread reads a pair.
_last_second: tuple[int, str] = (-1, "")


def _rfc3339(created: float, msecs: float) -> str:
    """*created* as UTC RFC 3339 with milliseconds: ``2026-10-21T08:15:02.317Z``."""
    global _last_second
    second = int(created)
    cached_second, text = _last_second
    if second != cached_second:
        text = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(second))
        _last_second = (second, text)
    return "%s.%03dZ" % (text, msecs)


class StructuredFormatter(logging.Formatter):
    """Render each record as a single ``terp-log/1`` JSON line.

    Application-supplied ``extra=`` fields (anything that is not a built-in
    ``LogRecord`` attribute) are emitted under a nested ``"extra"`` object so the
    structured context a caller attached actually reaches the log line -- e.g. the
    audit log-only sink's ``audit_action`` / ``audit_target_*``. Those fields have
    already passed through :class:`RedactingFilter` on the handler, so secrets are
    masked before they ever reach this formatter. The rendered message, and a
    traceback this formatter has to render itself, are scrubbed here as well: an
    argument's own text (an exception, an object) only exists once it is rendered.

    Formatting never raises: a record that cannot be rendered is written as a
    ``log.failure`` line instead.
    """

    def format(self, record: logging.LogRecord) -> str:
        try:
            return self._render(record)
        except Exception as exc:  # noqa: BLE001 - a log call must never raise
            return _failure_line(record, exc)

    def _render(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": _rfc3339(record.created, record.msecs),
            "schema": LOG_SCHEMA,
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", None) or "-",
            "message": _scrub_text(record.getMessage()),
        }
        fields = record.__dict__.get(_FIELDS)
        if isinstance(fields, dict):
            payload.update(
                (key, fields[key]) for key in _EVENT_FIELDS if fields.get(key) is not None
            )
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_LOGRECORD_ATTRS and key not in _NOT_EXTRA
        }
        if extra:
            payload["extra"] = extra
        if record.exc_text:
            payload["exc_info"] = record.exc_text
        elif record.exc_info:
            payload["exc_info"] = _scrub_text(self.formatException(record.exc_info))
        if record.stack_info:
            payload["stack_info"] = _scrub_text(record.stack_info)
        return json.dumps(payload, default=str)


def _failure_line(record: logging.LogRecord, exc: BaseException) -> str:
    """A ``log.failure`` line, built only from values that cannot fail to render."""
    created = record.created if isinstance(record.created, float) else time.time()
    return json.dumps(
        {
            "time": _rfc3339(created, (created % 1) * 1000),
            "schema": LOG_SCHEMA,
            "level": record.levelname if isinstance(record.levelname, str) else "ERROR",
            "logger": record.name if isinstance(record.name, str) else "-",
            "request_id": request_id_ctx.get() or "-",
            "message": "a log record could not be rendered",
            "event": "log.failure",
            "error": {"type": type(exc).__name__},
        }
    )


class _StructuredStreamHandler(logging.StreamHandler):
    """The handler ``configure_logging`` installs: a failed write is never a plain traceback.

    ``logging.Handler.handleError`` prints ``--- Logging error ---`` and a traceback to
    stderr, which would be the one line in the process that is not JSON. The formatter
    cannot fail, so what is left is the stream itself: when a write to it fails, one
    more is attempted in the record's own shape, and dropped if that fails too.
    """

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 - stdlib API
        try:
            self.stream.write(_failure_line(record, OSError("the log stream refused a write")))
            self.stream.write(self.terminator)
        except Exception:  # noqa: S110 - there is nowhere left to report to
            pass


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


#: The tenant seam (:func:`register_log_tenant_reader`): ``None`` until a capability fills it.
_tenant_reader: Callable[[], uuid.UUID | None] | None = None


def register_log_tenant_reader(read: Callable[[], uuid.UUID | None]) -> None:
    """Register how the access line reads the request's tenant (a capability seam).

    The tenancy capability registers its current-tenant getter, so the access line can
    name the tenant without the kernel importing tenancy -- the logging analogue of
    :func:`terp.core.register_job_tenant_context`. The tenant is only ever written beside
    an authenticated actor. Registration replaces any previous reader.
    """
    global _tenant_reader
    _tenant_reader = read


def active_log_tenant() -> uuid.UUID | None:
    """The tenant the registered reader reports right now, or ``None``."""
    return _tenant_reader() if _tenant_reader is not None else None


def configure_logging(
    level: int = logging.INFO,
    *,
    logger: logging.Logger | None = None,
    capture_process: bool = False,
) -> None:
    """Idempotently install redaction + request-context logging on *logger*.

    Adds a :class:`RedactingFilter` and :class:`RequestContextFilter` to the
    logger and to **every handler** (so child-logger records cannot bypass
    redaction), and renders records through a :class:`StructuredFormatter`. Safe
    to call repeatedly — the composition root calls it once at boot. *logger*
    defaults to the root logger; tests may pass a throwaway logger.

    For the root logger it also re-points uvicorn's loggers at the root handler. With
    *capture_process* -- the composition root passes it outside local development --
    the interpreter's default printers are replaced as well: an uncaught exception, one
    that ends a thread, an unraisable one and a warning each become a record.
    """
    target = logger if logger is not None else logging.getLogger()
    target.setLevel(level)

    if not any(isinstance(existing, RedactingFilter) for existing in target.filters):
        target.addFilter(RedactingFilter())
    if not any(isinstance(existing, RequestContextFilter) for existing in target.filters):
        target.addFilter(RequestContextFilter())

    if not target.handlers:
        target.addHandler(_protect_handler(_StructuredStreamHandler()))
    else:
        for handler in target.handlers:
            _protect_handler(handler)
    if logger is None:
        # Imported here, not at the top: the process half imports this module.
        from terp.core import _log_capture

        _log_capture.route_server_loggers()
        if capture_process:
            _log_capture.capture_process()


__all__ = [
    "LOG_SCHEMA",
    "TOP_LEVEL_FIELDS",
    "RedactingFilter",
    "RequestContextFilter",
    "StructuredFormatter",
    "active_log_tenant",
    "configure_logging",
    "get_request_id",
    "log_fields",
    "log_record_schema",
    "register_log_tenant_reader",
    "request_id_ctx",
]
