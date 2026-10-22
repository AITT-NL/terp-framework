"""The process half of logging: uvicorn's loggers and the interpreter's own printers.

Lifted out of ``terp.core.logging``, which keeps the record and its redaction. What is
here changes the *process*: it re-points loggers a server configured, and replaces the
hooks the interpreter prints a traceback or a warning with. ``configure_logging`` calls
it for the root logger only, and the hooks only outside local development.

The hooks are a per-app runtime seam (``reset_logging_runtime``), so the test plugin puts
back whatever a composed production app installed.
"""

from __future__ import annotations

import logging
import sys
import threading
import warnings
from types import TracebackType
from typing import Any, Final

from terp.core.logging import log_fields
from terp.core.runtime import register_runtime_seam

# What ``warnings.showwarning`` is before anything replaces it, and what capture_process
# replaced (``None`` while it has replaced nothing).
_INTERPRETER_SHOWWARNING: Final[Any] = warnings.showwarning
_replaced_showwarning: Any = None


#: uvicorn's loggers. Its command line configures them, with handlers of their own that
#: do not propagate, *before* it imports the app — so the composition root is the first
#: code that can re-point them, and does.
_SERVER_LOGGERS: Final[tuple[str, ...]] = (
    "uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi",
)


# The attribute an exception carries once the framework has written its record.
_LOGGED_MARK: Final[str] = "__terp_logged__"


def mark_logged(exc: BaseException) -> None:
    """Note that *exc* has had its one record, so the server does not write a second."""
    try:
        setattr(exc, _LOGGED_MARK, True)
    except (AttributeError, TypeError):  # an exception type that takes no attributes
        pass


class _AlreadyLoggedFilter(logging.Filter):
    """Drop the server's copy of an exception the framework has already written.

    Starlette's outermost middleware re-raises an exception after the app's handler has
    answered it with a 500, so that the server can log it too; uvicorn does, as
    "Exception in ASGI application" with the same traceback and without the request id.
    One exception, one record: the framework's carries the request id and the event.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if isinstance(record.exc_info, tuple) else None
        return not getattr(exc, _LOGGED_MARK, False)


def route_server_loggers() -> None:
    """Send uvicorn's lines through the root handler, and retire its duplicates.

    The framework writes one access line per request itself, naming the route template
    rather than the raw path (which holds ids and, in a query string, sometimes a token),
    so uvicorn's own access line would be a second, less careful copy of each request;
    and it writes the record of an unexpected exception itself, so uvicorn's copy of
    that is dropped too.
    """
    for name in _SERVER_LOGGERS:
        server_logger = logging.getLogger(name)
        for handler in list(server_logger.handlers):
            server_logger.removeHandler(handler)
        server_logger.propagate = True
    access = logging.getLogger("uvicorn.access")
    if access.level < logging.WARNING:
        access.setLevel(logging.WARNING)
    errors = logging.getLogger("uvicorn.error")
    if not any(isinstance(existing, _AlreadyLoggedFilter) for existing in errors.filters):
        errors.addFilter(_AlreadyLoggedFilter())


_uncaught_logger = logging.getLogger("terp.uncaught")


def _uncaught_fields(exc_type: type[BaseException]) -> dict[str, Any]:
    return log_fields(event="error.uncaught", error={"type": exc_type.__name__})


def _log_uncaught(
    exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
) -> None:
    """``sys.excepthook``: the exception that ends the process, as one record."""
    _uncaught_logger.critical(
        "uncaught %s: %s", exc_type.__name__, exc,
        exc_info=(exc_type, exc, tb), extra=_uncaught_fields(exc_type),
    )


def _log_uncaught_in_thread(args: threading.ExceptHookArgs) -> None:
    """``threading.excepthook``: a thread that died of an exception, as one record."""
    if args.exc_type is SystemExit:
        return
    name = args.thread.name if args.thread is not None else "-"
    _uncaught_logger.error(
        "uncaught %s in thread %s: %s", args.exc_type.__name__, name, args.exc_value,
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        extra=_uncaught_fields(args.exc_type),
    )


def _log_unraisable(unraisable: Any) -> None:
    """``sys.unraisablehook``: an exception nothing could raise (a finaliser's, say)."""
    _uncaught_logger.warning(
        "%s", unraisable.err_msg or "Exception ignored",
        exc_info=(unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback),
        extra=_uncaught_fields(unraisable.exc_type),
    )


def capture_process() -> None:
    """Route the interpreter's own printers — tracebacks and warnings — through logging.

    Only a hook still at the interpreter's default is replaced. One somebody else
    installed (a test runner's, an APM agent's) is theirs, and replacing it would take
    away what they installed it for.
    """
    if sys.excepthook is sys.__excepthook__:
        sys.excepthook = _log_uncaught
    if threading.excepthook is threading.__excepthook__:
        threading.excepthook = _log_uncaught_in_thread
    if sys.unraisablehook is sys.__unraisablehook__:
        sys.unraisablehook = _log_unraisable
    global _replaced_showwarning
    if warnings.showwarning is _INTERPRETER_SHOWWARNING:
        _replaced_showwarning = warnings.showwarning
        warnings.showwarning = _show_warning


def _show_warning(
    message: Warning | str,
    category: type[Warning],
    filename: str,
    lineno: int,
    file: Any = None,
    line: str | None = None,
) -> None:
    """``warnings.showwarning``: a warning as one record on ``py.warnings``.

    The stdlib's ``logging.captureWarnings`` in its own words, kept here so that what was
    replaced is known and can be put back (``reset_logging_runtime``); a warning sent to an
    explicit *file* still goes there.
    """
    if file is not None and _replaced_showwarning is not None:
        _replaced_showwarning(message, category, filename, lineno, file, line)
        return
    text = warnings.formatwarning(message, category, filename, lineno, line)
    logging.getLogger("py.warnings").warning("%s", text)


def _process_state() -> tuple[Any, ...]:
    return (
        sys.excepthook,
        threading.excepthook,
        sys.unraisablehook,
        warnings.showwarning,
        _replaced_showwarning,
    )


def _restore_process_state(state: tuple[Any, ...]) -> None:
    global _replaced_showwarning
    (
        sys.excepthook,
        threading.excepthook,
        sys.unraisablehook,
        warnings.showwarning,
        _replaced_showwarning,
    ) = state


def reset_logging_runtime() -> None:
    """Undo what :func:`capture_process` installed, and nothing else.

    Each hook that is this module's goes back to the interpreter's default; one somebody
    else installed stays. A runtime seam (``terp.core.runtime``), because ``create_app``
    installs these per app: a test that composes a production app must not leave a
    process that logs the next test's warnings instead of reporting them.
    """
    global _replaced_showwarning
    if sys.excepthook is _log_uncaught:
        sys.excepthook = sys.__excepthook__
    if threading.excepthook is _log_uncaught_in_thread:
        threading.excepthook = threading.__excepthook__
    if sys.unraisablehook is _log_unraisable:
        sys.unraisablehook = sys.__unraisablehook__
    if warnings.showwarning is _show_warning and _replaced_showwarning is not None:
        warnings.showwarning = _replaced_showwarning
    _replaced_showwarning = None


register_runtime_seam(
    "logging",
    capture=_process_state,
    restore=_restore_process_state,
    reset=reset_logging_runtime,
)


__all__ = [
    "capture_process",
    "mark_logged",
    "reset_logging_runtime",
    "route_server_loggers",
]
