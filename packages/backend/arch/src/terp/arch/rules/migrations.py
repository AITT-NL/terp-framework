"""Migration safety rules: destructive DDL must be visibly justified.

Terp migrations are the only supported schema-change path, so destructive DDL
is refused unless each destructive operation carries the standard governed
opt-out (``# arch-allow-no-destructive-migrations: <reason>`` on or immediately
above the operation, counted by the escape-hatch budget) — the same one-marker
contract as every other rule, never a bespoke file-wide waiver.
"""

from __future__ import annotations

import ast
import io
import pathlib
import re
import tokenize
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


def _downgrade_is_stub(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when *function*'s body is empty after its docstring, a lone ``pass``, or ``...``."""
    body = list(function.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if not body:
        return True
    if len(body) == 1:
        stmt = body[0]
        if isinstance(stmt, ast.Pass):
            return True
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is ...
        ):
            return True
    return False


def _has_comment_between(source: str, start: int, end: int) -> bool:
    """True when a real ``#`` comment token appears on lines ``start..end`` of *source*."""
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT and start <= token.start[0] <= end:
                return True
    except (tokenize.TokenError, IndentationError):  # pragma: no cover - defensive
        pass
    return False


def check_alembic_downgrades_not_empty(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A migration's ``downgrade()`` must reverse the change, not be an empty stub.

    An empty ``downgrade()`` (a lone ``pass`` / ``...``, or only a docstring) makes a
    revision irreversible: a rollback silently leaves the schema mismatched instead of
    restoring the previous state. Implement the reverse operations, or — for a
    deliberately irreversible step (a data backfill, a dropped legacy table) — leave a
    ``#`` comment inside the function explaining why the no-op is intentional.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in _migration_files(root):
        rel = _rel(path, root)
        source = path.read_text(encoding="utf-8")
        tree = parse(path)
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if function.name != "downgrade":
                continue
            end = function.end_lineno or function.lineno
            if _downgrade_is_stub(function) and not _has_comment_between(
                source, function.lineno, end
            ):
                violations.append(
                    ArchViolation(
                        "alembic_downgrades_not_empty",
                        rel,
                        function.lineno,
                        "downgrade() is an empty stub; implement the reverse migration so the "
                        "revision is reversible, or add a comment explaining the intentional no-op",
                    )
                )
    return violations
