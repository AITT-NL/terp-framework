"""Error-path rules: one envelope, and nothing a library wrote inside it.

The error path is the one place an application improvises a message for a
client. Everywhere else the shape is declared -- a response model, a schema, a
serializer -- and the rules that guard those declarations do not reach a string
a handler builds on the spot. These two close that gap from both ends.

``errors_use_the_typed_envelope`` is about which exception is raised: the web
framework's own HTTP error names a status code and a message directly, and the
envelope ``terp.core`` assembles for every other failure is bypassed for that one
response. ``no_exception_text_in_responses`` is about what goes inside the one
that is raised: a caught exception's text is a library's diagnostic string,
written for an operator reading a log, and forwarding it verbatim publishes
whatever it happens to name -- a table, an absolute path, an internal host.

Both are deliberately narrow. They look at a ``raise`` statement and nothing
else: no cross-file resolution, no data-flow, no guess about what a helper
returns. The forms that fall outside are recorded as residuals in the Terp
Standard rather than claimed.
"""

from __future__ import annotations

import ast
import builtins
import pathlib
from collections.abc import Iterator

from terp.arch._ast import base_name, iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _rel

#: The web framework's raw HTTP error, however it is imported. Both spellings an
#: app can reach (``fastapi`` re-exports Starlette's) leave the same leaf name,
#: which is what :func:`base_name` returns.
_RAW_HTTP_ERROR = "HTTPException"

#: Every exception name the language itself ships. Anything ending in ``Error``
#: or ``Exception`` that is NOT one of these is an application or framework error
#: -- the kind that reaches a client through the envelope. Read from ``builtins``
#: rather than listed, so a new builtin cannot silently start being treated as an
#: application error.
_BUILTIN_EXCEPTIONS = frozenset(
    name
    for name in dir(builtins)
    if isinstance(getattr(builtins, name), type)
    and issubclass(getattr(builtins, name), BaseException)
)

#: Keyword arguments that carry the message a client sees. ``log_context`` is
#: deliberately absent: it is attached to the log line and never serialised, so it
#: is where a caught exception's text is *supposed* to go.
_MESSAGE_KEYWORDS = frozenset({"detail", "message", "msg", "title"})

#: The traceback formatter, which needs no bound exception to reach the same text.
_TRACEBACK_FORMATTERS = frozenset({"format_exc", "format_exception"})


def _raised_name(node: ast.Raise) -> str | None:
    """The simple name of the exception *node* raises, or ``None`` for a re-raise."""
    return None if node.exc is None else base_name(node.exc)


def check_errors_use_the_typed_envelope(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Application modules raise the platform's typed errors, not raw HTTP errors.

    ``raise HTTPException(...)`` names a status code and a message directly, so
    that one response skips the envelope every other failure goes through -- the
    stable machine-readable code, the consistent body shape, and the single place
    messages are worded. A client then receives two error formats from one API and
    cannot tell which it is holding. Raise an ``AppError`` subclass
    (``NotFoundError``, ``ConflictError``, ...) instead.

    Only a ``raise`` counts. Importing the framework's error, catching it, and
    re-raising the caught one are all how an adapter recognises a failure the
    framework itself produced, and none of them builds a response.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or _raised_name(node) != _RAW_HTTP_ERROR:
                continue
            violations.append(
                ArchViolation(
                    "errors_use_the_typed_envelope",
                    rel,
                    node.lineno,
                    "raise HTTPException builds a response outside the typed error "
                    "envelope, so this endpoint answers in a shape nothing else uses; "
                    "raise an AppError subclass (NotFoundError, ConflictError, "
                    "PermissionDeniedError, ValidationFailedError)",
                )
            )
    return violations


def _is_response_error(name: str | None) -> bool:
    """True for an error type that reaches a client, false for one of the language's.

    A name ending in ``Error`` or ``Exception`` that the interpreter does not
    already define is an application or framework error, and an application or
    framework error is what the envelope renders. A builtin raised inside a
    handler is an internal control-flow signal -- it reaches a client only as a
    generic 500 whose message the framework writes -- so it is not this rule's
    business.
    """
    if name is None or name in _BUILTIN_EXCEPTIONS:
        return False
    return name.endswith("Error") or name.endswith("Exception")


def _message_expressions(call: ast.Call) -> list[ast.expr]:
    """The arguments of *call* that end up in the message a client reads.

    Every positional argument (an error's message is positional in both shapes a
    Terp app raises -- ``AppError(message)`` and ``HTTPException(status, detail)``)
    plus the keywords that name a client-visible message. A non-message keyword
    such as ``log_context`` is excluded on purpose, and that exclusion is the
    compliant path: the exception's own text belongs there.
    """
    return [*call.args, *(kw.value for kw in call.keywords if kw.arg in _MESSAGE_KEYWORDS)]


def _borrows_exception_text(expression: ast.expr, bound: tuple[str, ...]) -> bool:
    """True when *expression* reads a caught exception, by name or by traceback.

    ``bound`` is every name the enclosing handlers bound (``except E as exc``), and
    it is empty for a handler that bound nothing -- in which case the traceback
    formatter is still a way to reach the same text, so it is checked either way.
    """
    for node in ast.walk(expression):
        if isinstance(node, ast.Name) and node.id in bound:
            return True
        if isinstance(node, ast.Call) and base_name(node.func) in _TRACEBACK_FORMATTERS:
            return True
    return False


def _raises_inside_handlers(
    node: ast.AST, bound: tuple[str, ...] | None = None
) -> Iterator[tuple[ast.Raise, tuple[str, ...]]]:
    """Yield every ``raise`` under an ``except``, once, with the names in scope.

    ``bound`` is ``None`` outside a handler and a (possibly empty) tuple inside
    one, so "in a handler that bound nothing" stays distinguishable from "not in a
    handler at all". A nested handler does not hide the outer one's exception, so
    the names accumulate.

    Descending once and carrying the scope down is what keeps a raise from being
    reported twice. Walking each handler independently visits a raise inside nested
    handlers once per enclosing handler, and a raise that reaches the exception
    through the traceback formatter -- which matches whatever the binding is --
    then produces the same file and line as two findings.
    """
    if isinstance(node, ast.ExceptHandler):
        names = () if bound is None else bound
        bound = (*names, node.name) if node.name is not None else names
    if bound is not None and isinstance(node, ast.Raise):
        yield node, bound
    for child in ast.iter_child_nodes(node):
        yield from _raises_inside_handlers(child, bound)


def check_no_exception_text_in_responses(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A raised error's message never carries the caught exception's own text.

    Inside ``except ... as exc:``, building the message from ``exc`` -- ``str(exc)``,
    ``repr(exc)``, an f-string, ``exc.args``, ``%``-formatting -- or from
    ``traceback.format_exc()`` forwards a library's diagnostic string to whoever
    made the request. That string is not chosen, reviewed or versioned, and it
    routinely names a table, a statement, an absolute path or an internal host.

    Chaining the cause (``raise NotFoundError("Order not found") from exc``) is the
    compliant shape and is untouched: the exception stays in the log, out of the
    body. ``log_context={"cause": str(exc)}`` is untouched for the same reason --
    the envelope never serialises it. A builtin raised inside a handler is left
    alone too: it is internal control flow, and the framework writes the message a
    client would see.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node, bound in _raises_inside_handlers(tree):
            if not isinstance(node.exc, ast.Call):
                continue
            if not _is_response_error(base_name(node.exc.func)):
                continue
            if not any(
                _borrows_exception_text(expression, bound)
                for expression in _message_expressions(node.exc)
            ):
                continue
            violations.append(
                ArchViolation(
                    "no_exception_text_in_responses",
                    rel,
                    node.lineno,
                    "the error's message is built from the caught exception, so a "
                    "library's diagnostic text (a table, a path, an internal host) "
                    "reaches the client verbatim; write the message and pass the "
                    "cause instead (raise ...Error('...') from exc, or "
                    "log_context={'cause': str(exc)}, which is never serialised)",
                )
            )
    return violations


__all__ = [
    "check_errors_use_the_typed_envelope",
    "check_no_exception_text_in_responses",
]
