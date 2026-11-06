"""Time-handling rules: an instant is an instant in memory, in storage and at the door.

A naive timestamp — one without a timezone — silently assumes some zone and cannot be
compared or stored correctly across zones. Three rules close that hole where it opens.
``no_naive_datetime`` refuses the naive *constructors* (the deprecated
``datetime.utcnow()`` and a bare ``datetime.now()``), so every value the app builds carries
an explicit zone. ``datetime_columns_are_timezone_aware`` holds every timestamp *column* to
``UtcDateTime`` from ``terp.core``, which stores the instant as UTC on every dialect.
``request_timestamps_carry_their_offset`` refuses each use of ``NaiveMeansUtc``, the one way
around the request boundary's refusal of a client timestamp with no offset (ADR 0206).
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass

from terp.arch._ast import base_name, iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _is_table_model_class, _rel


def _is_datetime_receiver(value: ast.expr) -> bool:
    """True when *value* is the ``datetime`` class (``datetime`` or ``x.datetime``)."""
    return base_name(value) == "datetime"


def check_no_naive_datetime(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Timestamps are timezone-aware; ``utcnow()`` and a bare ``now()`` are refused.

    ``datetime.utcnow()`` is deprecated and returns a naive value; ``datetime.now()``
    with no ``tz`` argument reads the process's local zone. Both erase the intended
    zone, so a stored or compared timestamp is silently wrong across zones. Pass an
    explicit zone instead (``datetime.now(UTC)``). A call to ``now`` with any
    argument is treated as zone-aware and left alone.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            func = node.func
            if not _is_datetime_receiver(func.value):
                continue
            if func.attr == "utcnow":
                violations.append(
                    ArchViolation(
                        "no_naive_datetime",
                        rel,
                        node.lineno,
                        "datetime.utcnow() is deprecated and returns a naive timestamp; "
                        "use datetime.now(UTC) so the value carries an explicit timezone",
                    )
                )
            elif func.attr == "now" and not node.args and not node.keywords:
                violations.append(
                    ArchViolation(
                        "no_naive_datetime",
                        rel,
                        node.lineno,
                        "datetime.now() with no tz reads the local zone and yields a naive "
                        "timestamp; pass an explicit zone (datetime.now(UTC))",
                    )
                )
    return violations


#: The modules that define or re-export Terp's timestamp types.
_CORE_MODULES = frozenset({"terp.core", "terp.core.base_models", "terp.core.timestamps"})


@dataclass(frozen=True)
class _CoreBindings:
    """What one file binds to ``terp.core``: a symbol's local names, and the module's."""

    names: frozenset[str]
    """Local names for the symbol itself (``from terp.core import UtcDateTime as T``)."""

    modules: frozenset[str]
    """Dotted local names that mean a ``terp.core`` module (``terp.core``, ``core``)."""


def _core_bindings(tree: ast.Module, symbol: str) -> _CoreBindings:
    """Resolve, file-locally, which names in *tree* are ``terp.core``'s *symbol*.

    A name the file binds for itself — a class, a function, an assignment — is the file's
    own, whatever it is called: a local class named like the symbol is not the symbol.
    """
    names: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                if node.module in _CORE_MODULES and alias.name == symbol:
                    names.add(alias.asname or alias.name)
                elif f"{node.module}.{alias.name}" in _CORE_MODULES:
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname is not None:
                    if alias.name in _CORE_MODULES:
                        modules.add(alias.asname)
                    continue
                parts = alias.name.split(".")
                modules.update(
                    ".".join(parts[:end])
                    for end in range(1, len(parts) + 1)
                    if ".".join(parts[:end]) in _CORE_MODULES
                )
    own = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    } | {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    return _CoreBindings(frozenset(names - own), frozenset(modules))


def _dotted(node: ast.expr) -> str | None:
    """``a.b.c`` for a chain of names and attributes, else ``None``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return None if head is None else f"{head}.{node.attr}"
    return None


def _names_core_symbol(node: ast.AST, symbol: str, bindings: _CoreBindings) -> bool:
    """True when *node* refers to ``terp.core``'s *symbol*, by name or as an attribute."""
    if isinstance(node, ast.Name):
        return node.id in bindings.names
    if isinstance(node, ast.Attribute) and node.attr == symbol:
        return _dotted(node.value) in bindings.modules
    return False


def _is_datetime_annotation(annotation: ast.expr) -> bool:
    """True for ``datetime`` and ``datetime | None``, however the name is qualified."""
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _is_datetime_annotation(annotation.left) or _is_datetime_annotation(annotation.right)
    return base_name(annotation) == "datetime"


#: Column types with a ``timezone`` switch. With ``timezone=True`` they keep the zone on
#: PostgreSQL and store the wall time on SQLite (ADR 0205), so they are no longer the answer.
_TIMESTAMP_COLUMN_TYPES = frozenset({"DateTime", "TIMESTAMP"})

_UTC_DATETIME = "UtcDateTime"

#: One message per way a timestamp column falls short, each naming the fix.
_COLUMN_MESSAGES = {
    "naive": (
        "{owner}.{field}: timestamp column declares no timezone, so the database stores an "
        "ambiguous local-zone value; declare the column type explicitly "
        "(Field(sa_type=UtcDateTime()), from terp.core)"
    ),
    "wall-time": (
        "{owner}.{field}: {spelling}(timezone=True) keeps the zone on PostgreSQL but stores "
        "the wall time on SQLite, so the instant a row records depends on where it was "
        "written; declare Field(sa_type=UtcDateTime()), from terp.core: the database column "
        "type is the same, so no migration is needed"
    ),
    "foreign": (
        "{owner}.{field}: this UtcDateTime is not terp.core's (the file defines it or imports "
        "it from elsewhere), so nothing holds it to storing the instant as UTC; import "
        "UtcDateTime from terp.core"
    ),
}


def _column_storage(value: ast.expr | None, bindings: _CoreBindings) -> tuple[str, str]:
    """How a field declaration stores its timestamp, as ``(verdict, spelling)``.

    ``utc`` when the declaration names ``terp.core``'s ``UtcDateTime``, called or as the
    class, through any keyword; ``foreign`` when it names a ``UtcDateTime`` that resolves
    elsewhere; ``wall-time`` for ``DateTime`` or ``TIMESTAMP`` with ``timezone=True``; and
    ``naive`` for everything else.
    """
    if value is None:
        return "naive", ""
    nodes = list(ast.walk(value))
    if any(_names_core_symbol(node, _UTC_DATETIME, bindings) for node in nodes):
        return "utc", ""
    if any(
        isinstance(node, ast.Name | ast.Attribute) and base_name(node) == _UTC_DATETIME
        for node in nodes
    ):
        return "foreign", ""
    for node in nodes:
        if (
            isinstance(node, ast.Call)
            and base_name(node.func) in _TIMESTAMP_COLUMN_TYPES
            and any(
                keyword.arg == "timezone"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            )
        ):
            return "wall-time", base_name(node.func) or "DateTime"
    return "naive", ""


def _table_mixin_names(tree: ast.Module) -> set[str | None]:
    """Names a table model inherits from, so mixin-declared columns stay in scope.

    A timestamp declared on a mixin lands on the table exactly as if it had been
    written on the model, so the mixin's fields are this rule's business too.
    Resolution is deliberately file-local: a module keeps its tables and their
    mixins together in ``models.py``, and a mixin borrowed from another module is
    already refused by the cross-module import rule. A base with no simple name
    contributes ``None``, which no class name can match — harmless, so it is not
    filtered out.
    """
    return {
        base_name(base)
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and _is_table_model_class(node)
        for base in node.bases
    }


def check_datetime_columns_are_timezone_aware(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Every timestamp column is ``terp.core``'s ``UtcDateTime``.

    A column declared without a timezone maps to a naive database type, which discards the
    zone of even a correctly-built aware value on the way in. ``DateTime(timezone=True)``
    keeps the zone on PostgreSQL but stores the wall time on SQLite, so the instant a row
    records depends on the zone it was written in (ADR 0205). ``UtcDateTime`` stores the
    instant as UTC on both, so it is the one answer: ``Field(sa_type=UtcDateTime())``,
    named or called, through ``sa_type`` or ``sa_column``. It counts only when it resolves
    to ``terp.core``, since a class of the same name from anywhere else is held to nothing.
    Columns a table inherits from a mixin declared beside it count as the table's own.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        mixins = _table_mixin_names(tree)
        bindings = _core_bindings(tree, _UTC_DATETIME)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not _is_table_model_class(node) and node.name not in mixins:
                continue
            for stmt in node.body:
                if not isinstance(stmt, ast.AnnAssign) or not _is_datetime_annotation(
                    stmt.annotation
                ):
                    continue
                verdict, spelling = _column_storage(stmt.value, bindings)
                if verdict == "utc":
                    continue
                field = stmt.target.id if isinstance(stmt.target, ast.Name) else "<field>"
                violations.append(
                    ArchViolation(
                        "datetime_columns_are_timezone_aware",
                        rel,
                        stmt.lineno,
                        _COLUMN_MESSAGES[verdict].format(
                            owner=node.name, field=field, spelling=spelling
                        ),
                    )
                )
    return violations


_NAIVE_MEANS_UTC = "NaiveMeansUtc"

_ESCAPE_MESSAGE = (
    "NaiveMeansUtc reads a timestamp with no UTC offset as UTC, so a sender in any other "
    "zone is stored off by its offset; take the timestamp with its offset (a plain datetime "
    "field or filter refuses one without it), or, for a sender known to send UTC without "
    "saying so, keep it with '# arch-allow-request-timestamps-carry-their-offset: <reason>' "
    "(budgeted by the app's escape-hatch-budget.json)"
)


def _annotations(tree: ast.Module) -> list[ast.expr]:
    """Every annotation in *tree*: of an assignment, a parameter, and a return."""
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            found.append(node.annotation)
        elif isinstance(node, ast.arg) and node.annotation is not None:
            found.append(node.annotation)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.returns is not None:
            found.append(node.returns)
    return found


def _string_annotation_nodes(tree: ast.Module, symbol: str) -> list[ast.AST]:
    """The nodes of every quoted annotation that mentions *symbol*, parsed.

    A quoted annotation (``"NaiveMeansUtc | None"``) is still evaluated by Pydantic, so it
    takes the escape as surely as an unquoted one. A string anywhere else is only text.
    """
    found: list[ast.AST] = []
    quoted = (
        node
        for annotation in _annotations(tree)
        for node in ast.walk(annotation)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )
    for node in quoted:
        if symbol in node.value:
            try:
                parsed = ast.parse(node.value, mode="eval")
            except SyntaxError:
                continue
            for inner in ast.walk(parsed):
                if isinstance(inner, ast.expr):
                    ast.copy_location(inner, node)
                found.append(inner)
    return found


def check_request_timestamps_carry_their_offset(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Taking a client's timestamp without its UTC offset is an escape, named and counted.

    A request body built on ``BaseSchema`` refuses a timestamp with no offset, and so does a
    declared filter (ADR 0206): such a value names no instant, and read as UTC it puts a
    sender in another zone off by its offset. ``NaiveMeansUtc`` from ``terp.core`` is the one
    way around both, for a sender known to send UTC without saying so. Each use of it is
    refused here, so taking it is this rule's opt-out marker, which the app's escape-hatch
    budget counts, and a reviewer sees it.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        bindings = _core_bindings(tree, _NAIVE_MEANS_UTC)
        if not bindings.names and not bindings.modules:
            continue
        rel = _rel(path, root)
        nodes = [*ast.walk(tree), *_string_annotation_nodes(tree, _NAIVE_MEANS_UTC)]
        lines = sorted(
            {
                getattr(node, "lineno", 0)
                for node in nodes
                if _names_core_symbol(node, _NAIVE_MEANS_UTC, bindings)
            }
        )
        violations.extend(
            ArchViolation("request_timestamps_carry_their_offset", rel, line, _ESCAPE_MESSAGE)
            for line in lines
        )
    return violations


__all__ = [
    "check_datetime_columns_are_timezone_aware",
    "check_no_naive_datetime",
    "check_request_timestamps_carry_their_offset",
]
