"""Migration safety rules: destructive DDL must be visibly justified.

Terp migrations are the only supported schema-change path, so destructive DDL
is refused unless each destructive operation carries the standard governed
opt-out (``# arch-allow-no-destructive-migrations: <reason>`` on or immediately
above the operation, counted by the escape-hatch budget) — the same one-marker
contract as every other rule, never a bespoke file-wide waiver.
"""

from __future__ import annotations

import ast
import pathlib
import re
from collections.abc import Iterator

from terp.arch._ast import parse
from terp.arch.rules._support import ArchViolation, _rel

# Destructive SQL verbs a revision can smuggle through ``op.execute(...)``. Matched
# against string literals only (a statically reviewable statement); DROP TRIGGER /
# DROP FUNCTION / DROP INDEX are excluded — they destroy no row data.
_DESTRUCTIVE_SQL_RE = re.compile(
    r"\b(DROP\s+TABLE|DROP\s+COLUMN|TRUNCATE(\s+TABLE)?|DELETE\s+FROM"
    r"|ALTER\s+TABLE\s+.+\bDROP\b)\b",
    re.IGNORECASE | re.DOTALL,
)


def _migration_files(root: pathlib.Path) -> Iterator[pathlib.Path]:
    """Yield app/capability Alembic revision files under ``migrations/versions``."""
    for versions_dir in sorted(root.rglob("migrations/versions")):
        if not versions_dir.is_dir():  # pragma: no cover - rglob can match an unexpected file
            continue
        for path in sorted(versions_dir.glob("*.py")):
            if path.is_file() and not path.name.startswith("_"):
                yield path


def _literal_sql_fragments(node: ast.expr) -> Iterator[str]:
    """Yield every statically known string fragment of *node* (literals, f-string parts)."""
    for inner in ast.walk(node):
        if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
            yield inner.value


def _is_destructive_op_call(node: ast.Call) -> bool:
    """True for the Alembic destructive operations governed by this rule.

    Matched on the attribute name alone (``drop_table`` / ``drop_column`` /
    type-changing ``alter_column``), whatever the receiver — ``op``, a
    ``batch_op`` block, or an alias — so renaming the handle never unprotects
    the rule. ``.execute(...)`` whose statement literally contains a
    destructive verb (``DROP TABLE`` / ``DROP COLUMN`` / ``TRUNCATE`` /
    ``DELETE FROM`` / ``ALTER TABLE ... DROP``) is destructive too.
    """
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr in {"drop_table", "drop_column"}:
        return True
    if node.func.attr == "alter_column":
        return any(keyword.arg == "type_" for keyword in node.keywords)
    return node.func.attr == "execute" and any(
        _DESTRUCTIVE_SQL_RE.search(fragment)
        for arg in node.args
        for fragment in _literal_sql_fragments(arg)
    )


def check_no_destructive_migrations(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Destructive migration operations require a reason-bearing marker.

    ``drop_table(...)``, ``drop_column(...)``, type-changing
    ``alter_column(..., type_=...)`` (on ``op``, a batch block, or any alias), and
    ``execute(...)`` of a statement containing ``DROP TABLE`` / ``DROP COLUMN`` /
    ``TRUNCATE`` / ``DELETE FROM`` / ``ALTER TABLE ... DROP`` in ``upgrade()`` can
    destroy data or make rollback unsafe. Each such operation is a violation; a
    reviewed one is justified through the standard governed escape hatch — a
    ``# arch-allow-no-destructive-migrations: <reason>`` marker on (or immediately
    above) the operation, counted against the app's escape-hatch budget — so
    every accepted risk is explicit, reviewable, greppable, and ratcheted.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in _migration_files(root):
        rel = _rel(path, root)
        tree = parse(path)
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if function.name != "upgrade":
                continue
            for node in ast.walk(function):
                if not (isinstance(node, ast.Call) and _is_destructive_op_call(node)):
                    continue
                violations.append(
                    ArchViolation(
                        "no_destructive_migrations",
                        rel,
                        node.lineno,
                        "migration performs destructive DDL; avoid drops/type changes or add "
                        "'# arch-allow-no-destructive-migrations: <reason>' after review "
                        "(budgeted by the escape-hatch ratchet)",
                    )
                )
    return violations
