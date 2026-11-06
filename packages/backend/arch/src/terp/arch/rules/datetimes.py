"""Time-handling rules: an instant is an instant in memory, in storage and at the door.

A naive timestamp — one without a timezone — silently assumes some zone and cannot be
compared or stored correctly across zones. Three rules close that hole where it opens.
``no_naive_datetime`` refuses the naive *constructors* (the deprecated
``datetime.utcnow()`` and a bare ``datetime.now()``), so every value the app builds carries
an explicit zone. ``datetime_columns_are_timezone_aware`` holds every timestamp *column* to
``UtcDateTime`` from ``terp.core``, which stores the instant as UTC on every dialect.
Beside them, ``request_timestamps_carry_their_offset`` (:mod:`terp.arch.rules.request_timestamps`)
refuses each use of ``NaiveMeansUtc``, the framework's way around the refusal of timestamp text
that carries no UTC offset (ADR 0206).
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator
from dataclasses import dataclass, field

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


#: The modules whose ``UtcDateTime`` is the framework's: the type's own, and the package.
_CORE_MODULES = frozenset({"terp.core", "terp.core.base_models"})

_UTC_DATETIME = "UtcDateTime"


def _dotted(node: ast.expr) -> str | None:
    """``a.b.c`` for a chain of names and attributes, else ``None``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return None if head is None else f"{head}.{node.attr}"
    return None


@dataclass
class _Scope:
    """What a file's module scope binds at one point, for the names the column rule reads.

    ``names`` holds, per local name, whether it is ``terp.core``'s ``UtcDateTime``, and
    ``modules`` whether a dotted local name is a ``terp.core`` module. ``terp`` itself, bound by
    ``import terp`` or ``import terp.anything``, reaches ``terp.core`` as an attribute.
    """

    names: dict[str, bool] = field(default_factory=dict)
    modules: dict[str, bool] = field(default_factory=dict)

    def is_core_module(self, node: ast.expr) -> bool:
        dotted = _dotted(node)
        if dotted is None:
            return False
        if dotted in self.modules:
            return self.modules[dotted]
        return dotted in _CORE_MODULES and self.modules.get("terp", False)

    def is_utc_datetime(self, node: ast.expr) -> bool:
        """True when *node*, a type or a call of one, is ``terp.core``'s ``UtcDateTime``."""
        target = node.func if isinstance(node, ast.Call) else node
        if isinstance(target, ast.Name):
            return self.names.get(target.id, False)
        if isinstance(target, ast.Attribute) and target.attr == _UTC_DATETIME:
            return self.is_core_module(target.value)
        return False


def _bound_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Tuple | ast.List):
        return [name for element in target.elts for name in _bound_names(element)]
    return []


def _bind(scope: _Scope, stmt: ast.stmt) -> None:
    """Apply what *stmt*, a statement of the module's own scope, binds."""
    if isinstance(stmt, ast.ImportFrom):
        for alias in stmt.names:
            local = alias.asname or alias.name
            absolute = stmt.level == 0 and stmt.module is not None
            scope.names[local] = (
                absolute and stmt.module in _CORE_MODULES and alias.name == _UTC_DATETIME
            )
            scope.modules[local] = absolute and f"{stmt.module}.{alias.name}" in _CORE_MODULES
    elif isinstance(stmt, ast.Import):
        for alias in stmt.names:
            if alias.asname is not None:
                scope.modules[alias.asname] = alias.name in _CORE_MODULES
                scope.names[alias.asname] = False
            else:
                root = alias.name.split(".")[0]
                scope.modules[root] = root == "terp"
                scope.names[root] = False
    elif isinstance(stmt, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
        scope.names[stmt.name] = False
        scope.modules[stmt.name] = False
    elif isinstance(stmt, ast.Assign | ast.AnnAssign | ast.AugAssign):
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        value = None if isinstance(stmt, ast.AugAssign) else stmt.value
        for target in targets:
            for name in _bound_names(target):
                scope.names[name] = value is not None and scope.is_utc_datetime(value)
                scope.modules[name] = value is not None and scope.is_core_module(value)


def _module_statements(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """The module scope's statements in source order, through blocks that do not open one."""
    for stmt in body:
        yield stmt
        if isinstance(stmt, ast.If | ast.For | ast.AsyncFor | ast.While):
            yield from _module_statements(stmt.body)
            yield from _module_statements(stmt.orelse)
        elif isinstance(stmt, ast.With | ast.AsyncWith):
            yield from _module_statements(stmt.body)
        elif isinstance(stmt, ast.Try | ast.TryStar):
            yield from _module_statements(stmt.body)
            for handler in stmt.handlers:
                yield from _module_statements(handler.body)
            yield from _module_statements(stmt.orelse)
            yield from _module_statements(stmt.finalbody)


def _is_datetime_annotation(annotation: ast.expr) -> bool:
    """True for a ``datetime`` however it is wrapped: ``| None``, ``Optional``, ``Union``,
    ``Annotated``, or quoted."""
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _is_datetime_annotation(annotation.left) or _is_datetime_annotation(annotation.right)
    if isinstance(annotation, ast.Subscript) and base_name(annotation.value) in {
        "Optional",
        "Union",
        "Annotated",
    }:
        inner = annotation.slice
        elements = list(inner.elts) if isinstance(inner, ast.Tuple) else [inner]
        if base_name(annotation.value) == "Annotated":
            elements = elements[:1]
        return any(_is_datetime_annotation(element) for element in elements)
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            quoted = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return False
        return _is_datetime_annotation(quoted)
    return base_name(annotation) == "datetime"


#: Column types with a ``timezone`` switch. With ``timezone=True`` they keep the zone on
#: PostgreSQL and store the wall time on SQLite (ADR 0205), so they are no longer the answer.
_TIMESTAMP_COLUMN_TYPES = frozenset({"DateTime", "TIMESTAMP"})

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
        "{owner}.{field}: this UtcDateTime is not terp.core's (the file defines it, imports "
        "it from elsewhere, or reaches it through something else), so nothing holds it to "
        "storing the instant as UTC; import UtcDateTime from terp.core"
    ),
    "unreadable": (
        "{owner}.{field}: the column is built where this rule cannot read its type; declare "
        "it in place, Field(sa_type=UtcDateTime()) or sa_column=Column(UtcDateTime(), ...), "
        "with UtcDateTime from terp.core"
    ),
}


def _declared_column_types(
    value: ast.expr | None, column_names: set[str]
) -> list[ast.expr] | None:
    """The column types a field declaration names, or ``None`` when one cannot be read.

    Only the places a type reaches the column count: ``sa_type=``, and the type of
    ``sa_column=Column(...)`` (``type_=``, or its positional arguments, the column's name
    aside). A type named anywhere else in the call does not reach the column.
    """
    if not isinstance(value, ast.Call):
        return []
    found: list[ast.expr] = []
    for keyword in value.keywords:
        if keyword.arg == "sa_type":
            found.append(keyword.value)
        elif keyword.arg == "sa_column":
            column = keyword.value
            if not isinstance(column, ast.Call) or base_name(column.func) not in column_names:
                return None
            typed = [k.value for k in column.keywords if k.arg == "type_"]
            positional = [
                argument
                for argument in column.args
                if not (isinstance(argument, ast.Constant) and isinstance(argument.value, str))
            ]
            found.extend(typed or positional)
    return found


def _annotated_fields(annotation: ast.expr) -> list[ast.expr]:
    """The ``Field(...)`` calls an ``Annotated`` annotation carries, however it is wrapped."""
    found: list[ast.expr] = []
    for node in ast.walk(annotation):
        if isinstance(node, ast.Subscript) and base_name(node.value) == "Annotated":
            inner = node.slice
            elements = list(inner.elts) if isinstance(inner, ast.Tuple) else [inner]
            found.extend(
                element
                for element in elements[1:]
                if isinstance(element, ast.Call) and base_name(element.func) == "Field"
            )
    return found


def _column_names(tree: ast.Module) -> set[str]:
    """The names this file calls ``Column`` by: its own, and any import alias of it."""
    names = {"Column"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname for alias in node.names if alias.name == "Column" and alias.asname)
    return names


def _type_verdict(node: ast.expr, scope: _Scope) -> tuple[str, str]:
    if scope.is_utc_datetime(node):
        return "utc", ""
    target = node.func if isinstance(node, ast.Call) else node
    if base_name(target) == _UTC_DATETIME:
        return "foreign", ""
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


def _column_storage(
    declarations: list[ast.expr | None], scope: _Scope, column_names: set[str]
) -> tuple[str, str]:
    """How a field's declarations store its timestamp: ``utc`` only for terp.core's type.

    A type that is not terp.core's, or one that stores the wall time, decides it whatever else
    is named. Otherwise terp.core's type decides it, so the name a column is given beside it
    does not; with neither, the column is naive.
    """
    types: list[ast.expr] = []
    for declaration in declarations:
        declared = _declared_column_types(declaration, column_names)
        if declared is None:
            return "unreadable", ""
        types.extend(declared)
    verdicts = [_type_verdict(node, scope) for node in types]
    for kind in ("foreign", "wall-time", "utc"):
        for verdict in verdicts:
            if verdict[0] == kind:
                return verdict
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


def _column_violations(
    cls: ast.ClassDef, scope: _Scope, rel: str, column_names: set[str]
) -> list[ArchViolation]:
    violations: list[ArchViolation] = []
    for stmt in cls.body:
        if not isinstance(stmt, ast.AnnAssign) or not _is_datetime_annotation(stmt.annotation):
            continue
        declarations = [stmt.value, *_annotated_fields(stmt.annotation)]
        verdict, spelling = _column_storage(declarations, scope, column_names)
        if verdict == "utc":
            continue
        name = stmt.target.id if isinstance(stmt.target, ast.Name) else "<field>"
        violations.append(
            ArchViolation(
                "datetime_columns_are_timezone_aware",
                rel,
                stmt.lineno,
                _COLUMN_MESSAGES[verdict].format(owner=cls.name, field=name, spelling=spelling),
            )
        )
    return violations


def check_datetime_columns_are_timezone_aware(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Every timestamp column is ``terp.core``'s ``UtcDateTime``.

    A column declared without a timezone maps to a naive database type, which discards the
    zone of even a correctly-built aware value on the way in. ``DateTime(timezone=True)``
    keeps the zone on PostgreSQL but stores the wall time on SQLite, so the instant a row
    records depends on the zone it was written in (ADR 0205). ``UtcDateTime`` stores the
    instant as UTC on both, so it is the one answer: ``Field(sa_type=UtcDateTime())``, named or
    called, through ``sa_type`` or ``sa_column=Column(...)``'s type. It counts only when the
    name resolves to ``terp.core`` where the class is defined, reading the module's imports,
    definitions and assignments in source order, since a class of the same name from
    anywhere else is held to nothing. Columns a table inherits from a mixin declared beside it
    count as the table's own.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        mixins = _table_mixin_names(tree)
        column_names = _column_names(tree)
        scope = _Scope()
        checked: set[int] = set()
        for stmt in _module_statements(tree.body):
            if isinstance(stmt, ast.ClassDef) and (
                _is_table_model_class(stmt) or stmt.name in mixins
            ):
                checked.add(id(stmt))
                violations.extend(_column_violations(stmt, scope, rel, column_names))
            _bind(scope, stmt)
        # A class defined inside a function is read when the function runs: after the module.
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ClassDef)
                and id(node) not in checked
                and (_is_table_model_class(node) or node.name in mixins)
            ):
                violations.extend(_column_violations(node, scope, rel, column_names))
    return violations


__all__ = ["check_datetime_columns_are_timezone_aware", "check_no_naive_datetime"]
