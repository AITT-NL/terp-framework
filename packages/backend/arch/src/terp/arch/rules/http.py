"""HTTP / app-composition rules: response models out, no hand-rolled app or middleware.

``create_app`` owns composition (deny-by-default guards, the error envelope,
the central middleware stack + logging); routes declare a ``response_model`` so
no bare ORM/data leaves the boundary.
"""

from __future__ import annotations

import ast
import pathlib
import re

from terp.arch._ast import base_name, iter_python_files, parse
from terp.arch.rules._support import (
    ArchViolation,
    _HTTP_METHODS,
    _is_table_model_class,
    _rel,
)

# HTTP status codes whose responses carry no body (RFC 9110); a route returning
# one of these legitimately has no ``response_model`` to declare.
_NO_BODY_STATUS_CODES: frozenset[int] = frozenset({204, 205, 304})

# The same no-body codes named symbolically -- ``fastapi.status`` / ``http.HTTPStatus``
# members (or a local constant of the same conventional name) -- so
# ``status_code=status.HTTP_204_NO_CONTENT`` is recognized, not only a bare literal.
_NO_BODY_STATUS_NAMES: frozenset[str] = frozenset(
    {
        "HTTP_204_NO_CONTENT",
        "HTTP_205_RESET_CONTENT",
        "HTTP_304_NOT_MODIFIED",
        "NO_CONTENT",
        "RESET_CONTENT",
        "NOT_MODIFIED",
    }
)


def _is_no_body_status(value: ast.expr) -> bool:
    """True when *value* is a no-body status (204/205/304), as a literal or a
    conventional named constant (``status.HTTP_204_NO_CONTENT``, ``NO_CONTENT``)."""
    if isinstance(value, ast.Constant):
        return value.value in _NO_BODY_STATUS_CODES
    if isinstance(value, ast.Attribute):
        return value.attr in _NO_BODY_STATUS_NAMES
    if isinstance(value, ast.Name):
        return value.id in _NO_BODY_STATUS_NAMES
    return False


def _route_declares_response(keywords: list[ast.keyword]) -> tuple[bool, bool]:
    """``(has_response_model, has_no_body_status)`` for a route call's keywords."""
    has_response_model = any(keyword.arg == "response_model" for keyword in keywords)
    no_body_status = any(
        keyword.arg == "status_code" and _is_no_body_status(keyword.value)
        for keyword in keywords
    )
    return has_response_model, no_body_status


def check_routes_declare_response_model(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Every content route declares ``response_model=`` (no bare ORM/data out).

    Covers both decorator routes (``@router.get(...)``) and imperative registration
    (``router.add_api_route(...)``): a route with neither a ``response_model`` nor a
    no-body ``status_code`` (204/205/304) can serialize a bare ORM object out of the
    boundary, so both forms are checked.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call):
                        continue
                    func = decorator.func
                    if not isinstance(func, ast.Attribute) or func.attr not in _HTTP_METHODS:
                        continue
                    has_response_model, no_body_status = _route_declares_response(
                        decorator.keywords
                    )
                    if not has_response_model and not no_body_status:
                        violations.append(
                            ArchViolation(
                                "routes_declare_response_model",
                                rel,
                                decorator.lineno,
                                f"route {node.name!r} declares no response_model and is not a "
                                "no-body status (204/205/304); a bare ORM/data object must not "
                                "leave the API boundary -- declare response_model= or set a "
                                "no-body status_code",
                            )
                        )
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_api_route"
            ):
                has_response_model, no_body_status = _route_declares_response(node.keywords)
                if not has_response_model and not no_body_status:
                    path_arg = (
                        node.args[0].value
                        if node.args and isinstance(node.args[0], ast.Constant)
                        else "<route>"
                    )
                    violations.append(
                        ArchViolation(
                            "routes_declare_response_model",
                            rel,
                            node.lineno,
                            f"imperative route {path_arg!r} (add_api_route) declares no "
                            "response_model and is not a no-body status (204/205/304); a bare "
                            "ORM/data object must not leave the API boundary -- declare "
                            "response_model= or set a no-body status_code",
                        )
                    )
    return violations


def _referenced_type_names(expr: ast.expr) -> set[str]:
    """Every identifier in a type expression (``Name`` ids + ``Attribute`` attrs).

    ``Page[User]`` -> ``{"Page", "User"}``; ``list[models.User]`` ->
    ``{"list", "models", "User"}`` -- so a table model named anywhere inside a
    generic ``response_model`` is seen, not only a bare top-level reference.
    """
    names: set[str] = set()
    for node in ast.walk(expr):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def check_response_model_not_table_model(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A route's ``response_model`` is a read DTO, never a ``table=True`` ORM model.

    :func:`check_routes_declare_response_model` proves a model is *declared*; this
    rule proves it is not the persisted table itself. A ``response_model`` set to a
    ``table=True`` model -- directly or wrapped in ``Page[...]`` / ``list[...]`` --
    serializes the ORM row, so a column such as ``hashed_password`` leaks straight
    through the boundary (the ``Page[User]`` footgun). Return a ``*Read`` schema
    (:class:`terp.core.BaseSchema`) listing exactly the safe fields instead.

    Table models are found by scanning the same tree for ``table=True`` classes, so
    the rule needs no import resolution; the fail-closed runtime layer
    (``terp.core.create_app``) additionally rejects a table model reached across
    packages, where a static scan cannot follow the symbol.
    """
    root = pathlib.Path(app_root)
    parsed = [(_rel(path, root), parse(path)) for path in iter_python_files(root)]
    table_models = {
        node.name
        for _, tree in parsed
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and _is_table_model_class(node)
    }
    violations: list[ArchViolation] = []
    for rel, tree in parsed:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and base_name(node.func) == "build_crud_router":
                for keyword in node.keywords:
                    if keyword.arg != "read_schema":
                        continue
                    for name in sorted(_referenced_type_names(keyword.value) & table_models):
                        violations.append(
                            ArchViolation(
                                "response_model_not_table_model",
                                rel,
                                node.lineno,
                                f"build_crud_router(read_schema={name!r}) exposes the table "
                                f"model {name!r}; a persisted model serializes every column "
                                "(e.g. a password hash) -- pass a *Read DTO "
                                "(terp.core.BaseSchema) as read_schema instead",
                            )
                        )
                continue
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if not isinstance(func, ast.Attribute) or func.attr not in _HTTP_METHODS:
                    continue
                for keyword in decorator.keywords:
                    if keyword.arg != "response_model":
                        continue
                    for name in sorted(_referenced_type_names(keyword.value) & table_models):
                        violations.append(
                            ArchViolation(
                                "response_model_not_table_model",
                                rel,
                                decorator.lineno,
                                f"route {node.name!r} exposes the table model {name!r} as its "
                                "response_model (directly or via Page[...]/list[...]); a "
                                "persisted model serializes every column (e.g. a password "
                                "hash) -- return a *Read DTO (terp.core.BaseSchema) instead",
                            )
                        )
    return violations


# Bare collection annotations a ``response_model`` must not use unpaginated: a list
# route returns a capped ``Page[T]``, never an unbounded ``list[...]`` (ADR 0006).
_COLLECTION_RESPONSE_TYPES: frozenset[str] = frozenset(
    {"list", "List", "Sequence", "Iterable", "Collection", "tuple", "set", "frozenset"}
)


def _is_unpaginated_collection(value: ast.expr) -> bool:
    """True for a bare collection ``response_model`` (``list`` / ``list[...]``), not ``Page[...]``."""
    if isinstance(value, ast.Subscript):
        return base_name(value.value) in _COLLECTION_RESPONSE_TYPES
    return base_name(value) in _COLLECTION_RESPONSE_TYPES


def _is_route_decorator(func: ast.expr) -> bool:
    """True for the route decorator forms this rule owns (method shortcuts + api_route)."""
    return isinstance(func, ast.Attribute) and (
        func.attr in _HTTP_METHODS or func.attr == "api_route"
    )


def check_list_routes_paginate(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A list route returns a capped ``Page[T]``, never a bare ``list[...]``.

    Pagination is a mandatory cross-cutting control (ADR 0006, Tier A): a route whose
    ``response_model`` is a bare ``list[...]`` / ``Sequence[...]`` serializes an
    **unbounded** collection -- a resource-exhaustion and over-exposure footgun on a
    large table, and a ``Page[T]`` guarantee that was previously only a convention.
    Wrap the Read DTO in ``terp.core.Page[...]`` (returned via ``Page.of(...)`` with
    ``PaginationDep``) so every list is capped and uniformly shaped. A single-object
    ``response_model`` (``NoteRead``) is unaffected; both decorator routes and
    imperative ``add_api_route`` registration are checked.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call):
                        continue
                    func = decorator.func
                    if not _is_route_decorator(func):
                        continue
                    for keyword in decorator.keywords:
                        if keyword.arg == "response_model" and _is_unpaginated_collection(
                            keyword.value
                        ):
                            violations.append(
                                ArchViolation(
                                    "list_routes_paginate",
                                    rel,
                                    decorator.lineno,
                                    f"route {node.name!r} returns a bare collection "
                                    "response_model (an unbounded list); return a capped "
                                    "terp.core.Page[...] (with PaginationDep) so a list can "
                                    "never serialize unbounded rows",
                                )
                            )
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_api_route"
            ):
                for keyword in node.keywords:
                    if keyword.arg == "response_model" and _is_unpaginated_collection(
                        keyword.value
                    ):
                        path_arg = (
                            node.args[0].value
                            if node.args and isinstance(node.args[0], ast.Constant)
                            else "<route>"
                        )
                        violations.append(
                            ArchViolation(
                                "list_routes_paginate",
                                rel,
                                node.lineno,
                                f"imperative route {path_arg!r} (add_api_route) returns a bare "
                                "collection response_model (an unbounded list); return a capped "
                                "terp.core.Page[...] instead",
                            )
                        )
    return violations


# A path parameter naming a resource id (``id`` or ``…_id``) must be a UUID: the
# framework issues UUID v4 primary keys, and typing the path param as ``uuid.UUID``
# gives free 422 validation at the boundary instead of letting malformed ids reach
# the service layer.
_ID_PARAM_RE = re.compile(r"(?:^id$|_id$)")
_PATH_PARAM_RE = re.compile(r"\{(\w+)(?::[^}]*)?\}")


def _route_path_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """The ``{param}`` names declared in *node*'s route-decorator URL templates."""
    params: set[str] = set()
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not _is_route_decorator(decorator.func):
            continue
        if decorator.args and isinstance(decorator.args[0], ast.Constant):
            template = decorator.args[0].value
            if isinstance(template, str):
                params.update(_PATH_PARAM_RE.findall(template))
    return params


def _is_uuid_annotation(annotation: ast.expr) -> bool:
    """True when *annotation* is ``uuid.UUID`` (attribute) or ``UUID`` (name)."""
    if isinstance(annotation, ast.Attribute):
        return annotation.attr == "UUID"
    if isinstance(annotation, ast.Name):
        return annotation.id == "UUID"
    return False


def check_path_id_params_are_uuid(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A route path parameter naming a resource id must be typed as a UUID.

    A handler parameter that also appears in the route's URL template
    (``@router.get("/{note_id}")``) and is named ``id`` or ends in ``_id`` must be
    annotated ``uuid.UUID`` — the framework's primary keys are UUID v4, and the UUID
    type gives automatic boundary validation (a 422 on malformed input) instead of
    letting a bad id reach the service. Query / body parameters are out of scope —
    only path params are checked.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            path_params = _route_path_params(node)
            if not path_params:
                continue
            for arg in (*node.args.posonlyargs, *node.args.args):
                if arg.arg not in path_params or not _ID_PARAM_RE.search(arg.arg):
                    continue
                if arg.annotation is None:
                    violations.append(
                        ArchViolation(
                            "path_id_params_are_uuid",
                            rel,
                            node.lineno,
                            f"path parameter {arg.arg!r} has no type annotation; type it "
                            "as uuid.UUID for automatic boundary validation",
                        )
                    )
                elif not _is_uuid_annotation(arg.annotation):
                    violations.append(
                        ArchViolation(
                            "path_id_params_are_uuid",
                            rel,
                            node.lineno,
                            f"path parameter {arg.arg!r} is not typed as uuid.UUID; an id path "
                            "param must be a UUID so malformed input is rejected at the boundary",
                        )
                    )
    return violations


# Safe (RFC 9110) HTTP methods a route can serve; an invocation through one is
# authorized by the deny-by-default guard against the policy's *read* requirement, so
# a handler reachable via a safe method must not mutate.
_SAFE_ROUTE_METHODS = frozenset({"get", "head", "options"})
_SAFE_METHOD_NAMES = frozenset({"GET", "HEAD", "OPTIONS"})

# A mutating ``BaseService`` call a safe-reachable handler must not make. The write
# primitives (``_save`` / ``_remove``) are unambiguous; ``create`` / ``update`` /
# ``delete`` are matched only on a service-ish receiver (``self`` or a name containing
# "service") so an unrelated ``.update()`` / ``.delete()`` (a dict, a header map) is
# not flagged.
_BASESERVICE_WRITE_PRIMITIVES = frozenset({"_save", "_remove"})
_CRUD_MUTATORS = frozenset({"create", "update", "delete"})


def _call_route_methods(keywords: list[ast.keyword]) -> set[str] | None:
    """The methods an ``api_route`` / ``add_api_route`` call registers.

    A literal ``methods=[...]`` -> that upper-cased set; **no** ``methods`` keyword ->
    FastAPI's default ``{"GET"}``; a non-literal ``methods=`` (a variable) -> ``None``
    (undeterminable, so the route is left unchecked rather than guessed).
    """
    for keyword in keywords:
        if keyword.arg == "methods":
            if isinstance(keyword.value, ast.List):
                return {
                    element.value.upper()
                    for element in keyword.value.elts
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)
                }
            return None
    return {"GET"}


def _decorator_route_methods(decorator: ast.expr) -> set[str] | None:
    """The methods a route *decorator* registers, or ``None`` if it is not a route.

    ``@x.get(...)`` -> ``{"GET"}``; ``@x.api_route(...)`` -> its ``methods`` (default
    ``{"GET"}``); a non-route decorator -> ``None``.
    """
    if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)):
        return None
    attr = decorator.func.attr
    if attr in _HTTP_METHODS or attr in _SAFE_ROUTE_METHODS:
        return {attr.upper()}
    if attr == "api_route":
        return _call_route_methods(decorator.keywords)
    return None


def _serves_safe_method(methods: set[str] | None) -> bool:
    """True when *methods* includes a safe method, so the read tier authorizes it.

    Note this is an **intersection**, not a subset: a mixed ``["GET", "POST"]`` route
    is still reachable via ``GET`` at the read tier, so a mutation in its handler is a
    privilege escape on that method.
    """
    return methods is not None and bool(methods & _SAFE_METHOD_NAMES)


def _is_mutating_service_call(node: ast.AST) -> bool:
    """True for a call that persists through ``BaseService`` (``_save`` / ``_remove`` or
    a ``self`` / ``*service*`` ``create`` / ``update`` / ``delete``)."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    attr = node.func.attr
    if attr in _BASESERVICE_WRITE_PRIMITIVES:
        return True
    if attr in _CRUD_MUTATORS:
        receiver = base_name(node.func.value).lower()
        return receiver == "self" or "service" in receiver
    return False


def _safe_reachable_handlers(
    tree: ast.Module,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every route handler reachable through a safe HTTP method, decorator or imperative.

    Covers ``@router.get`` / ``@router.api_route(methods=[…])`` decorators **and**
    imperative ``router.add_api_route(path, endpoint, methods=[…])`` registration
    (resolving ``endpoint`` to its ``def`` in this module) — and a route whose methods
    *include* a safe one (a mixed ``["GET", "POST"]``), since the safe-method
    invocation runs at the read tier. Returned sorted by line for determinism.
    """
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    by_name = {node.name: node for node in functions}
    safe: set[ast.FunctionDef | ast.AsyncFunctionDef] = set()
    for node in functions:
        if any(
            _serves_safe_method(_decorator_route_methods(decorator))
            for decorator in node.decorator_list
        ):
            safe.add(node)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_api_route"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Name)
            and _serves_safe_method(_call_route_methods(node.keywords))
        ):
            endpoint = by_name.get(node.args[1].id)
            if endpoint is not None:
                safe.add(endpoint)
    return sorted(safe, key=lambda node: node.lineno)


def check_safe_methods_are_read_only(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A handler reachable via a safe HTTP method (``GET`` / ``HEAD`` / ``OPTIONS``) must not mutate.

    The deny-by-default guard derives the required role tier from the **HTTP method**:
    a safe method is authorized against the policy's *read* requirement, a
    mutating one (``POST`` / ``PUT`` / ``PATCH`` / ``DELETE``) against the *write*
    requirement. So a handler reachable through a safe method that calls a mutating
    ``BaseService`` method (``create`` / ``update`` / ``delete`` / ``_save`` /
    ``_remove``) performs a write a *read-tier* caller cleared — a privilege-tier
    escape (a viewer triggering an editor/admin write via a ``GET``). This holds for a
    mixed-method route too (``["GET", "POST"]``): the ``GET`` invocation runs at the
    read tier, so a handler that always mutates is flagged (split it, or branch on the
    method behind a ``POST``). Both decorator and imperative ``add_api_route``
    registration are checked. Put the write behind a ``POST`` / ``PUT`` / ``PATCH`` /
    ``DELETE`` route so it is authorized at the write tier. The runtime half
    (``create_app`` marks a safe-method request read-only, so the chokepoint refuses
    the write) is the paired control.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for handler in _safe_reachable_handlers(tree):
            for sub in ast.walk(handler):
                if _is_mutating_service_call(sub):
                    method = sub.func.attr  # type: ignore[attr-defined]
                    violations.append(
                        ArchViolation(
                            "safe_methods_are_read_only",
                            rel,
                            sub.lineno,
                            f"safe-method route {handler.name!r} calls the mutating service "
                            f"method {method!r}; a GET/HEAD/OPTIONS route is authorized at the "
                            "READ tier, so a write here runs below the write tier — move the "
                            "mutation behind a POST/PUT/PATCH/DELETE route",
                        )
                    )
    return violations


def check_no_app_instantiation(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """App code never constructs ``FastAPI()`` directly.

    ``terp.core.create_app`` owns app composition (deny-by-default guards, the
    control plane, the error envelope). A hand-built ``FastAPI()`` is an
    application assembled outside the framework.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and base_name(node.func) == "FastAPI":
                violations.append(
                    ArchViolation(
                        "no_app_instantiation",
                        rel,
                        node.lineno,
                        "app code constructs FastAPI() directly; compose the app via "
                        "terp.core.create_app so framework guards are not bypassed",
                    )
                )
    return violations


def check_no_adhoc_middleware(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """App code never wires HTTP middleware itself; security is centralized.

    Cross-cutting HTTP security (headers, CORS, rate-limit, body-size, request-id)
    is declared once as a ``SecurityConfig`` and installed by ``create_app``. A
    module calling ``add_middleware(...)``, using the ``@app.middleware("http")``
    decorator, or subclassing ``BaseHTTPMiddleware`` is assembling a security
    posture outside that single control plane.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and base_name(node.func) == "add_middleware":
                violations.append(
                    ArchViolation(
                        "no_adhoc_middleware",
                        rel,
                        node.lineno,
                        "app code calls add_middleware(); cross-cutting security is declared "
                        "once in SecurityConfig and any other middleware is passed to "
                        "create_app(middleware=[...]) -- both installed centrally by create_app",
                    )
                )
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "middleware"
            ):
                violations.append(
                    ArchViolation(
                        "no_adhoc_middleware",
                        rel,
                        node.lineno,
                        "app code registers HTTP middleware via @app.middleware(...); "
                        "cross-cutting security is centralized in SecurityConfig",
                    )
                )
            elif isinstance(node, ast.ClassDef) and "BaseHTTPMiddleware" in {
                base_name(base) for base in node.bases
            }:
                violations.append(
                    ArchViolation(
                        "no_adhoc_middleware",
                        rel,
                        node.lineno,
                        f"class {node.name!r} subclasses BaseHTTPMiddleware; cross-cutting "
                        "HTTP security is centralized in SecurityConfig, not hand-rolled",
                    )
                )
    return violations


# App-level registration APIs with no legitimate app-code use: each one puts HTTP
# surface on the app OUTSIDE the per-module deny-by-default guard `create_app`
# injects at mount time (a mounted sub-app or raw route is served unguarded).
_RAW_APP_SURFACE_ATTRS = frozenset(
    {"mount", "include_router", "add_route", "add_websocket_route"}
)

# Route registrations that are legitimate on a module's APIRouter but never on the
# composed app object: verb decorators plus the generic/imperative spellings, and
# the lifecycle hooks (ungated executable registration on the app).
_APP_ROUTE_ATTRS = _HTTP_METHODS | frozenset(
    {
        "head",
        "options",
        "trace",
        "route",
        "api_route",
        "add_api_route",
        "websocket",
        "websocket_route",
        "on_event",
        "add_event_handler",
    }
)


def _create_app_names(tree: ast.Module) -> set[str]:
    """Names in *tree* that resolve to ``terp.core.create_app``."""
    names = {"create_app"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module not in {"terp.core", "terp.core.app"}:
            continue
        for alias in node.names:
            if alias.name == "create_app":
                names.add(alias.asname or alias.name)
    return names


def _call_is_create_app(call: ast.Call, names: set[str]) -> bool:
    """True when *call* invokes a known spelling of ``create_app``."""
    callee = base_name(call.func)
    return callee == "create_app" or (callee is not None and callee in names)


def _assign_targets(node: ast.Assign | ast.AnnAssign) -> tuple[ast.expr, ...]:
    return tuple(node.targets) if isinstance(node, ast.Assign) else (node.target,)


def _assigned_names_from_create_app(
    nodes: list[ast.stmt], create_names: set[str]
) -> set[str]:
    """Local names assigned from ``create_app(...)`` within a block."""
    names: set[str] = set()
    for node in ast.walk(ast.Module(body=nodes, type_ignores=[])):
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        value = node.value
        if not isinstance(value, ast.Call) or not _call_is_create_app(value, create_names):
            continue
        for target in _assign_targets(node):
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _composed_app_names(tree: ast.Module) -> set[str]:
    """Names in *tree* bound to a composed app.

    Two spellings cover the canonical composition root: a name assigned straight
    from ``create_app(...)``, and a name assigned from calling a local zero-arg
    factory whose body returns ``create_app(...)`` (``app = build()``).
    """
    create_names = _create_app_names(tree)
    factories: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            local_app_names = _assigned_names_from_create_app(node.body, create_names)
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Return)
                    and isinstance(inner.value, ast.Call)
                    and _call_is_create_app(inner.value, create_names)
                ):
                    factories.add(node.name)
                elif (
                    isinstance(inner, ast.Return)
                    and isinstance(inner.value, ast.Name)
                    and inner.value.id in local_app_names
                ):
                    factories.add(node.name)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        callee = base_name(value.func)
        if _call_is_create_app(value, create_names) or callee in factories:
            for target in _assign_targets(node):
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _receiver_root_name(node: ast.expr) -> str | None:
    """The root name of a receiver chain (``app.router`` -> ``app``)."""
    current = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def check_no_raw_app_routes(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """App code never registers HTTP surface on the composed app object.

    ``create_app`` mounts every module router behind the deny-by-default policy
    guard; a route registered on the app itself bypasses that guard (served with
    no authentication or role check) and is invisible to the module permission
    model (``terp inspect access`` can only alarm on it, not attribute it). Two
    shapes are caught: the app-level registration APIs that have no legitimate
    app-code use at all (``mount`` / ``include_router`` / ``add_route`` /
    ``add_websocket_route`` — modules declare ONE flat router; composition mounts
    it), and any route registration (``@app.get`` / ``app.add_api_route`` / …)
    whose receiver is bound from ``create_app(...)`` or from a local factory
    returning it (``app = build()``).
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        app_names = _composed_app_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            attr = node.func.attr
            if attr in _RAW_APP_SURFACE_ATTRS:
                violations.append(
                    ArchViolation(
                        "no_raw_app_routes",
                        rel,
                        node.lineno,
                        f"app code calls .{attr}(...); HTTP surface belongs on a module's "
                        "single flat router, mounted by create_app behind the deny-by-default "
                        "guard -- surface registered on the app itself is served unguarded",
                    )
                )
            elif (
                attr in _APP_ROUTE_ATTRS
                and _receiver_root_name(node.func.value) in app_names
            ):
                receiver = _receiver_root_name(node.func.value) or "app"
                violations.append(
                    ArchViolation(
                        "no_raw_app_routes",
                        rel,
                        node.lineno,
                        f"route registered on the composed app ({receiver}.{attr}); "
                        "it bypasses the module policy guard (no authentication, no role "
                        "check) -- declare it on a module router instead",
                    )
                )
    return violations


def check_no_dependency_overrides(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """App code never touches ``dependency_overrides``.

    ``create_app`` binds the authentication and session seams once, at composition.
    Rebinding ``app.dependency_overrides`` in app code (e.g. replacing the principal
    provider) silently disables authentication or swaps the session outside every
    guard. Overrides are a TEST-ONLY seam (the arch scan skips ``tests/``); app code
    has no legitimate use.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "dependency_overrides":
                violations.append(
                    ArchViolation(
                        "no_dependency_overrides",
                        rel,
                        node.lineno,
                        "app code touches dependency_overrides; the principal/session "
                        "seams are bound once by create_app (overrides are test-only "
                        "-- rebinding them here silently bypasses authentication)",
                    )
                )
    return violations


def check_no_adhoc_logging_config(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """App code never configures logging globally; redaction is centralized.

    Structured logging + PII redaction is installed once by ``configure_logging``
    (called by ``create_app``). A module calling ``logging.basicConfig`` /
    ``dictConfig`` / ``fileConfig`` re-points logging and can silently bypass the
    central secret-redaction filter.
    """
    root = pathlib.Path(app_root)
    config_calls = frozenset({"basicConfig", "dictConfig", "fileConfig"})
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and base_name(node.func) in config_calls:
                violations.append(
                    ArchViolation(
                        "no_adhoc_logging_config",
                        rel,
                        node.lineno,
                        "app code configures logging globally; structured logging + PII "
                        "redaction is centralized via terp.core (configure_logging)",
                    )
                )
    return violations
