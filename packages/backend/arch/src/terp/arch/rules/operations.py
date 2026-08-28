"""Operation rules: a route's declared operation is a typed catalog constant,
declared once coverage requires one (ADR 0102, terp-spec 0.29.0).

Two rules, sharing one runtime enforcement seam
(``terp.core.app._validate_declared_operations``) exactly the way the event bus's
no-drift rule and this pair are modelled on it:

* ``operations_reference_catalog`` -- the no-drift half, unconditional: an
  operation named anywhere (the ``operation(...)`` route-level marker, or a
  canonical CRUD factory's ``*_operation=`` keywords) must be a typed
  ``OperationDefinition`` constant, never a bare string or a value built inline
  at the call site.
* ``routes_declare_operation`` -- the coverage half, conditional on the app's own
  choice: every route declares an operation once the app's ``OperationCatalog``
  opts into ``OperationCoverage.STRICT``. An app that has not made that choice is
  unaffected -- this rule stays silent, matching the "optional feature,
  unconditional guarantee once used" split the no-drift half already has.
"""

from __future__ import annotations

import ast
import pathlib

from terp.arch._ast import base_name, iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _rel, iter_route_registrations

#: The ``build_crud_router(...)`` keywords carrying an operation, in the same
#: order the factory builds its five routes -- kept as a mapping (not a bare
#: set) so a violation can name which of the five routes is missing one.
_CRUD_OPERATION_KEYWORDS: dict[str, str] = {
    "list_operation": "the list route",
    "create_operation": "the create route",
    "get_operation": "the get route",
    "update_operation": "the update route",
    "delete_operation": "the delete route",
}


def _operation_ref_violation(value: ast.expr, rel: str, where: str) -> ArchViolation | None:
    """Flag an operation reference that is a bare value, not a typed catalog constant.

    A typed reference (a ``Name`` / ``Attribute`` pointing at a declared catalog
    constant) is allowed; ``None`` is allowed (the factory's "no operation for
    this route" default); anything else -- a bare string or an inline
    ``OperationDefinition(...)`` -- would let an operation drift in as a literal,
    the same failure mode ``events_reference_catalog`` polices for the event bus.
    """
    if isinstance(value, ast.Constant):
        if value.value is None:
            return None
        what = "a string literal" if isinstance(value.value, str) else "a literal"
    elif isinstance(value, ast.Call):
        what = "an inline OperationDefinition(...)"
    else:
        return None
    return ArchViolation(
        "operations_reference_catalog",
        rel,
        value.lineno,
        f"{where} must reference a typed OperationDefinition constant from the "
        f"control-plane operations catalog, not {what}",
    )


def check_operations_reference_catalog(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A route's declared operation is a typed catalog constant, never a bare value.

    Catches two call sites: the ``operation(...)`` route-level marker (its single
    positional argument), and a canonical CRUD factory's five ``*_operation=``
    keywords. A route that declares no operation at all is not this rule's
    concern -- that is ``routes_declare_operation``'s question, not this one's.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = base_name(node.func)
            candidates: list[tuple[ast.expr, str]] = []
            if name == "operation":
                # `operation(definition: OperationDefinition)` has one parameter,
                # callable positionally (the documented, universal spelling in this
                # codebase) or by its keyword name -- both must be checked, or the
                # keyword form drifts in undetected.
                if node.args:
                    candidates.append((node.args[0], "operation(...)"))
                else:
                    candidates += [
                        (keyword.value, "operation(definition=...)")
                        for keyword in node.keywords
                        if keyword.arg == "definition"
                    ]
            elif name == "build_crud_router":
                candidates += [
                    (keyword.value, f"build_crud_router({keyword.arg}=...)")
                    for keyword in node.keywords
                    if keyword.arg in _CRUD_OPERATION_KEYWORDS
                ]
            for value, where in candidates:
                violation = _operation_ref_violation(value, rel, where)
                if violation is not None:
                    violations.append(violation)
    return violations


def _coverage_is_strict(app_root: pathlib.Path) -> bool:
    """Statically detect an ``OperationCatalog(coverage=OperationCoverage.STRICT)``.

    Real apps declare their operations catalog in a sibling ``control_plane/``
    (the same convention ``policy_refs_resolve`` uses for the permissions
    registry), reached via ``app_root.parent`` -- so that is checked first, and a
    real app's own scan usually never needs to fall through to ``app_root`` at
    all. The scan also covers ``app_root`` itself: the Standard's own corpus can
    only place files inside the tree it copies into the scanned root, never as a
    true sibling, so a corpus case declares its catalog inside that tree instead.

    This is a syntactic match, not a resolved reference: it recognizes
    ``coverage=OperationCoverage.STRICT`` (or a bare ``coverage=STRICT`` given an
    aliased import) written directly at the call site, the spelling this
    codebase's own control-plane modules use throughout. It does not follow a
    value assigned to an intermediate variable, and it does not check that the
    matched ``OperationCatalog(...)`` is the one actually mounted on a
    ``ControlPlane`` -- so it is a best-effort static signal, paired with (never
    a substitute for) the runtime ``_validate_declared_operations`` boot check,
    which resolves the real, mounted catalog and enforces coverage unconditionally.
    """
    control_plane = app_root.parent / "control_plane"
    roots = [control_plane, app_root] if control_plane.is_dir() else [app_root]
    for root in roots:
        for path in iter_python_files(root):
            tree = parse(path)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and base_name(node.func) == "OperationCatalog"):
                    continue
                for keyword in node.keywords:
                    if keyword.arg == "coverage" and base_name(keyword.value) == "STRICT":
                        return True
    return False


def _declares_operation(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Is *node* decorated with ``terp.core.routing.operation(...)``?

    Matched on the decorator's final name, mirroring ``_declares_read_only`` in
    ``http.py``: the import spelling is the module author's business.
    """
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        target = decorator.func
        if isinstance(target, ast.Name) and target.id == "operation":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "operation":
            return True
    return False


def _crud_router_missing_operations(node: ast.Call) -> list[str]:
    """Which of the five ``build_crud_router(...)`` routes declare no operation.

    A keyword absent entirely and a keyword explicitly set to ``None`` are the
    same thing to the factory (both default to "no operation for this route"),
    so both count as missing here.
    """
    present: dict[str, ast.expr] = {
        keyword.arg: keyword.value
        for keyword in node.keywords
        if keyword.arg in _CRUD_OPERATION_KEYWORDS
    }
    return [
        label
        for keyword_name, label in _CRUD_OPERATION_KEYWORDS.items()
        if keyword_name not in present
        or (isinstance(present[keyword_name], ast.Constant) and present[keyword_name].value is None)
    ]


def check_routes_declare_operation(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Every route declares the operation it performs, once coverage is strict.

    The app's own choice, exactly as the runtime half (``create_app`` ->
    ``_validate_declared_operations``) treats it: an app whose operations catalog
    has not opted into ``OperationCoverage.STRICT`` is unaffected, so this rule
    silently returns no violations rather than requiring every route to be
    annotated the moment the helper exists. Both the decorator / imperative
    route forms (via :func:`iter_route_registrations`) and the canonical CRUD
    factory's five generated routes are covered.
    """
    root = pathlib.Path(app_root)
    if not _coverage_is_strict(root):
        return []
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        for route in iter_route_registrations(tree):
            handler = route.handler
            if handler is None and route.endpoint_name is not None:
                handler = functions.get(route.endpoint_name)
            if handler is None:
                # An imperative endpoint that is not a plain name cannot be
                # followed to a signature -- skipped rather than guessed at,
                # the same fail-open precedent path_id_params_are_uuid sets.
                continue
            if _declares_operation(handler):
                continue
            violations.append(
                ArchViolation(
                    "routes_declare_operation",
                    rel,
                    route.lineno,
                    f"route {route.label!r} declares no operation, and this app's "
                    "operations catalog is set to strict coverage; declare one "
                    "with terp.core.operation(...), or relax coverage to warn "
                    "while it is being annotated",
                )
            )
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and base_name(node.func) == "build_crud_router"):
                continue
            for missing in _crud_router_missing_operations(node):
                violations.append(
                    ArchViolation(
                        "routes_declare_operation",
                        rel,
                        node.lineno,
                        f"build_crud_router(...) declares no operation for {missing}, "
                        "and this app's operations catalog is set to strict coverage; "
                        "pass the matching *_operation= keyword",
                    )
                )
    return violations


__all__ = [
    "check_operations_reference_catalog",
    "check_routes_declare_operation",
]
