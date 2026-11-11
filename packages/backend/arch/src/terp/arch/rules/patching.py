"""The patching rule: app code calls the framework and never replaces its functions.

A check that runs the framework's code is only worth what that code is: the comparison an
app makes with its ``authz-surface.json`` before it serves (ADR 0212), the guard on every
route, a boot refusal. Each can be turned off from inside the app by replacing the function
that performs it, in one line and with every other check still green.
:func:`check_no_framework_patching` refuses the statements that do that, for the framework
and for the web stack whose route table the framework reads.

It reads one file at a time and follows a name no further than a plain assignment. What it
does not see is recorded as the rule's residuals. It does not read ``tests`` directories:
replacing a function there, with ``monkeypatch`` or ``mock.patch``, is how a test is written.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator

from terp.arch._ast import iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _rel

_RULE = "no_framework_patching"
#: The packages whose functions an app calls and never replaces: the framework, and the web
#: stack whose route table its composition and its startup comparison walk.
_GUARDED = ("terp", "fastapi", "starlette")
#: Where ``patch`` comes from, in either spelling.
_MOCK = ("unittest", "mock")
#: The calls that set or delete an attribute by name.
_SETTERS = frozenset({"setattr", "delattr", "__setattr__", "__delattr__"})
#: The methods that put a module into the module registry, or take one out, by key.
_REGISTRY_WRITERS = frozenset({"__setitem__", "__delitem__", "setdefault", "pop", "update"})
_REMEDY = (
    "app code calls the framework and never replaces its functions, so a check that runs "
    "the framework's code is running the code that shipped: use the seam the framework "
    "gives for what you need (a create_app parameter, a ModuleSpec, a registered predicate), "
    "and replace a function only in a test"
)


def _guarded(dotted: str) -> bool:
    return dotted.split(".", 1)[0] in _GUARDED


def _literal(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _dotted(node: ast.AST) -> str:
    """A name or attribute chain as written, or ``""`` for anything else."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


class _File:
    """One parsed file: the names it binds to the guarded packages, and to ``mock``."""

    def __init__(self, tree: ast.Module) -> None:
        self.names: set[str] = set()
        self.mocks: set[str] = set()
        #: How the file spells the module registry: `sys.modules`, or the name it imports it as.
        self.registry = {"sys.modules"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".", 1)[0]
                    if _guarded(alias.name):
                        self.names.add(bound)
                    elif alias.name.split(".", 1)[0] in _MOCK:
                        self.mocks.add(bound)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                for alias in node.names:
                    if node.module == "sys" and alias.name == "modules":
                        self.registry.add(alias.asname or alias.name)
                    elif _guarded(node.module):
                        self.names.add(alias.asname or alias.name)
                    elif node.module.split(".", 1)[0] in _MOCK:
                        self.mocks.add(alias.asname or alias.name)
        # A plain assignment carries the reference on: `kernel = terp.core.app`. Repeated
        # until nothing joins, so a chain of them is followed however it is ordered.
        assignments = [
            (node.targets[0].id, node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ]
        grew = True
        while grew:
            grew = False
            for name, value in assignments:
                if name not in self.names and self.refers(value):
                    self.names.add(name)
                    grew = True

    def is_registry(self, node: ast.AST) -> bool:
        return _dotted(node) in self.registry

    def refers(self, node: ast.AST) -> bool:
        """Whether *node* is a reference into a guarded package, and not a call's result."""
        if isinstance(node, ast.Name):
            return node.id in self.names
        if isinstance(node, ast.Attribute):
            return self.refers(node.value)
        if isinstance(node, ast.Subscript):
            # sys.modules["terp.core.app"], and a guarded module's own namespace by key.
            if self.is_registry(node.value):
                return _guarded(_literal(node.slice) or "")
            return self.namespace(node.value)
        if isinstance(node, ast.Call):
            called = _dotted(node.func)
            if called in {"import_module", "importlib.import_module", "__import__"}:
                return bool(node.args) and _guarded(_literal(node.args[0]) or "")
        return False

    def namespace(self, node: ast.AST) -> bool:
        """Whether *node* is a guarded object's namespace: ``X.__dict__`` or ``vars(X)``."""
        if isinstance(node, ast.Attribute) and node.attr == "__dict__":
            return self.refers(node.value)
        if isinstance(node, ast.Call) and _dotted(node.func) == "vars" and node.args:
            return self.refers(node.args[0])
        return False

    def replaced(self, target: ast.AST) -> str | None:
        """What an assignment or a deletion of *target* replaces, or ``None``."""
        if isinstance(target, ast.Attribute) and self.refers(target.value):
            return _dotted(target) or f"an attribute {target.attr!r} of the framework"
        if isinstance(target, ast.Subscript):
            if self.is_registry(target.value) and _guarded(_literal(target.slice) or ""):
                return f"sys.modules[{_literal(target.slice)!r}]"
            if self.namespace(target.value):
                return f"a name in {_dotted(target.value) or 'a namespace of the framework'}"
        return None

    def patched(self, call: ast.Call) -> str | None:
        """What *call* replaces by name, or ``None``: ``setattr``, ``patch`` and their kin."""
        if not call.args:
            return None
        first = call.args[0]
        method = isinstance(call.func, ast.Attribute)
        leaf = call.func.attr if method else _dotted(call.func)
        called = _dotted(call.func) or leaf
        if method and leaf in _REGISTRY_WRITERS and self.is_registry(call.func.value):
            keys = first.keys if isinstance(first, ast.Dict) else [first]
            named = [text for key in keys if (text := _literal(key)) and _guarded(text)]
            return f"sys.modules.{leaf} of {named[0]}" if named else None
        if leaf in _SETTERS and self.refers(first):
            return f"{leaf} on {_dotted(first) or 'the framework'}"
        text = _literal(first)
        # A patcher's own method takes the target as a dotted string: MonkeyPatch.setattr.
        if method and leaf in {"setattr", "delattr"} and text and _guarded(text):
            return f"{called} of {text}"
        if called.split(".", 1)[0] in self.mocks and "patch" in called.split("."):
            if text and _guarded(text):
                return f"{called} of {text}"
            if self.refers(first):
                return f"{called} on {_dotted(first) or 'the framework'}"
        return None


def _targets(node: ast.AST) -> Iterator[ast.AST]:
    """Every place a statement assigns to or deletes, through tuples and stars."""
    if isinstance(node, ast.Assign):
        pending = list(node.targets)
    elif isinstance(node, ast.AugAssign | ast.AnnAssign):
        pending = [node.target]
    elif isinstance(node, ast.Delete):
        pending = list(node.targets)
    else:
        return
    while pending:
        target = pending.pop()
        if isinstance(target, ast.Tuple | ast.List):
            pending.extend(target.elts)
        elif isinstance(target, ast.Starred):
            pending.append(target.value)
        else:
            yield target


def check_no_framework_patching(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """App code does not replace a function of the framework or of the web stack it reads.

    Refused: an assignment to, or a deletion of, an attribute reached through a name the
    file imports from ``terp``, ``fastapi`` or ``starlette``; the same through
    ``sys.modules[...]``, ``importlib.import_module(...)``, an object's ``__dict__`` or
    ``vars()``; a module of those packages replaced in ``sys.modules``; ``setattr`` and
    ``delattr`` on such a name; and ``mock.patch`` of one. Each makes a check that runs the
    framework's code run something else (ADR 0212).
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        file = _File(tree)
        found: dict[int, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                what = file.patched(node)
                if what is not None:
                    found.setdefault(node.lineno, f"{what} replaces it at run time")
                continue
            for target in _targets(node):
                what = file.replaced(target)
                if what is not None:
                    verb = "deleted" if isinstance(node, ast.Delete) else "assigned"
                    found.setdefault(node.lineno, f"{what} is {verb} at run time")
        violations.extend(
            ArchViolation(_RULE, _rel(path, root), line, f"{message}; {_REMEDY}")
            for line, message in sorted(found.items())
        )
    return violations


__all__ = ["check_no_framework_patching"]
