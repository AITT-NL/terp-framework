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


def _module_constant(tree: ast.Module, name: str) -> tuple[object, int] | None:
    """The value and line of a module-level ``name = <literal>`` assignment, if any."""
    for statement in tree.body:
        targets: list[ast.expr] = []
        if isinstance(statement, ast.Assign):
            targets = list(statement.targets)
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        if not any(
            isinstance(target, ast.Name) and target.id == name for target in targets
        ):
            continue
        value = statement.value
        if value is None:  # pragma: no cover - a bare annotation carries no revision
            continue
        try:
            return ast.literal_eval(value), statement.lineno
        except ValueError:  # pragma: no cover - a computed revision id is not a literal
            return None
    return None


def _parent_revisions(down_revision: object) -> tuple[str, ...]:
    """The parents *down_revision* names — one id, a merge's tuple of ids, or none."""
    if isinstance(down_revision, str):
        return (down_revision,)
    if isinstance(down_revision, tuple | list):
        return tuple(item for item in down_revision if isinstance(item, str))
    return ()


def check_migration_history_is_intact(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Each migration history must be one unbroken chain from a single first revision.

    A revision whose parent is missing, or a second revision that claims to be the
    start of the history, means an already-authored migration was deleted or replaced.
    Any database that applied the old revision can no longer be upgraded — the schema
    in front of it was built by a history that no longer exists — and no drift check
    can see it, because a database rebuilt from the rewritten history is perfectly
    consistent. Add a new revision on top of the existing chain instead of editing a
    revision that has already been applied anywhere.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    histories: dict[pathlib.Path, list[tuple[pathlib.Path, ast.Module]]] = {}
    for path in _migration_files(root):
        histories.setdefault(path.parent, []).append((path, parse(path)))

    for revisions in histories.values():
        known: set[str] = set()
        for _, tree in revisions:
            found = _module_constant(tree, "revision")
            if found and isinstance(found[0], str):
                known.add(found[0])
        roots: list[tuple[pathlib.Path, int, str]] = []
        entries: list[tuple[pathlib.Path, int, str, tuple[str, ...]]] = []
        broken_revisions: set[str] = set()
        for path, tree in revisions:
            rel = _rel(path, root)
            revision_found = _module_constant(tree, "revision")
            found = _module_constant(tree, "down_revision")
            if (
                found is None
                or revision_found is None
                or not isinstance(revision_found[0], str)
            ):
                continue
            down, line = found
            parents = _parent_revisions(down)
            revision = revision_found[0]
            entries.append((path, line, revision, parents))
            if not parents:
                roots.append((path, line, revision))
                continue
            for parent in parents:
                if parent not in known:
                    broken_revisions.add(revision)
                    violations.append(
                        ArchViolation(
                            "migration_history_is_intact",
                            rel,
                            line,
                            f"down_revision {parent!r} is not a revision in this "
                            "history; the migration it builds on was deleted or "
                            "renamed, which strands every database that applied it",
                        )
                    )
        if len(roots) > 1:
            for path, line, _ in roots:
                violations.append(
                    ArchViolation(
                        "migration_history_is_intact",
                        _rel(path, root),
                        line,
                        "this history has more than one first revision; a rewritten "
                        "or duplicated baseline leaves databases on the old chain "
                        "unupgradable",
                    )
                )
        elif entries and not roots:
            path, line, _, _ = entries[0]
            violations.append(
                ArchViolation(
                    "migration_history_is_intact",
                    _rel(path, root),
                    line,
                    "this history has no first revision; its parent graph contains "
                    "a cycle, so no database can start at a valid baseline",
                )
            )
        elif len(roots) == 1:
            children: dict[str, set[str]] = {revision: set() for revision in known}
            for _, _, revision, parents in entries:
                for parent in parents:
                    if parent in known:
                        children.setdefault(parent, set()).add(revision)
            reachable: set[str] = set()
            pending = [roots[0][2]]
            while pending:
                revision = pending.pop()
                if revision in reachable:
                    continue
                reachable.add(revision)
                pending.extend(children.get(revision, ()))
            for path, line, revision, _ in entries:
                if revision not in reachable and revision not in broken_revisions:
                    violations.append(
                        ArchViolation(
                            "migration_history_is_intact",
                            _rel(path, root),
                            line,
                            "this revision is not connected to the history's first "
                            "revision; a disconnected cycle or rewritten chain leaves "
                            "databases unupgradable",
                        )
                    )
    return violations


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


def _owning_package(path: pathlib.Path) -> pathlib.Path | None:
    """The package directory that owns *path* — the nearest module/capability root.

    Ownership follows the import path, not the presence of a history: a package that has
    just gained a model has no ``migrations/`` directory yet, and that is exactly the
    state a move leaves behind.
    """
    for parent in path.parents:
        if parent.parent.name in {"modules", "capabilities"}:
            return parent
    return None


def _declared_tablenames(root: pathlib.Path) -> Iterator[tuple[str, pathlib.Path, int]]:
    """Yield ``(table, file, line)`` for each ``__tablename__`` literal under *root*.

    Revision files are skipped (they mention table names, they do not declare models);
    everything else counts, so a package that splits its models across a ``models/``
    sub-package is read the same way as one with a single ``models.py``.
    """
    for path in sorted(root.rglob("*.py")):
        if "migrations" in path.parts:
            continue
        try:
            tree = parse(path)
        except (OSError, SyntaxError):  # pragma: no cover - unreadable source
            continue
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            if not any(
                isinstance(t, ast.Name) and t.id == "__tablename__" for t in targets
            ):
                continue
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                yield value.value, path, node.lineno


def _created_tables(path: pathlib.Path) -> set[str]:
    """Table names the revision at *path* creates inside ``upgrade()``."""
    created: set[str] = set()
    try:
        tree = parse(path)
    except (OSError, SyntaxError):  # pragma: no cover - unreadable source
        return created
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if function.name != "upgrade":
            continue
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_table"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                created.add(node.args[0].value)
    return created


def check_table_ownership_is_not_split(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A table must be created by the package whose models declare it.

    Moving a model to another package splits the two and emits no DDL at all: the losing
    package no longer owns the table so its scoped autogenerate cannot propose a drop, and
    the gaining package diffs against a database where the table already exists so it
    proposes no create. Every existing database keeps upgrading and the build stays green.
    The next ordinary schema change to that model is then authored into the gaining
    package's INDEPENDENT history, which - with no foreign key between the two packages -
    a fresh install may run before the history that creates the table. Only fresh installs
    break, months later, blamed on an innocent add_column. Move the table with
    expand/contract instead (see ADR 0090).
    """
    root = pathlib.Path(app_root)
    creator_of: dict[str, pathlib.Path] = {}
    for path in _migration_files(root):
        owner = _owning_package(path)
        if owner is None:
            continue
        for table in _created_tables(path):
            creator_of.setdefault(table, owner)

    violations: list[ArchViolation] = []
    for table, path, line in _declared_tablenames(root):
        creator = creator_of.get(table)
        owner = _owning_package(path)
        if creator is None or owner is None or creator == owner:
            continue
        violations.append(
            ArchViolation(
                "table_ownership_is_not_split",
                _rel(path, root),
                line,
                f"table {table!r} is declared here but created by "
                f"{_rel(creator, root)}'s migration history; each history is "
                "independent and ordered only by foreign keys, so a fresh install "
                "may run this package's next migration before the table exists. "
                "Move the model back, or move the table with expand/contract (new "
                "__tablename__, copy the rows, retire the old table later)",
            )
        )
    return violations
