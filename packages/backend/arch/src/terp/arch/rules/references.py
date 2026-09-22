"""Reference rules: a stored pointer declares what a delete of its target does.

The build-time half of the reference control (ADR 0133). Its runtime companion is
``terp.core.assert_references_declare_delete_behaviour``, which audits live
metadata; this reads the *source*, so it also sees the case metadata cannot tell
apart -- a foreign key that emits no ``ON DELETE`` clause because nobody chose
one looks exactly like a foreign key that emits none because ``NO ACTION`` was
chosen deliberately.
"""

from __future__ import annotations

import ast
import pathlib

from terp.arch._ast import base_name, iter_python_files, parse
from terp.arch.rules._support import (
    ArchViolation,
    _is_table_model_class,
    _module_under,
    _rel,
    _soft_delete_capable_class_names,
)

# Referential actions that cannot fire against a soft-deletable target: that
# target's delete is a stamp, so no DELETE statement ever reaches the constraint.
# RESTRICT and NO ACTION are absent because they only ever described the hard-delete
# path; these three each promise to change other rows, and none of them ever will.
_UNREACHABLE_AGAINST_SOFT_DELETE = frozenset({"CASCADE", "SET NULL", "SET DEFAULT"})

# The soft-delete trait's column, as ``terp.core.SoftDeleteMixin`` declares it.
_SOFT_DELETE_COLUMN = "deleted_at"


def _string_literal(node: ast.expr | None) -> str | None:
    """*node*'s value when it is a plain string literal, else ``None``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    """The value of *call*'s ``name=`` keyword, if it has one."""
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _has_keyword(call: ast.Call, name: str) -> bool:
    """Whether *call* passes ``name=`` at all (any value, including a variable)."""
    return any(keyword.arg == name for keyword in call.keywords)


def _declared_action(call: ast.Call, keyword: str) -> str | None:
    """The action named by *call*'s *keyword*, normalised, when it is knowable.

    Accepts both the string spelling (``ondelete="CASCADE"``) and the enum
    spelling (``on_delete=OnDelete.CASCADE``); anything computed elsewhere is
    unknowable here and answers ``None``, which only ever suppresses the
    *unreachable-action* half -- the declaration itself is already present.
    """
    value = _keyword(call, keyword)
    if value is None:
        return None
    literal = _string_literal(value)
    if literal is not None:
        return literal.upper()
    if isinstance(value, ast.Attribute):
        # OnDelete.SET_NULL -> "SET NULL"
        return value.attr.replace("_", " ").upper()
    return None


def _target_table(target: str | None) -> str | None:
    """The bare table name in a ``"[schema.]table.column"`` foreign-key target."""
    if target is None or "." not in target:
        return None
    return target.rsplit(".", 2)[-2]


def _table_owner_classes(root: pathlib.Path) -> dict[str, set[str]]:
    """Map each table name to the class names that could declare it.

    Both spellings count: an explicit ``__tablename__ = "user_group"`` and the
    implicit default (SQLModel lowercases the class name). A name is mapped to a
    *set* because two packages may legitimately define same-named classes; the
    caller treats a table as soft-deletable when **any** candidate is, which fails
    closed.
    """
    owners: dict[str, set[str]] = {}
    for path in iter_python_files(root):
        for node in ast.walk(parse(path)):
            if not isinstance(node, ast.ClassDef) or not _is_table_model_class(node):
                continue
            owners.setdefault(node.name.lower(), set()).add(node.name)
            for statement in node.body:
                if not isinstance(statement, ast.Assign):
                    continue
                names = {
                    target.id
                    for target in statement.targets
                    if isinstance(target, ast.Name)
                }
                declared = _string_literal(statement.value)
                if "__tablename__" in names and declared is not None:
                    owners.setdefault(declared, set()).add(node.name)
    return owners


def _soft_delete_tables(root: pathlib.Path) -> frozenset[str]:
    """Table names whose owning model composes the soft-delete trait.

    A class counts through the trait's *column* as well as through its bases: a
    model that declares ``deleted_at`` itself behaves identically at the reference
    end, and treating only the mixin as soft-deletable would miss it.
    """
    capable = _soft_delete_capable_class_names(root)
    with_column: set[str] = set()
    for path in iter_python_files(root):
        for node in ast.walk(parse(path)):
            if not isinstance(node, ast.ClassDef) or not _is_table_model_class(node):
                continue
            if any(
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and statement.target.id == _SOFT_DELETE_COLUMN
                for statement in node.body
            ):
                with_column.add(node.name)
    soft = capable | with_column
    return frozenset(
        table for table, classes in _table_owner_classes(root).items() if classes & soft
    )


def _site_for(call: ast.Call) -> tuple[ast.Call, bool, str | None, str | None] | None:
    """*call* as a reference site ``(call, declared, action, target)``, or ``None``.

    The four spellings are matched on mutually exclusive call shapes:

    * ``Ref(target, on_delete=...)`` -- the declared form.
    * ``Field(foreign_key=..., [ondelete=...])`` -- SQLModel's own shorthand, which
      declares the behaviour when (and only when) it passes ``ondelete``.
    * ``ForeignKey(target, [ondelete=...])`` / ``ForeignKeyConstraint(cols, targets,
      [ondelete=...])`` -- a hand-built column or a table-level constraint, which
      appear inside a ``sa_column=`` or ``__table_args__``.

    Matched on the call name, like every sibling rule; the runtime audit
    (``terp.core.assert_references_declare_delete_behaviour``) is what covers a
    foreign key spelled through an aliased import, which no name-based scan can see.
    """
    name = base_name(call.func)
    if name == "Ref":
        target = _string_literal(call.args[0]) if call.args else None
        if target is None:
            # ``Ref(target="invoice.id", ...)`` is the same declaration spelled with a
            # keyword, and reachability needs the target however it was passed.
            target = _string_literal(_keyword(call, "target"))
        return (
            call,
            _has_keyword(call, "on_delete"),
            _declared_action(call, "on_delete"),
            target,
        )
    if name == "Field" and _has_keyword(call, "foreign_key"):
        return (
            call,
            _has_keyword(call, "ondelete"),
            _declared_action(call, "ondelete"),
            _string_literal(_keyword(call, "foreign_key")),
        )
    if name == "ForeignKey":
        target = _string_literal(call.args[0]) if call.args else None
        return (
            call,
            _has_keyword(call, "ondelete"),
            _declared_action(call, "ondelete"),
            target,
        )
    if name == "ForeignKeyConstraint":
        targets = call.args[1] if len(call.args) > 1 else None
        first = (
            _string_literal(targets.elts[0])
            if isinstance(targets, ast.List | ast.Tuple) and targets.elts
            else None
        )
        return (
            call,
            _has_keyword(call, "ondelete"),
            _declared_action(call, "ondelete"),
            first,
        )
    return None


def _reference_sites(
    node: ast.ClassDef,
) -> list[tuple[ast.Call, bool, str | None, str | None]]:
    """Every foreign-key declaration *node* itself makes, one per column.

    Descent is controlled rather than a flat ``ast.walk``, because two shapes would
    otherwise report the same column twice -- and a corpus case cannot catch that,
    since it only asserts the rule fired at all:

    * A **nested** table model is visited by the caller's own pass over the file, so
      walking into it here would report its columns once per enclosing class.
    * A matched site is not descended into. ``Field(foreign_key=...,
      sa_column=Column(ForeignKey(...)))`` holds a foreign key inside a foreign key,
      and it is still only one column.
    """
    sites: list[tuple[ast.Call, bool, str | None, str | None]] = []

    def visit(current: ast.AST) -> None:
        for child in ast.iter_child_nodes(current):
            if isinstance(child, ast.ClassDef):
                continue  # its own pass covers it
            site = _site_for(child) if isinstance(child, ast.Call) else None
            if site is not None:
                sites.append(site)
                continue  # one column, one finding
            visit(child)

    visit(node)
    return sites


def check_references_declare_delete_behaviour(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Every stored reference declares what a delete of its target does -- and can do it.

    A foreign key has a referential action whether or not anyone chose one, and the
    action you get by not choosing (``NO ACTION``) is indistinguishable in the
    source from the action you did choose. So the reference is *undeclared*: a
    reader cannot tell a deliberate "the database takes no action here, the service
    owns this" from an oversight, and neither can a reviewer. Declare it with
    ``Ref(target, on_delete=OnDelete.<ACTION>)`` (``terp.core``), whose ``on_delete``
    is a required keyword, so the decision cannot be skipped rather than merely
    ought not to be.

    The platform deliberately does **not** prefer an action. Which one is right
    depends on what the reference means -- ``CASCADE`` for a part of its parent,
    ``RESTRICT`` for something the parent must not vanish underneath, ``SET NULL``
    for a pointer allowed to go slack -- so all five SQL actions are accepted and
    only the *naming* is enforced. ``OnDelete.NO_ACTION`` is a full answer and emits
    no clause at all, so adopting the declaration on an existing schema costs no
    migration. A hand-built ``ForeignKey(..., ondelete=...)`` also counts: it made
    the decision without the helper.

    Second condition: an action that **cannot fire** is not a declaration, it is a
    belief. A soft-deletable target's delete is a stamp -- the audited chokepoint
    sets ``deleted_at`` and the row stays, so no ``DELETE`` ever reaches the
    constraint. ``CASCADE`` against such a target never cascades, ``SET DEFAULT``
    never defaults, and ``SET NULL`` never nulls -- the worst of the three, because
    the children keep a live pointer to a row the read scope now hides from every
    query, so the reference reads as broken rather than absent. What separates these
    from the two that are accepted is not that they are active: it is that the reason
    for declaring them depends on their firing, where ``RESTRICT`` and ``NO_ACTION``
    are honest descriptions of the hard-delete path no request can reach. Declare one
    of those and cascade the stamp from the owning service, the only layer that can
    see it.
    """
    root = pathlib.Path(app_root)
    soft_delete_tables = _soft_delete_tables(root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        if _module_under(path, package) is None:
            continue
        rel = _rel(path, root)
        for node in ast.walk(parse(path)):
            if not isinstance(node, ast.ClassDef) or not _is_table_model_class(node):
                continue
            for call, declared, action, target in _reference_sites(node):
                if not declared:
                    violations.append(
                        ArchViolation(
                            "references_declare_delete_behaviour",
                            rel,
                            call.lineno,
                            f"table model {node.name!r} declares a foreign key with no "
                            "delete behaviour, so its action is whatever SQL defaults to "
                            "and no reader can tell that was a choice; declare it with "
                            "Ref(target, on_delete=OnDelete.<ACTION>) -- every action is "
                            "accepted, and OnDelete.NO_ACTION emits no clause, so saying "
                            "so costs no migration",
                        )
                    )
                    continue
                table = _target_table(target)
                if (
                    action in _UNREACHABLE_AGAINST_SOFT_DELETE
                    and table is not None
                    and table in soft_delete_tables
                ):
                    violations.append(
                        ArchViolation(
                            "references_declare_delete_behaviour",
                            rel,
                            call.lineno,
                            f"table model {node.name!r} declares ON DELETE {action} against "
                            f"soft-deletable table {table!r}, an action that can never fire: "
                            "that target is never DELETEd, only stamped, so the clause is "
                            "dead and the guarantee it looks like does not exist (SET NULL "
                            "worst of all -- the row keeps a live pointer to a row every "
                            "read now hides). Declare RESTRICT or NO_ACTION as the "
                            "hard-delete backstop and cascade the stamp from the service",
                        )
                    )
    return sorted(violations, key=lambda violation: (violation.path, violation.line))


__all__ = ["check_references_declare_delete_behaviour"]
