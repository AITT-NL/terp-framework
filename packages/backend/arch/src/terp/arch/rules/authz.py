"""Authority rules: deny-by-default policy + typed permission references.

Every module declares a ``Policy``; every authority it cites is a typed
``Role`` / ``Permission`` from the control plane, never a bare string.
"""

from __future__ import annotations

import ast
import pathlib

from terp.arch._ast import base_name, iter_python_files, parse
from terp.arch.rules._support import (
    ArchViolation,
    _MUTATING_HTTP_METHODS,
    _POLICY_AUTHZ_KEYWORDS,
    _module_under,
    _rel,
)


def check_modules_declare_policy(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Every ``modules/<name>/module.py`` declares a ``ModuleSpec`` with a ``policy=``."""
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        if path.name != "module.py" or _module_under(path, package) is None:
            continue
        tree = parse(path)
        rel = _rel(path, root)
        found_spec = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and base_name(node.func) == "ModuleSpec":
                found_spec = True
                if not any(keyword.arg == "policy" for keyword in node.keywords):
                    violations.append(
                        ArchViolation(
                            "modules_declare_policy",
                            rel,
                            node.lineno,
                            "ModuleSpec declares no policy=; deny-by-default requires "
                            "an explicit Policy. Use Policy.default() for authenticated "
                            "CRUD; Policy.public(reason=...) is only for an intentionally "
                            "unauthenticated module",
                        )
                    )
        if not found_spec:
            violations.append(
                ArchViolation(
                    "modules_declare_policy",
                    rel,
                    1,
                    "module.py declares no ModuleSpec",
                )
            )
    return violations


def check_no_adhoc_permission_literals(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Modules reference typed authority objects, never bare permission strings."""
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = base_name(node.func)
            if name == "Policy":
                for keyword in node.keywords:
                    if keyword.arg in _POLICY_AUTHZ_KEYWORDS and isinstance(
                        keyword.value, ast.Constant
                    ) and isinstance(keyword.value.value, str):
                        violations.append(
                            ArchViolation(
                                "no_adhoc_permission_literals",
                                rel,
                                keyword.value.lineno,
                                "Policy authority must reference a typed Role or Permission "
                                "from control_plane.permissions, not a string literal",
                            )
                        )
            if name == "require_permission" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    violations.append(
                        ArchViolation(
                            "no_adhoc_permission_literals",
                            rel,
                            first.lineno,
                            "require_permission must receive a typed Permission from "
                            "control_plane.permissions, not a string literal",
                        )
                    )
    return violations


def _methods_kwarg_has_mutation(keywords: list[ast.keyword]) -> bool:
    """True when a route call's ``methods=[...]`` lists a write verb."""
    for keyword in keywords:
        if keyword.arg == "methods" and isinstance(keyword.value, ast.List | ast.Tuple):
            if any(
                isinstance(element, ast.Constant)
                and isinstance(element.value, str)
                and element.value.lower() in _MUTATING_HTTP_METHODS
                for element in keyword.value.elts
            ):
                return True
    return False


def _has_mutating_route(tree: ast.Module) -> bool:
    """True when *tree* declares a write route (``post`` / ``put`` / ``patch`` / ``delete``).

    Catches the verb decorators (``@router.post``), a generic ``@router.api_route`` /
    imperative ``add_api_route`` with ``methods=`` listing a write verb, so a write
    surface cannot dodge the policy check by its registration spelling.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(
                    decorator.func, ast.Attribute
                ):
                    continue
                if decorator.func.attr in _MUTATING_HTTP_METHODS:
                    return True
                if decorator.func.attr == "api_route" and _methods_kwarg_has_mutation(
                    decorator.keywords
                ):
                    return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"add_api_route", "api_route"}
            and _methods_kwarg_has_mutation(node.keywords)
        ):
            return True
    return False


def _module_policy_calls(tree: ast.Module) -> list[ast.Call]:
    """The ``Policy(...)`` / ``Policy.tiers(...)`` expressions bound to a ``ModuleSpec.policy``.

    Only the policy actually handed to ``ModuleSpec(policy=...)`` is returned, so an
    unrelated weak ``Policy(...)`` sitting elsewhere in the file is never mistaken for
    the module's posture.
    """
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or base_name(node.func) != "ModuleSpec":
            continue
        for keyword in node.keywords:
            value = keyword.value
            if keyword.arg == "policy" and isinstance(value, ast.Call):
                func = value.func
                rooted_at_policy = (isinstance(func, ast.Name) and func.id == "Policy") or (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "Policy"
                )
                if rooted_at_policy:
                    calls.append(value)
    return calls


# The default role ladder's ranks, so the build rule can compare a statically
# resolvable read/write tier (``Roles.VIEWER`` / the ``VIEWER`` constant / ``x.ADMIN``).
# A *custom* role's rank is not knowable from a source scan, so those are compared by
# their resolved rank at boot (``create_app`` -> ``_validate_policy_write_tiers``); this
# rule is the early-warning build-time half.
_DEFAULT_ROLE_RANKS: dict[str, int] = {"VIEWER": 10, "EDITOR": 20, "ADMIN": 30}


def _policy_kwarg(call: ast.Call, *names: str) -> ast.expr | None:
    """Return the first present keyword value among *names* on *call*, else ``None``."""
    for keyword in call.keywords:
        if keyword.arg in names:
            return keyword.value
    return None


def _static_default_rank(node: ast.expr | None, *, absent: int) -> int | None:
    """Statically resolve a role reference to its rank.

    ``None`` node -> *absent* (the framework default: read omits to ``VIEWER``, write to
    ``EDITOR``). A default-ladder reference (``Roles.ADMIN`` / ``ADMIN``) -> its rank. A
    custom role whose rank a scan cannot know -> ``None`` (the boot check compares it).
    """
    if node is None:
        return absent
    return _DEFAULT_ROLE_RANKS.get(base_name(node))


def check_mutations_require_write_role(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A module with a mutating route must not gate writes below its read tier.

    A module that exposes ``POST`` / ``PUT`` / ``PATCH`` / ``DELETE`` is a write
    surface, so its ``Policy`` must gate writes **at or above** the read tier —
    otherwise anyone who can read can also mutate (privilege inversion). Two shapes are
    caught statically: the write tier set to the read floor ``VIEWER``
    (``Policy(write=Roles.VIEWER)`` / ``Policy.tiers(write=…)``), and a default-ladder
    inversion where the write rank is below the read rank (``Policy(read=Roles.ADMIN,
    write=Roles.EDITOR)``, or ``Policy(read=Roles.ADMIN)`` where write defaults to the
    lower ``EDITOR``). ``Policy.default()`` (read=VIEWER, write=EDITOR) is the safe
    default; ``ADMIN`` is fine. A *custom* role ladder's ranks are not knowable from a
    source scan, so those are enforced by the boot-time check
    (``create_app`` -> ``_validate_policy_write_tiers``) — this rule is the early-warning
    build-time half. A public module is governed by ``public_modules_are_read_only``
    instead. The check is tied to the policy bound to the module's ``ModuleSpec(policy=…)``.
    """
    root = pathlib.Path(app_root)
    mutating_modules: set[str] = set()
    policies: list[tuple[str, str, ast.Call]] = []
    for path in iter_python_files(root):
        module = _module_under(path, package)
        if module is None:
            continue
        tree = parse(path)
        if _has_mutating_route(tree):
            mutating_modules.add(module)
        if path.name == "module.py":
            rel = _rel(path, root)
            policies.extend((module, rel, call) for call in _module_policy_calls(tree))

    violations: list[ArchViolation] = []
    for module, rel, call in policies:
        if module not in mutating_modules:
            continue
        if isinstance(call.func, ast.Attribute) and call.func.attr == "public":
            continue  # a public module is governed by public_modules_are_read_only
        write_node = _policy_kwarg(call, "write", "write_role")
        read_node = _policy_kwarg(call, "read", "read_role")
        at_read_floor = write_node is not None and base_name(write_node) == "VIEWER"
        write_rank = _static_default_rank(write_node, absent=_DEFAULT_ROLE_RANKS["EDITOR"])
        read_rank = _static_default_rank(read_node, absent=_DEFAULT_ROLE_RANKS["VIEWER"])
        inverted = write_rank is not None and read_rank is not None and write_rank < read_rank
        if at_read_floor or inverted:
            anchor = write_node if write_node is not None else call
            violations.append(
                ArchViolation(
                    "mutations_require_write_role",
                    rel,
                    anchor.lineno,
                    f"module {module!r} exposes a mutating route but its Policy gates writes "
                    "at or below the read tier (privilege inversion); the write tier must "
                    "outrank the read floor (use Policy.default() for EDITOR, or "
                    "write=Roles.ADMIN)",
                )
            )
    return violations


def check_public_modules_are_read_only(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A public (unauthenticated) module must not expose a mutating route.

    ``Policy.public(reason=…)`` drops authentication for the **whole** module, so a
    ``POST`` / ``PUT`` / ``PATCH`` / ``DELETE`` under it is an *unauthenticated write* —
    almost always an accident (applying ``Policy.public`` to a module that also has
    writes), and the broken-access-control footgun the deny-by-default posture exists to
    prevent. A genuinely public write (a sign-up / contact form / webhook receiver) is
    rare and deliberate, so it stays available through the governed escape hatch: a
    justified ``# arch-allow-public-modules-are-read-only: <reason>`` marker (ratcheted by
    the escape-hatch budget), making the unauthenticated write **visible and budgeted**
    rather than silent. Gate the writes behind a Policy with a write role, or justify the
    public write explicitly. (Build-time governance, like ``canonical_module_shape``: the
    runtime posture — public means no auth — is intentional and unchanged.)
    """
    root = pathlib.Path(app_root)
    mutating_modules: set[str] = set()
    public_policies: list[tuple[str, str, ast.Call]] = []
    for path in iter_python_files(root):
        module = _module_under(path, package)
        if module is None:
            continue
        tree = parse(path)
        if _has_mutating_route(tree):
            mutating_modules.add(module)
        if path.name == "module.py":
            rel = _rel(path, root)
            public_policies.extend(
                (module, rel, call)
                for call in _module_policy_calls(tree)
                if isinstance(call.func, ast.Attribute) and call.func.attr == "public"
            )

    violations: list[ArchViolation] = []
    for module, rel, call in public_policies:
        if module in mutating_modules:
            violations.append(
                ArchViolation(
                    "public_modules_are_read_only",
                    rel,
                    call.lineno,
                    f"module {module!r} is public (Policy.public) but exposes a mutating "
                    "route; an unauthenticated write is almost always a mistake. Gate the "
                    "writes behind a Policy with a write role, or justify a deliberate "
                    "public write with `# arch-allow-public-modules-are-read-only: <reason>`",
                )
            )
    return violations



_REGISTRY_MODULE = "control_plane.permissions"


def _registry_declared_names(registry: pathlib.Path) -> frozenset[str]:
    """The authority names ``control_plane/permissions.py`` declares at top level.

    Simple assignments (``BILLING_READ = Permission(...)``), annotated assignments,
    and names imported into the registry (e.g. the kernel's ``VIEWER``) all count —
    the registry is the single place an app's authority vocabulary is spelled out.
    """
    tree = parse(registry)
    declared: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    declared.add(target.id)
                elif isinstance(target, ast.Tuple | ast.List):
                    declared.update(
                        element.id for element in target.elts if isinstance(element, ast.Name)
                    )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            declared.add(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            declared.update(alias.asname or alias.name for alias in node.names)
    return frozenset(declared)


def _dotted(node: ast.expr) -> str | None:
    """Flatten a ``Name`` / dotted ``Attribute`` expression to ``a.b.c``, else ``None``."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _registry_bindings(tree: ast.Module) -> tuple[frozenset[str], dict[str, str]]:
    """How a file names the registry: (module-alias prefixes, member-name map).

    ``from control_plane import permissions as perms`` yields the prefix ``perms``;
    ``import control_plane.permissions`` yields ``control_plane.permissions``;
    ``from control_plane.permissions import BILLING_READ as CAN_READ`` maps the local
    name ``CAN_READ`` to the registry member ``BILLING_READ``.
    """
    prefixes: set[str] = set()
    members: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _REGISTRY_MODULE:
                    prefixes.add(alias.asname or _REGISTRY_MODULE)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            if node.module == "control_plane":
                for alias in node.names:
                    if alias.name == "permissions":
                        prefixes.add(alias.asname or "permissions")
            elif node.module == _REGISTRY_MODULE:
                for alias in node.names:
                    members[alias.asname or alias.name] = alias.name
    return frozenset(prefixes), members


def _authority_references(tree: ast.Module) -> list[ast.expr]:
    """Every typed-authority expression cited in *tree*.

    Covers ``Policy(read=... / write=...)`` keywords and the first argument of
    ``require_permission(...)`` — the same authority seams
    ``no_adhoc_permission_literals`` guards against bare strings.
    """
    references: list[ast.expr] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = base_name(node.func)
        if name == "Policy":
            references.extend(
                keyword.value
                for keyword in node.keywords
                if keyword.arg in _POLICY_AUTHZ_KEYWORDS
                and isinstance(keyword.value, ast.Name | ast.Attribute)
            )
        if name == "require_permission" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Name | ast.Attribute):
                references.append(first)
    return references


def check_policy_refs_resolve(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Every typed authority a ``Policy`` cites resolves in ``control_plane/permissions.py``.

    The build-time half of control-plane registry resolution: boot validation
    (``ControlPlane.validation_errors``) already refuses an undeclared authority at
    runtime; this rule catches the same drift at the gate, before the app ever boots.
    Any reference that traces to the app's authority registry — ``perms.BILLING_READ``
    via a module alias, or a name imported from ``control_plane.permissions`` — must
    name something the registry actually declares. References the scan cannot trace to
    the registry (kernel defaults such as ``Roles.EDITOR``, locally built objects) are
    left to the runtime check, so the rule stays precise, never heuristic.
    """
    root = pathlib.Path(app_root)
    registry = root.parent / "control_plane" / "permissions.py"
    declared = _registry_declared_names(registry) if registry.is_file() else None
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        prefixes, members = _registry_bindings(tree)
        if not prefixes and not members:
            continue
        if declared is None:
            violations.append(
                ArchViolation(
                    "policy_refs_resolve",
                    rel,
                    1,
                    "imports control_plane.permissions, but the app declares no "
                    "control_plane/permissions.py authority registry",
                )
            )
            continue
        for reference in _authority_references(tree):
            member: str | None = None
            if isinstance(reference, ast.Name):
                member = members.get(reference.id)
            else:
                dotted = _dotted(reference)
                if dotted is not None and "." in dotted:
                    prefix, _, attr = dotted.rpartition(".")
                    if prefix in prefixes:
                        member = attr
            if member is not None and member not in declared:
                violations.append(
                    ArchViolation(
                        "policy_refs_resolve",
                        rel,
                        reference.lineno,
                        f"authority reference {member!r} does not resolve: "
                        "control_plane/permissions.py declares no such name",
                    )
                )
    return violations
