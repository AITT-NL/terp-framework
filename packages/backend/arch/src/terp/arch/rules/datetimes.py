"""Time-handling rules: timestamps are timezone-aware in memory *and* in storage.

A naive timestamp — one without a timezone — silently assumes the process's local
zone and cannot be compared or stored correctly across zones. Two rules close that
hole at both ends. ``no_naive_datetime`` refuses the naive *constructors* (the
deprecated ``datetime.utcnow()`` and a bare ``datetime.now()``), so every value the
app builds carries an explicit zone. ``datetime_columns_are_timezone_aware`` refuses
a naive *column*, because a timestamp column declared without a timezone discards
the zone of even a correctly-built aware value on the way into the database.
"""

from __future__ import annotations

import ast
import pathlib

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


def _is_datetime_annotation(annotation: ast.expr) -> bool:
    """True for ``datetime`` and ``datetime | None``, however the name is qualified."""
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _is_datetime_annotation(annotation.left) or _is_datetime_annotation(annotation.right)
    return base_name(annotation) == "datetime"


# Column types that carry a ``timezone`` switch. Either spelling pins the stored
# zone when it is passed ``timezone=True``.
_TIMESTAMP_COLUMN_TYPES = frozenset({"DateTime", "TIMESTAMP"})


def _declares_timezone_aware_storage(value: ast.expr | None) -> bool:
    """True when a field declaration pins a ``timezone=True`` column type.

    Matches both spellings that reach the column — ``Field(sa_type=DateTime(timezone=True))``
    and ``Field(sa_column=Column(DateTime(timezone=True), ...))`` — by looking for the
    typed call anywhere in the declaration, so the rule does not depend on which
    keyword carried it.
    """
    if value is None:
        return False
    return any(
        isinstance(node, ast.Call)
        and base_name(node.func) in _TIMESTAMP_COLUMN_TYPES
        and any(
            keyword.arg == "timezone"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in node.keywords
        )
        for node in ast.walk(value)
    )


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
    """Every timestamp column stores its timezone.

    A timestamp column declared without an explicit timezone maps to a naive
    database type (``TIMESTAMP WITHOUT TIME ZONE``), which discards the zone of even
    a correctly-built aware value on the way in — so the stored moment is ambiguous
    and ordering or comparison across zones is silently wrong. This is the storage
    half of the hole whose in-memory half ``no_naive_datetime`` closes: capturing an
    aware value is not enough if the column cannot keep it. Declare the column type
    explicitly (``Field(sa_type=DateTime(timezone=True))``). Columns a table inherits
    from a mixin declared beside it count as the table's own.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        mixins = _table_mixin_names(tree)
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
                if _declares_timezone_aware_storage(stmt.value):
                    continue
                field = stmt.target.id if isinstance(stmt.target, ast.Name) else "<field>"
                violations.append(
                    ArchViolation(
                        "datetime_columns_are_timezone_aware",
                        rel,
                        stmt.lineno,
                        f"{node.name}.{field}: timestamp column declares no timezone, so the "
                        "database stores an ambiguous local-zone value; declare the column "
                        "type explicitly (Field(sa_type=DateTime(timezone=True)))",
                    )
                )
    return violations


__all__ = ["check_datetime_columns_are_timezone_aware", "check_no_naive_datetime"]
