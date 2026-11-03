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
    r"\b(DROP\s+TABLE|DROP\s+COLUMN|DROP\s+SCHEMA|TRUNCATE(\s+TABLE)?|DELETE\s+FROM"
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

#: What a ``;`` inside does not end a statement in: a quoted string, a quoted identifier
#: (in double quotes or backticks), a dollar-quoted body and a comment. Each is matched
#: whole, so the only ``;`` left for the last alternative is one between statements. An
#: unterminated span runs to the end of the text.
_SQL_SPANS = re.compile(
    r"'(?:[^']|'')*'?"
    r'|"(?:[^"]|"")*"?'
    r"|`[^`]*`?"
    r"|--[^\n]*"
    r"|/\*.*?(?:\*/|\Z)"
    r"|(?P<tag>\$(?:[A-Za-z_][A-Za-z_0-9]*)?\$).*?(?:(?P=tag)|\Z)"
    r"|;",
    re.DOTALL,
)

#: The keywords an executing call takes its statement under, when not first.
_STATEMENT_KEYWORDS = frozenset({"sqltext", "statement"})
#: The methods of ``text(...)`` whose result is still that statement.
_TEXT_METHODS = frozenset({"bindparams", "columns", "execution_options"})

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


def _statements(text: str) -> list[str]:
    """*text* split into statements at each ``;`` that ends one (see ``_SQL_SPANS``)."""
    statements: list[str] = []
    start = 0
    for span in _SQL_SPANS.finditer(text):
        if span.group() == ";":
            statements.append(text[start : span.start()])
            start = span.end()
    statements.append(text[start:])
    return statements


def _classify_statement(statement: str) -> str | None:
    """The kind of destructive step one SQL statement takes, if any."""
    if _DESTRUCTIVE_SQL_RE.search(statement):
        return _DROP
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


def _classify_sql(call: ast.Call) -> list[tuple[str, str]]:
    """Each destructive statement an ``execute(...)`` runs, as its kind and its text, in order.

    Every statement is its own step, so a text that drops one table and renames another
    is a drop and a rename, never just the first of them.
    """
    found: list[tuple[str, str]] = []
    for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
        for text in _sql_texts(argument):
            for statement in _statements(text):
                kind = _classify_statement(statement)
                if kind is not None:
                    found.append((kind, statement))
    return found


def _statement_is_read(call: ast.Call) -> bool:
    """Whether the statement an executing *call* runs has its text in the source.

    The statement is the call's first argument, or its ``sqltext=`` / ``statement=``. It
    is read when it is a string literal, an f-string or a ``+`` of strings, or ``text()``
    of one, ``.bindparams(...)``, ``.columns(...)`` and ``.execution_options(...)`` on it
    included.
    """
    node = call.args[0] if call.args else next(
        (k.value for k in call.keywords if k.arg in _STATEMENT_KEYWORDS), None
    )
    if node is None:
        return False
    if _static_text(node) is not None:
        return True
    while (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _TEXT_METHODS
    ):
        node = node.func.value
    if not isinstance(node, ast.Call):
        return False
    callee = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
    text = node.args[0] if node.args else next(
        (k.value for k in node.keywords if k.arg == "text"), None
    )
    return callee == "text" and text is not None and _static_text(text) is not None
