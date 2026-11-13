"""Reading an Alembic revision file as data: which revision it is, and which it follows.

A reader that lists the migration histories a release carries, a release manifest's
reader for one, needs every revision's identity without importing the revision, because
importing a revision runs it. So the header is read the way the harness reads
everything, from the source with :func:`ast.parse`, and nothing here imports or executes
the file. Whether it depends on a revision beside the ones it follows is
:func:`revision_depends_on`, and what its ``upgrade()`` destroys is
:func:`terp.arch.destructive_operations`, each read the same way.
"""

from __future__ import annotations

import ast
import reprlib
from dataclasses import dataclass


@dataclass(frozen=True)
class RevisionHeader:
    """A revision's ``revision`` id and its ``down_revision`` as the file writes it.

    ``down_revision`` is ``None`` for a history's first revision, one id for an
    ordinary revision, and a tuple of ids for a merge; a list in the file is read as
    the tuple of the same ids, in the same order.
    """

    revision: str
    down_revision: str | tuple[str, ...] | None

    @property
    def parents(self) -> tuple[str, ...]:
        """The revisions this one follows, in the file's order: none, one, or several."""
        if self.down_revision is None:
            return ()
        if isinstance(self.down_revision, str):
            return (self.down_revision,)
        return self.down_revision


def revision_header(source: str) -> RevisionHeader:
    """The ``revision`` and ``down_revision`` the revision file *source* assigns.

    Each is read from the one module-level assignment to it, ``name = <literal>`` or
    ``name: <annotation> = <literal>``, as Alembic's own template writes it: the
    ``revision`` a string, the ``down_revision`` ``None``, a string, or a tuple or list
    of strings. *source* is parsed with :func:`ast.parse` and is never imported or
    executed, so source that does not parse raises :class:`SyntaxError`, as
    ``no_destructive_migrations`` does. A header that cannot be read for certain raises
    :class:`ValueError` naming the variable: one that is not assigned at module level,
    or is bound there more than once, or by anything but that plain assignment, or to
    anything but such a literal. ``branch_labels`` and ``depends_on`` are not read.
    """
    tree = ast.parse(source)
    revision = _assigned(tree, "revision")
    if not isinstance(revision, str):
        raise ValueError(f"'revision' must be a string, not {reprlib.repr(revision)}")
    down_revision = _assigned(tree, "down_revision")
    if isinstance(down_revision, list | tuple) and all(
        isinstance(parent, str) for parent in down_revision
    ):
        return RevisionHeader(revision, tuple(down_revision))
    if down_revision is None or isinstance(down_revision, str):
        return RevisionHeader(revision, down_revision)
    raise ValueError(
        "'down_revision' must be None, a string, or a tuple of strings, "
        f"not {reprlib.repr(down_revision)}"
    )


def revision_depends_on(source: str) -> object:
    """The ``depends_on`` the revision file *source* assigns, or ``None`` where it assigns none.

    Read as :func:`revision_header` reads ``down_revision``: from the one module-level
    assignment to it, ``depends_on = <literal>`` or ``depends_on: <annotation> = <literal>``,
    and returned as written. Alembic's own template writes ``None``, and unlike the header's
    two names this one may be left out, which Alembic reads as ``None`` too. A revision that
    depends on another is the only one of the two Alembic writes to the version table, so a
    reader that follows ``down_revision`` to tell what is applied would count the dependency
    pending ever after; such a reader refuses anything but ``None``. *source* is parsed with
    :func:`ast.parse` and is never imported or executed: source that does not parse raises
    :class:`SyntaxError`, and a ``depends_on`` bound more than once at module level, or by
    anything but that plain assignment, or to anything but a literal, raises
    :class:`ValueError` naming it.
    """
    tree = ast.parse(source)
    if not any(_binds(statement, "depends_on") for statement in tree.body):
        return None
    return _assigned(tree, "depends_on")


def _assigned(tree: ast.Module, name: str) -> object:
    """The literal value of the one module-level binding of *name* in *tree*."""
    bindings = [statement for statement in tree.body if _binds(statement, name)]
    if not bindings:
        raise ValueError(f"the revision assigns no module-level {name!r}")
    if len(bindings) > 1:
        raise ValueError(f"the revision binds {name!r} {len(bindings)} times at module level")
    statement = bindings[0]
    targets: list[ast.expr] = []
    value: ast.expr | None = None
    if isinstance(statement, ast.Assign):
        targets, value = statement.targets, statement.value
    elif isinstance(statement, ast.AnnAssign):
        targets, value = [statement.target], statement.value
    if value is None or not any(
        isinstance(target, ast.Name) and target.id == name for target in targets
    ):
        raise ValueError(f"{name!r} must be assigned on its own, as `{name} = <literal>`")
    try:
        return ast.literal_eval(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name!r} must be assigned a literal") from exc


def _binds(statement: ast.stmt, name: str) -> bool:
    """True when *statement* binds *name* anywhere in its targets.

    A bare annotation (``revision: str``) binds nothing, so it is not counted.
    """
    targets: list[ast.expr]
    if isinstance(statement, ast.Assign):
        targets = statement.targets
    elif isinstance(statement, ast.AugAssign) or (
        isinstance(statement, ast.AnnAssign) and statement.value is not None
    ):
        targets = [statement.target]
    else:
        return False
    return any(
        isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Store)
        for target in targets
        for node in ast.walk(target)
    )


__all__ = ["RevisionHeader", "revision_depends_on", "revision_header"]
