"""Per-module role rules (ADR 0121): the declaration, the refusal, and the chokepoint.

A per-module role is an *assignment*: the rungs are code and the holders are data. These
three rules police the code half — that a module which opts in says what to call it, that a
module which can hand authority out never opts in at all, and that nobody writes the
assignment table around the service that audits and validates the write.

Separate from ``authz`` deliberately. That module is about the coarse gate every module
declares (a ``Policy``, and typed references into it); this one is about the narrower,
optional axis a module may add on top, whose failure mode is escalation rather than an
undeclared surface.
"""

from __future__ import annotations

import ast
import pathlib

from terp.arch._ast import base_name, iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _module_under, _rel

#: The two services that can hand authority out. A module holding either can create a
#: grant or a per-module rung, which is the authority that confers every other one.
_AUTHORITY_SERVICES = frozenset({"AccessService", "ModuleRoleService"})

#: The assignment table. A module writing it directly bypasses the audited chokepoint *and*
#: ``validate_assignment``, which is what turns an undeclared row into an unenforceable one.
_MODULE_ROLE_MODEL = "ModuleRole"


def _module_access_calls(tree: ast.AST) -> list[ast.Call]:
    """Every ``ModuleAccess(...)`` and ``ModuleAccess.platform_only(...)`` in *tree*."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and base_name(node.func) == "ModuleAccess"
    ]


def _declares_assignable(call: ast.Call) -> bool:
    """Whether this ``ModuleAccess(...)`` opts the module into per-module roles.

    Only a literal ``True`` counts. A computed value is not read as an opt-in, and
    deliberately: guessing *in* flags a module for a declaration it does not make, and
    guessing *out* is an escape. Neither is acceptable, so a non-literal is left to the
    constructor invariant and the boot check, both of which see the real value.
    """
    for keyword in call.keywords:
        if keyword.arg == "assignable":
            return isinstance(keyword.value, ast.Constant) and keyword.value.value is True
    return False


def check_grantable_modules_are_named(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A module that opts into per-module roles declares what to call it.

    The label is the only text an administrator ever sees for the module in the access
    pane, which renders one strip per assignable module. A strip headed by an identifier
    tells a reader who cannot read the source nothing about what they are granting.

    ``ModuleAccess`` enforces the same thing as a constructor invariant, so this is the
    build-time half of one control rather than a second control. What it adds is the file
    and the line, before the app is imported — the difference between a fixable message
    and a traceback out of composition.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        if _module_under(path, package) is None:
            continue
        rel = _rel(path, root)
        for call in _module_access_calls(parse(path)):
            if not _declares_assignable(call):
                continue
            labelled = any(
                keyword.arg == "label"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
                and keyword.value.value.strip() != ""
                for keyword in call.keywords
            )
            if not labelled:
                violations.append(
                    ArchViolation(
                        "grantable_modules_are_named",
                        rel,
                        call.lineno,
                        "ModuleAccess(assignable=True) declares no label=; the access "
                        "pane heads this module's strip with it, and an administrator "
                        "reading an identifier cannot tell what they are granting. Add a "
                        "label (fix recipe: terp guide permissions)",
                    )
                )
    return violations


def check_platform_modules_refuse_module_roles(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A module that can hand authority out is never itself per-module assignable.

    Per-module ``admin`` in a module that administers grants is not a *use* of the ladder,
    it is a way around it: whoever holds it can grant themselves anything, everywhere, and
    the rung that let them looks like a narrow one. The platform's own capabilities declare
    ``ModuleAccess.platform_only(reason=...)`` for exactly that reason, and an application
    module that reaches for ``AccessService`` or ``ModuleRoleService`` has taken on the same
    authority and owes the same refusal.

    Deliberately shallow and syntactic, because it is the escalation guard: naming the
    service at all is the trigger, with no attempt to decide whether a call site only reads.
    A read is the first half of a write, and no static check can tell a module that lists
    grants from one that is about to create one.

    The trigger and the declaration are usually in different files of the same module —
    ``service.py`` holds the service, ``module.py`` holds the manifest — so the unit is the
    module directory, and the violation is reported where the declaration is, since that is
    the line to change.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    flagged: set[tuple[str, int]] = set()
    for path in iter_python_files(root):
        if _module_under(path, package) is None:
            continue
        holds_authority = any(
            isinstance(node, (ast.Name, ast.Attribute))
            and base_name(node) in _AUTHORITY_SERVICES
            for node in ast.walk(parse(path))
        )
        if not holds_authority:
            continue
        for sibling in sorted(path.parent.glob("*.py")):
            rel = _rel(sibling, root)
            for call in _module_access_calls(parse(sibling)):
                if not _declares_assignable(call):
                    continue
                # Two files in one module can each name the service; the declaration is
                # still one line, and one line deserves one violation.
                if (rel, call.lineno) in flagged:
                    continue
                flagged.add((rel, call.lineno))
                violations.append(
                    ArchViolation(
                        "platform_modules_refuse_module_roles",
                        rel,
                        call.lineno,
                        "this module holds AccessService or ModuleRoleService, so a "
                        "per-module admin here could grant itself every other authority "
                        "— a way around the role ladder rather than a use of it. Declare "
                        "ModuleAccess.platform_only with a reason instead of opting in "
                        "(fix recipe: terp guide permissions)",
                    )
                )
    return violations


def check_module_role_writes_go_through_the_capability(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """No module touches the per-module assignment table itself.

    Every write has to pass ``ModuleRoleService``, which is where the audit row is emitted
    and where ``validate_assignment`` refuses a rung the declarations cannot support — a
    platform module, a module that never opted in, a rank the ladder does not declare. A row
    written around that is not a lenient assignment; it is one that can never fire, and
    whoever wrote it will believe the person is authorized until the moment they are not.

    A plain *read* of the model is refused too, on the same footing as
    ``no_manual_ownership_checks``: a read is the first half of a hand-rolled per-module
    gate, and no static check can tell it from a read that only displays a rung. The
    question "what does this subject hold?" already has an answer that carries provenance
    with it, so a module has no reason to ask the table.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        if _module_under(path, package) is None:
            continue
        rel = _rel(path, root)
        for node in ast.walk(parse(path)):
            if not isinstance(node, (ast.Name, ast.Attribute)):
                continue
            if base_name(node) != _MODULE_ROLE_MODEL:
                continue
            violations.append(
                ArchViolation(
                    "module_role_writes_go_through_the_capability",
                    rel,
                    node.lineno,
                    "the ModuleRole table belongs to the access capability: reach it "
                    "through ModuleRoleService, or ask the capability what a subject "
                    "holds, so the write is audited and refused when the declarations "
                    "cannot support it (fix recipe: terp guide permissions)",
                )
            )
    return violations
