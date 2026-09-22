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


def _module_root(path: pathlib.Path) -> pathlib.Path | None:
    """The ``modules/<name>`` directory *path* lives in, or ``None`` when it is not in one.

    ``_module_under`` answers *which* module a file belongs to but not where that module
    starts, and the difference is an escape rather than a detail: a service kept in
    ``modules/billing/services/grants.py`` has a parent directory with no manifest in it, so
    a rule that globbed the *file's own* parent never saw the declaration it was looking for,
    and the module went unchecked.

    One guard, not two: this both answers the question and decides whether the file is a
    module file at all, so a caller needs no separate ``_module_under`` test — and a second
    check for a path ending at ``modules`` itself would be a line nothing can reach, since
    only ``*.py`` files are scanned.
    """
    parts = path.parts
    if "modules" not in parts:
        return None
    return pathlib.Path(*parts[: parts.index("modules") + 2])

#: The two services that can hand authority out. A module holding either can create a
#: grant or a per-module rung, which is the authority that confers every other one.
_AUTHORITY_SERVICES = frozenset({"AccessService", "ModuleRoleService"})

#: The assignment table. A module writing it directly bypasses the audited chokepoint *and*
#: ``validate_assignment``, which is what turns an undeclared row into an unenforceable one.
_MODULE_ROLE_MODEL = "ModuleRole"


def _module_access_calls(tree: ast.AST) -> list[ast.Call]:
    """Every ``ModuleAccess(...)`` and ``ModuleAccess.platform_only(...)`` in *tree*.

    Both spellings, and the second needs its own arm: ``base_name`` yields an attribute's
    *last* segment, so ``base_name(node.func)`` is ``"platform_only"`` for the classmethod
    form and matching on it alone saw only the constructor. The refusal is the declaration
    this rule most needs to read, so missing it made the whole platform-only half invisible
    — including, before this, the branch that asks whether a refusal says why.
    """
    found: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            # `ModuleAccess.platform_only(...)`, and equally `terp.core.ModuleAccess.x(...)`,
            # since `base_name` walks an attribute chain down to its root name.
            if base_name(func.value) == "ModuleAccess":
                found.append(node)
        elif base_name(func) == "ModuleAccess":
            found.append(node)
    return found


def _is_platform_only(call: ast.Call) -> bool:
    """Whether this call is the refusal form, ``ModuleAccess.platform_only(...)``."""
    func = call.func
    return isinstance(func, ast.Attribute) and func.attr == "platform_only"


def _states_a_reason(call: ast.Call) -> bool:
    """Whether the refusal carries a non-empty literal ``reason=``.

    The signature makes the reason *present* — it is a required keyword-only argument, so
    omitting it is an import-time ``TypeError`` and no static rule is needed for that. It
    does not make the reason *meaningful*: ``platform_only(reason="")`` constructs happily,
    and produces a module the access screen lists as never assignable with a blank
    explanation, which is the state the mandatory argument existed to prevent. A non-literal
    is accepted, for the reason a non-literal ``assignable=`` is: the rule refuses to guess
    at a value it cannot see.
    """
    stated = next((k.value for k in call.keywords if k.arg == "reason"), None)
    if stated is None:
        return False
    if not isinstance(stated, ast.Constant):
        return True
    return isinstance(stated.value, str) and stated.value.strip() != ""


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


def _is_named(value: ast.expr) -> bool:
    """Whether a ``label=`` argument names the module.

    A non-literal counts. The rule refuses to guess at a value it cannot see — the same
    answer it gives a computed ``assignable=`` and a computed ``reason=`` — and here the cost
    of guessing wrong is a message that is simply false: the old test accepted only a literal
    string, so ``label=MODULE_TITLE`` was reported as "declares no label=" on a line that
    plainly declares one, and the fix the message asked for had already been made.
    """
    if not isinstance(value, ast.Constant):
        return True
    return isinstance(value.value, str) and value.value.strip() != ""


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
                keyword.arg == "label" and _is_named(keyword.value)
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
    app_root: str | pathlib.Path,
    *,
    package: str = "app",  # noqa: ARG001  (the harness calls every rule with it)
) -> list[ArchViolation]:
    """A module that can hand authority out is never itself per-module assignable.

    Per-module ``admin`` in a module that administers grants is not a *use* of the ladder,
    it is a way around it: whoever holds it can grant themselves anything, everywhere, and
    the rung that let them looks like a narrow one. The platform's own capabilities declare
    ``ModuleAccess.platform_only(reason=...)`` for exactly that reason, and an application
    module that reaches for ``AccessService`` or ``ModuleRoleService`` has taken on the same
    authority and owes the same refusal.

    Two shapes of the same failure, because the declaration has to say two things: that the
    module refuses, and why. A refusal with a blank reason is listed on the access screen as
    never assignable with nothing beside it, which leaves exactly the question the reason
    exists to answer — and the constructor cannot catch it, since a required keyword argument
    makes the reason present rather than meaningful.

    Deliberately shallow and syntactic, because it is the escalation guard: naming the
    service at all is the trigger, with no attempt to decide whether a call site only reads.
    A read is the first half of a write, and no static check can tell a module that lists
    grants from one that is about to create one.

    The trigger and the declaration are usually in different files of the same module —
    ``service.py`` holds the service, ``module.py`` holds the manifest — so the unit is the
    module directory rather than the triggering file's own, and the violation is reported
    where the declaration is, since that is the line to change. The distinction is load
    bearing: a service kept in ``modules/billing/services/grants.py`` sits in a directory
    with no manifest, and globbing beside the file rather than at the module root let exactly
    that layout escape the check.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    flagged: set[tuple[str, int]] = set()
    for path in iter_python_files(root):
        module_root = _module_root(path)
        if module_root is None:
            continue
        holds_authority = any(
            isinstance(node, (ast.Name, ast.Attribute))
            and base_name(node) in _AUTHORITY_SERVICES
            for node in ast.walk(parse(path))
        )
        if not holds_authority:
            continue
        for sibling in sorted(module_root.glob("*.py")):
            rel = _rel(sibling, root)
            for call in _module_access_calls(parse(sibling)):
                if _declares_assignable(call):
                    message = (
                        "this module holds AccessService or ModuleRoleService, so a "
                        "per-module admin here could grant itself every other authority "
                        "— a way around the role ladder rather than a use of it. Declare "
                        "ModuleAccess.platform_only with a reason instead of opting in "
                        "(fix recipe: terp guide permissions)"
                    )
                elif _is_platform_only(call) and not _states_a_reason(call):
                    message = (
                        "this module refuses per-module roles but says nothing about why; "
                        "the access screen lists it as never assignable and has nothing to "
                        "show beside that, which leaves the reader the exact question the "
                        "reason answers. Give ModuleAccess.platform_only a reason that "
                        "names the authority at stake (fix recipe: terp guide permissions)"
                    )
                else:
                    continue
                # Two files in one module can each name the service; the declaration is
                # still one line, and one line deserves one violation.
                if (rel, call.lineno) in flagged:
                    continue
                flagged.add((rel, call.lineno))
                violations.append(
                    ArchViolation(
                        "platform_modules_refuse_module_roles", rel, call.lineno, message
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
