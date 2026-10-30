"""How ``no_destructive_migrations`` reads a statement a revision runs as written.

``op.execute(...)`` and ``exec_driver_sql(...)`` hand the database a statement, and a
destructive step spelled that way is the same risk as its op-form call. The rule reads
every statement whose text is in the source, a literal, an f-string or a ``+`` of
strings, and classifies it by the same five kinds as the calls. Private to
:mod:`terp.arch.rules.destructive_migrations`, which owns the kinds' messages.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator

#: The five kinds of destructive step, named as the rule and its readers name them.
_DROP = "drop"
_RENAME = "rename"
_TYPE = "type"
_NOT_NULL = "not-null"
_CONSTRAINT = "constraint"

# Destructive SQL verbs a revision can smuggle through ``op.execute(...)``. Matched
# against string literals only (a statically reviewable statement); DROP TRIGGER /
# DROP FUNCTION / DROP INDEX are excluded — they destroy no row data — and so is
# ``DROP NOT NULL``, the relaxing direction ``alter_column(nullable=True)`` spells.
_DESTRUCTIVE_SQL_RE = re.compile(
    r"\b(DROP\s+TABLE|DROP\s+COLUMN|TRUNCATE(\s+TABLE)?|DELETE\s+FROM"
    r"|ALTER\s+TABLE\s+.+\bDROP\b(?!\s+NOT\s+NULL\b))\b",
    re.IGNORECASE | re.DOTALL,
)

# The rest are read one statement at a time, so a clause of one statement can never
# pair with the ``ALTER TABLE`` of another. A constraint rename is left alone: no
# query names a constraint, so the running release cannot be reading the old name.
_RENAME_SQL_RE = re.compile(
    r"\bALTER\s+TABLE\b.*?\bRENAME\b(?!\s+CONSTRAINT\b)|\bRENAME\s+TABLE\b",
    re.IGNORECASE | re.DOTALL,
)
_TYPE_SQL_RE = re.compile(
    r"\bALTER\s+TABLE\b.*?\bALTER\s+(?:COLUMN\s+)?(?!COLUMN\b)\S+\s+(?:SET\s+DATA\s+)?TYPE\b",
    re.IGNORECASE | re.DOTALL,
)
_NOT_NULL_SQL_RE = re.compile(
    r"\bALTER\s+TABLE\b.*?\bSET\s+NOT\s+NULL\b", re.IGNORECASE | re.DOTALL
)
_ADD_CONSTRAINT_SQL_RE = re.compile(
    r"\bALTER\s+TABLE\b.*?\bADD\s+(?:CONSTRAINT\s+(?:\"[^\"]*\"|\S+)\s+)?"
    r"(?P<kind>UNIQUE|PRIMARY\s+KEY|CHECK|FOREIGN\s+KEY|EXCLUDE)\b",
    re.IGNORECASE | re.DOTALL,
)
_ENFORCE_SQL_RE = re.compile(
    r"\bCREATE\s+UNIQUE\s+INDEX\b|\bVALIDATE\s+CONSTRAINT\b", re.IGNORECASE
)
#: ``NOT VALID`` skips the existing rows, which is the expand half of a check or a
#: foreign key; the ``VALIDATE CONSTRAINT`` that follows it is the contract half.
_NOT_VALID_RE = re.compile(r"\bNOT\s+VALID\b", re.IGNORECASE)
_NOT_VALID_KINDS = ("CHECK", "FOREIGN")

#: Calls whose arguments are a statement the database runs as written.
_EXECUTING = frozenset({"execute", "exec_driver_sql"})

_PLACEHOLDER = " ? "


def _static_text(node: ast.expr) -> str | None:
    """The statement *node* spells, with each interpolated part read as a placeholder.

    A literal, an f-string and a ``+`` of strings are each one statement, so
    ``f"ALTER TABLE {name} RENAME TO entry"`` is read whole rather than as two halves
    that each look harmless. ``None`` when *node* holds no static text at all.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else _PLACEHOLDER
            for part in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _static_text(node.left), _static_text(node.right)
        if left is None and right is None:
            return None
        return (left if left is not None else _PLACEHOLDER) + (
            right if right is not None else _PLACEHOLDER
        )
    return None


def _sql_texts(node: ast.AST) -> Iterator[str]:
    """Yield every statically known statement under *node* (``sa.text(...)`` included)."""
    text = _static_text(node) if isinstance(node, ast.expr) else None
    if text is not None:
        yield text
        return
    for child in ast.iter_child_nodes(node):
        yield from _sql_texts(child)


def _classify_statement(statement: str) -> str | None:
    """The kind of destructive step one SQL statement takes, if any."""
    if _RENAME_SQL_RE.search(statement):
        return _RENAME
    if _TYPE_SQL_RE.search(statement):
        return _TYPE
    if _NOT_NULL_SQL_RE.search(statement):
        return _NOT_NULL
    added = _ADD_CONSTRAINT_SQL_RE.search(statement)
    if added and not (
        added.group("kind").upper().startswith(_NOT_VALID_KINDS)
        and _NOT_VALID_RE.search(statement)
    ):
        return _CONSTRAINT
    if _ENFORCE_SQL_RE.search(statement):
        return _CONSTRAINT
    return None


def _classify_sql(call: ast.Call) -> tuple[str, str] | None:
    """The kind of destructive step the statement an ``execute(...)`` runs takes.

    Returned with the text it was read from: the first statement in the call's
    arguments that is destructive, whole, before it is split at ``;``.
    """
    for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
        for text in _sql_texts(argument):
            if _DESTRUCTIVE_SQL_RE.search(text):
                return _DROP, text
            for statement in text.split(";"):
                kind = _classify_statement(statement)
                if kind is not None:
                    return kind, text
    return None
