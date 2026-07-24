"""Time-handling rule: timestamps must be timezone-aware, never naive.

A naive timestamp — one produced without a timezone — silently assumes the
process's local zone and cannot be compared or stored correctly across zones.
The two classic naive constructors are the deprecated ``datetime.utcnow()`` and
a bare ``datetime.now()`` (no ``tz``). This rule refuses both so every timestamp
carries an explicit zone (``datetime.now(UTC)``).
"""

from __future__ import annotations

import ast
import pathlib

from terp.arch._ast import base_name, iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _rel


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


__all__ = ["check_no_naive_datetime"]
