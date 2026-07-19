"""Model-trait rules: scope + provenance are applied centrally, never by hand.

Soft-delete / tenant scoping (``base_query``) and actor-stamping (``_save``) are
auto-honored from model traits, so a module must not hand-write the managed scope
columns or set the actor stamps; a tenant-scoped model's service must be scoped.
"""

from __future__ import annotations

import ast
import pathlib

from terp.arch._ast import base_name, iter_python_files, parse
from terp.arch.rules._support import (
    ArchViolation,
    _MANAGED_ACTOR_COLUMNS,
    _MANAGED_OWNERSHIP_COLUMNS,
    _MANAGED_SCOPE_COLUMNS,
    _is_table_model_class,
    _module_under,
    _rel,
    _service_model,
)


def check_tenant_scoped_models_use_scoped_service(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A ``TenantScopedMixin`` model's service must extend ``TenantScopedService``.

    This makes tenant isolation structural on the **write** side: reads of a
    tenant-scoped model are already filtered centrally by the registered tenant
    scope predicate (ADR 0017), but ``TenantScopedService`` is what stamps
    ``tenant_id`` on create — so a plain ``BaseService`` (which would insert an
    unstamped, never-visible row) is rejected at build time.
    """
    root = pathlib.Path(app_root)
    trees = {path: parse(path) for path in iter_python_files(root)}

    scoped_models: set[str] = set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if "TenantScopedMixin" in {base_name(base) for base in node.bases}:
                    scoped_models.add(node.name)

    violations: list[ArchViolation] = []
    for path, tree in trees.items():
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {base_name(base) for base in node.bases}
            if not ({"BaseService", "TenantScopedService"} & bases):
                continue
            model = _service_model(node)
            if model in scoped_models and "TenantScopedService" not in bases:
                violations.append(
                    ArchViolation(
                        "tenant_scoped_models_use_scoped_service",
                        rel,
                        node.lineno,
                        f"service {node.name!r} binds tenant-scoped model {model!r} but "
                        "does not extend TenantScopedService; reads would bypass tenant isolation",
                    )
                )
    return violations


def check_no_manual_scope_filtering(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Modules never touch framework-managed scope columns (``deleted_at`` / ``tenant_id``).

    Soft-delete and tenant scoping are applied **centrally**: ``BaseService.base_query``
    filters ``deleted_at IS NULL`` for a soft-delete model and applies every registered
    row predicate (e.g. the tenant filter) for a scoped one, and the audited ``delete``
    chokepoint stamps ``deleted_at``. A module
    that references ``<x>.deleted_at`` / ``<x>.tenant_id`` — to filter, set, or compare —
    is re-implementing that scope predicate by hand, which can leak or destroy scoped
    rows. The framework's ``base_query`` is the only path; expose the column in a read
    DTO if you must surface it, but never filter or assign it in module code.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in _MANAGED_SCOPE_COLUMNS:
                violations.append(
                    ArchViolation(
                        "no_manual_scope_filtering",
                        rel,
                        node.lineno,
                        f"module references the framework-managed scope column "
                        f"{node.attr!r}; soft-delete / tenant scoping is applied centrally "
                        "by BaseService.base_query — do not filter, set, or compare it by hand",
                    )
                )
    return violations


def check_no_manual_actor_stamping(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Modules never set the framework-managed actor-stamp columns by hand.

    Who created and last modified a row is **provenance**, applied **centrally**:
    ``BaseService._save`` fills ``created_by_id`` (on insert) and ``modified_by_id``
    (on every write) from the request actor (:class:`~terp.core.ActorStampedMixin`,
    ADR 0012). A module that assigns ``<x>.created_by_id`` / ``<x>.modified_by_id``
    is forging or clobbering that trail — the actor must come from the authenticated
    request, never from caller-supplied data. As with the scope columns, a read DTO
    may still *expose* the column (an annotation is fine); only attribute access
    (set / compare) is policed.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in _MANAGED_ACTOR_COLUMNS:
                violations.append(
                    ArchViolation(
                        "no_manual_actor_stamping",
                        rel,
                        node.lineno,
                        f"module references the framework-managed actor-stamp column "
                        f"{node.attr!r}; created_by_id / modified_by_id are filled centrally "
                        "by BaseService from the request actor — do not set or compare them by hand",
                    )
                )
    return violations


def check_no_manual_ownership_checks(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Modules keep ownership structural and never gate ``owner_id`` by hand.

    Object-level authorization is applied **centrally**: ``BaseService`` stamps
    ``owner_id`` from the request actor on create and authorizes every update / delete
    of an owned row at the write chokepoint (a non-owner write fails closed with 403,
    ADR 0029). A module that references ``<x>.owner_id`` — to compare it against a
    principal, filter on it, or set it — is hand-rolling that per-row check, the
    easy-to-get-wrong pattern (it leaks if forgotten, and a hand-written
    ``select(...).where(owner_id == ...)`` also drops the soft-delete / tenant row
    scope) the seam replaces. Declare :class:`~terp.core.OwnedMixin` on the model and
    let the framework gate the write; register an object-authz predicate (ADR 0029)
    for a richer policy. As with the scope / actor columns, a read DTO may still
    *expose* ``owner_id`` (an annotation is fine); only attribute access (set / filter
    / compare) is policed.
    """
    root = pathlib.Path(app_root)
    trees = {path: parse(path) for path in iter_python_files(root)}
    violations: list[ArchViolation] = []

    owned_models: set[tuple[str, str]] = set()
    service_models: dict[tuple[str, str], tuple[str, str, int]] = {}
    for path, tree in trees.items():
        module_name = _module_under(path, package)
        if module_name is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {base_name(base) for base in node.bases}
            if "OwnedMixin" in bases:
                owned_models.add((module_name, node.name))
            model = _service_model(node)
            if model is not None:
                service_models[(module_name, node.name)] = (
                    model,
                    _rel(path, root),
                    node.lineno,
                )

    job_modules: set[str] = set()
    for path, tree in trees.items():
        module_name = _module_under(path, package)
        if module_name is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or base_name(node.func) != "ModuleSpec":
                continue
            jobs = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "jobs"),
                None,
            )
            if isinstance(jobs, ast.List | ast.Tuple) and jobs.elts:
                job_modules.add(module_name)

    for path, tree in trees.items():
        rel = _rel(path, root)
        module_name = _module_under(path, package)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in _MANAGED_OWNERSHIP_COLUMNS:
                violations.append(
                    ArchViolation(
                        "no_manual_ownership_checks",
                        rel,
                        node.lineno,
                        f"module references the framework-managed ownership column "
                        f"{node.attr!r}; per-row write authorization is applied centrally by "
                        "BaseService for an OwnedMixin model (ADR 0029) — do not compare, "
                        "filter, or set it by hand. Declare OwnedMixin and register an "
                        "object-authz predicate for a richer policy",
                    )
                )
    for (module_name, service_name), (model_name, rel, line) in service_models.items():
        if module_name not in job_modules or (module_name, model_name) in owned_models:
            continue
        violations.append(
            ArchViolation(
                "no_manual_ownership_checks",
                rel,
                line,
                f"module declares background jobs while service "
                f"{service_name!r} binds model {model_name!r} without "
                "OwnedMixin; a system actor is not an ownership bypass. "
                "Compose OwnedMixin for user-owned rows and stop for a "
                "reviewed maintenance-authority capability instead of "
                "dropping the owner gate",
            )
        )
    return violations


def check_no_raw_file_references(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A table model's ``*file_id`` column is declared with ``FileRef(...)``, never bare.

    A stored pointer to a file object carries **authorization semantics**: the files
    capability serves delegated reads only through a *declared* reference
    (``FileService.load_for`` fail-closes on an undeclared column — the runtime half of
    this rule, ADR 0057). A bare ``file_id: uuid.UUID`` column on a ``table=True`` model
    is an undeclared reference: nothing ties the file's access to the referencing row,
    which is the classic object-level (BOLA) drift. Declare the column with
    ``FileRef(...)`` (from ``terp-cap-files``) so the reference is greppable, verified
    at runtime, and served through the module's own already-authorized row — never
    hand-rolled. A non-table schema (a Read DTO exposing ``file_id``) is fine and not
    policed; only the persisted column is.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not _is_table_model_class(node):
                continue
            for stmt in node.body:
                if not (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                ):
                    continue
                name = stmt.target.id
                if name != "file_id" and not name.endswith("_file_id"):
                    continue
                declared = (
                    isinstance(stmt.value, ast.Call)
                    and base_name(stmt.value.func) == "FileRef"
                )
                if not declared:
                    violations.append(
                        ArchViolation(
                            "no_raw_file_references",
                            rel,
                            stmt.lineno,
                            f"table model {node.name!r} declares the file-reference "
                            f"column {name!r} as a bare field; a stored file pointer "
                            "must be declared with FileRef(...) (terp-cap-files, ADR "
                            "0057) so delegated access is declared and served through "
                            "FileService.load_for — never an undeclared uuid column",
                        )
                    )
    return violations


def check_base_query_not_overridden(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A service never overrides ``base_query`` — add read filters via ``business_filters``.

    ``BaseService.base_query`` composes the **non-droppable** row scope (soft-delete +
    every registered capability predicate, e.g. tenancy) with the service's
    ``business_filters``. Overriding it — the old, footgun-y seam — can silently drop
    soft-delete / tenant scoping the moment the override forgets ``super().base_query()``,
    leaking soft-deleted or cross-tenant rows. Add static conditions via
    ``business_filters()`` (you return conditions, not a query, so you cannot drop scope
    and need no ``super()``); a per-call filter belongs in a custom ``list`` that builds
    on ``base_query().where(...)`` (ADR 0017).
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef)
                    and stmt.name == "base_query"
                ):
                    violations.append(
                        ArchViolation(
                            "base_query_not_overridden",
                            rel,
                            stmt.lineno,
                            f"service {node.name!r} overrides base_query, which composes the "
                            "non-droppable soft-delete / tenant row scope; add read conditions "
                            "via business_filters() instead — a super()-less override silently "
                            "drops scope",
                        )
                    )
    return violations

def _is_self_model(expr: ast.expr) -> bool:
    """True for the service-bound model expressions ``self.model`` / ``type(self).model``."""
    if not isinstance(expr, ast.Attribute) or expr.attr != "model":
        return False
    if isinstance(expr.value, ast.Name) and expr.value.id == "self":
        return True
    return (
        isinstance(expr.value, ast.Call)
        and base_name(expr.value.func) == "type"
        and bool(expr.value.args)
        and isinstance(expr.value.args[0], ast.Name)
        and expr.value.args[0].id == "self"
    )


def _referenced_names(expr: ast.expr) -> set[str]:
    """Every identifier mentioned inside *expr* (``Lead``, ``models.Lead``, ``Lead.email``)."""
    names: set[str] = set()
    for node in ast.walk(expr):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _select_chain(call: ast.Call, parent_of: dict[ast.AST, ast.AST]) -> ast.expr:
    """The outermost expression of the ``select(...).where(...).join(...)`` chain at *call*.

    Ascends while the node is the receiver of a chained method call, so a scope-trait
    model referenced in a trailing ``.where`` / ``.join`` / ``.order_by`` /
    ``.select_from`` is seen too -- not only one passed directly to ``select(...)``.
    """
    current: ast.expr = call
    while True:
        parent = parent_of.get(current)
        grandparent = parent_of.get(parent) if parent is not None else None
        if (
            isinstance(parent, ast.Attribute)
            and parent.value is current
            and isinstance(grandparent, ast.Call)
            and grandparent.func is parent
        ):
            current = grandparent
        else:
            break
    return current


def _enclosing_service_model(node: ast.AST, parent_of: dict[ast.AST, ast.AST]) -> str | None:
    """The model bound by the nearest enclosing ``BaseService`` / ``TenantScopedService``."""
    current = parent_of.get(node)
    while current is not None:
        if isinstance(current, ast.ClassDef):
            bases = {base_name(base) for base in current.bases}
            if {"BaseService", "TenantScopedService"} & bases:
                return _service_model(current)
        current = parent_of.get(current)
    return None


def check_reads_use_base_query(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A scope-trait model is read through ``base_query``, never a raw ``select()``.

    A model that mixes :class:`~terp.core.SoftDeleteMixin` or ``TenantScopedMixin``
    carries row scope (soft-delete / tenant). A bespoke read that issues
    ``select(<Model>)`` directly — instead of building on ``base_query()`` — drops
    that scope, leaking soft-deleted or cross-tenant rows (the F1 follow-up to
    ADR 0017: closing ``base_query`` to overrides did not close a *new* read method
    that never calls it). Build reads on ``base_query()`` / ``business_filters()``;
    the request session re-applies the scope to any single-entity ``select`` as the
    runtime backstop, and this rule is the build-time early warning. ``base_query``
    itself — the one sanctioned ``select(model)`` — lives in the framework, not a
    module, so it is never scanned here.

    The whole ``select(...)`` chain is inspected, so a scope-trait model referenced
    in a trailing ``.where`` / ``.join`` / ``.order_by`` / ``.select_from`` is caught
    too (not only one passed directly to ``select(...)``), and
    ``select(self.model)`` / ``select(type(self).model)`` resolve to the enclosing
    service's bound model. A primary-key load — ``session.get(<ScopedModel>, id)`` —
    is matched directly too (it has no ``select(...)`` node, yet bypasses the row
    scope just the same; the runtime guard re-scopes it as the paired control). A read
    built on ``self.base_query()`` is never rooted at a ``select(...)`` call, so the
    sanctioned pattern is left clean.
    """
    root = pathlib.Path(app_root)
    trees = {path: parse(path) for path in iter_python_files(root)}

    scoped_models: set[str] = set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and (
                {"SoftDeleteMixin", "TenantScopedMixin"}
                & {base_name(base) for base in node.bases}
            ):
                scoped_models.add(node.name)

    violations: list[ArchViolation] = []
    for path, tree in trees.items():
        rel = _rel(path, root)
        parent_of: dict[ast.AST, ast.AST] = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and base_name(node.func) == "select":
                chain = _select_chain(node, parent_of)
                targets = _referenced_names(chain) & scoped_models
                bound_model = _enclosing_service_model(node, parent_of)
                if bound_model in scoped_models and any(
                    _is_self_model(sub) for sub in ast.walk(chain)
                ):
                    targets = targets | {bound_model}
                for target in sorted(targets):
                    violations.append(
                        ArchViolation(
                            "reads_use_base_query",
                            rel,
                            node.lineno,
                            f"reads scope-trait model {target!r} via a raw select(); a "
                            "soft-delete / tenant model must be read through base_query() so "
                            "its row scope is not dropped — build on self.base_query() / "
                            "business_filters() instead of select(...)",
                        )
                    )
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and base_name(node.args[0]) in scoped_models
            ):
                # ``session.get(ScopedModel, id)`` is a primary-key load that bypasses
                # ``base_query`` and the row predicates — it has no ``select(...)`` node
                # for the branch above to see, so it is matched directly (the first
                # positional argument is the scoped model class). ``self.get(session,
                # id)`` / ``_service.get(session, id)`` pass a session first, not a
                # model, so they are not flagged.
                target = base_name(node.args[0])
                violations.append(
                    ArchViolation(
                        "reads_use_base_query",
                        rel,
                        node.lineno,
                        f"reads scope-trait model {target!r} via session.get(); a "
                        "primary-key load drops the soft-delete / tenant scope — read it "
                        "through self.get() / base_query() (the audited BaseService) so "
                        "its row scope is not dropped",
                    )
                )
    return violations