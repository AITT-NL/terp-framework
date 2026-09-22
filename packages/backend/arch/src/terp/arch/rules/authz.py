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
    iter_route_registrations,
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


from terp.arch.rules._policy_source import (
    DEFAULT_ROLE_RANKS,
    has_mutating_route,
    methods_kwarg_has_mutation,
    module_policy_calls,
    policy_kwarg,
    static_default_rank,
)


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
    (``create_app`` -> ``validate_policy_write_tiers``) — this rule is the early-warning
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
        if has_mutating_route(tree):
            mutating_modules.add(module)
        if path.name == "module.py":
            rel = _rel(path, root)
            policies.extend((module, rel, call) for call in module_policy_calls(tree))

    violations: list[ArchViolation] = []
    for module, rel, call in policies:
        if module not in mutating_modules:
            continue
        if isinstance(call.func, ast.Attribute) and call.func.attr == "public":
            continue  # a public module is governed by public_modules_are_read_only
        write_node = policy_kwarg(call, "write", "write_role")
        read_node = policy_kwarg(call, "read", "read_role")
        at_read_floor = write_node is not None and base_name(write_node) == "VIEWER"
        write_rank = static_default_rank(write_node, absent=DEFAULT_ROLE_RANKS["EDITOR"])
        read_rank = static_default_rank(read_node, absent=DEFAULT_ROLE_RANKS["VIEWER"])
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
        if has_mutating_route(tree):
            mutating_modules.add(module)
        if path.name == "module.py":
            rel = _rel(path, root)
            public_policies.extend(
                (module, rel, call)
                for call in module_policy_calls(tree)
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


#: The safe HTTP verbs. A read is where the audit trail was silent: every write already
#: emits through the ``BaseService`` chokepoint, which is what makes that record
#: unbypassable and also what makes it mutation-only.
_SAFE_HTTP_METHODS = frozenset({"get", "head"})

#: The call that records a disclosure (ADR 0118). Matched on the attribute name so both
#: ``emit_disclosure(...)`` and ``audit.emit_disclosure(...)`` count.
_DISCLOSURE_CALL = "emit_disclosure"


def _names_a_permission_dependency(keywords: list[ast.keyword]) -> bool:
    """True when a route registration hangs ``require_permission(...)`` on itself.

    The marker of a read somebody decided a tier could not express: the module Policy
    already asked "may this person read here?", and the route asks for a named grant on
    top of it.
    """
    for keyword in keywords:
        if keyword.arg != "dependencies":
            continue
        for node in ast.walk(keyword.value):
            if isinstance(node, ast.Call) and base_name(node.func) == "require_permission":
                return True
    return False


def _signature_names_a_permission_dependency(
    handler: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """The other spelling: the marker declared in the endpoint's own signature.

    ``terp.core.routing.route_permission_names`` walks the resolved dependency tree at
    runtime for exactly this reason -- reading only ``dependencies=`` missed a parameter
    annotated with the requirement, and the route's authority was then reported as the
    tier alone.
    """
    for argument in (*handler.args.args, *handler.args.kwonlyargs, *handler.args.posonlyargs):
        for node in ast.walk(argument.annotation) if argument.annotation else ():
            if isinstance(node, ast.Call) and base_name(node.func) == "require_permission":
                return True
    for default in (*handler.args.defaults, *handler.args.kw_defaults):
        for node in ast.walk(default) if default is not None else ():
            if isinstance(node, ast.Call) and base_name(node.func) == "require_permission":
                return True
    return False


def _calls_emit_disclosure(handler: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(handler):
        if isinstance(node, ast.Call) and base_name(node.func) == _DISCLOSURE_CALL:
            return True
    return False


def check_permission_gated_reads_disclose(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A read behind a named grant records that it happened.

    The audit trail is emitted from the ``BaseService`` write chokepoint. That is what
    makes it unbypassable, and it is also what makes it **mutation-only**: nothing
    anywhere records a read. The trail answers "who changed what" and never "who looked",
    and looking is the whole of the harm for a connection profile, a salary, a case file
    or any other listing an application holds.

    ADR 0118 supplied the seam -- :func:`terp.core.emit_disclosure`, which opens its own
    session (a read has no unit of work to ride), clears the read-only request flag, and
    emits *before* the data is handed over so the record is the precondition of the
    disclosure rather than a report on it. What it did not supply is any reason for a
    route to call it, and nothing in the platform did.

    **Which reads, then?** Not all of them: a record per read of everything is noise that
    buries the one entry somebody will eventually need. The signal is already in the
    source, written by the author: a route that carries ``require_permission(...)`` is one
    where somebody decided the module's role tier could not express the decision -- "any
    editor may read here" was not good enough, so this route asks for a named grant. That
    is the platform's own marker for *sensitive*, and it is the one this rule reads.

    Both spellings of the marker count (``dependencies=[Depends(require_permission(...))]``
    and the requirement declared in the endpoint signature), because a rule that saw only
    the first would be blind to exactly the form the runtime projection had to be fixed to
    notice.

    The escape hatch is a justified ``# arch-allow-permission-gated-reads-disclose:
    <reason>`` marker, ratcheted by the escape-hatch budget. It is a real exception -- a
    grant that gates an action rather than a disclosure (a route that *starts* something
    and returns only an acknowledgement) reads no protected data and has nothing to
    record.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        if _module_under(path, package) is None:
            continue
        tree = parse(path)
        rel = _rel(path, root)
        for registration in iter_route_registrations(tree):
            handler = registration.handler
            if handler is None or registration.verb not in _SAFE_HTTP_METHODS:
                continue
            gated = _names_a_permission_dependency(
                list(registration.keywords)
            ) or _signature_names_a_permission_dependency(handler)
            if not gated or _calls_emit_disclosure(handler):
                continue
            violations.append(
                ArchViolation(
                    "permission_gated_reads_disclose",
                    rel,
                    registration.lineno,
                    f"{handler.name!r} is a read gated by a named permission and records "
                    "nothing when it answers; a grant is how this application says the "
                    "data is sensitive, and the audit trail then says who changed it and "
                    "never who read it -- call emit_disclosure(target_type=..., "
                    "target_id=...) before returning the data",
                )
            )
    return violations


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
