"""Persistence rules: writes go through the audited chokepoint, models use BaseTable.

No raw session/engine construction (``SessionDep`` is the only handle), no direct
``session.*`` writes (the audited ``BaseService`` chokepoint owns persistence),
every table model extends ``BaseTable``, and every input ``str`` caps its length.
"""

from __future__ import annotations

import ast
import pathlib

from terp.arch._ast import _SECURITY_SKIP_DIRS, base_name, iter_python_files, parse
from terp.arch.rules._support import (
    ArchViolation,
    _MANAGED_INPUT_COLUMNS,
    _SESSION_CONSTRUCTORS,
    _SESSION_EXECUTORS,
    _SESSION_MUTATORS,
    _SESSION_VAR_NAMES,
    _annotated_session_params_for_function,
    _has_max_length,
    _is_dml_expression,
    _is_sensitive_field_name,
    _is_str_annotation,
    _is_table_model_class,
    _module_under,
    _rel,
    _request_body_model_names,
    _response_model_names,
)


def _is_plain_string_literal(node: ast.expr) -> bool:
    """True only for a literal string known exactly at review time."""
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def check_no_dynamic_sql(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Raw SQL text in app modules must be a static literal, never dynamically built.

    Dynamic ``text(...)`` / ``sqlalchemy.text(...)`` calls (f-strings, string
    concatenation, ``.format``, ``%`` formatting, or a variable) are not statically
    reviewable and are easy to turn into SQL injection. Keep SQL as a literal and
    pass data through SQLAlchemy parameters / ORM expressions instead. As a
    security rule this also scans ``tests/`` and ``migrations/`` dirs inside a
    module — they are importable Python, so they are application surface too.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root, skip_dirs=_SECURITY_SKIP_DIRS):
        if _module_under(path, package) is None:
            continue
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and base_name(node.func) == "text"
                and node.args
                and not _is_plain_string_literal(node.args[0])
            ):
                violations.append(
                    ArchViolation(
                        "no_dynamic_sql",
                        rel,
                        node.lineno,
                        "text(...) must receive a plain string literal; use ORM expressions "
                        "or parameterized SQLAlchemy queries instead of dynamically built SQL",
                    )
                )
    return violations


def _attr_calls_in(node: ast.AST, attr: str) -> list[ast.Call]:
    """Every ``<recv>.<attr>(...)`` call node in *node*'s subtree."""
    return [
        sub
        for sub in ast.walk(node)
        if isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Attribute)
        and sub.func.attr == attr
    ]


def check_offset_queries_declare_ordering(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """An offset-paginated query must declare an explicit ordering.

    Row order without an ``ORDER BY`` is undefined, so paging with ``.offset(...)``
    over an unordered query can skip or repeat rows between pages. A function that
    calls ``.offset(...)`` must also call ``.order_by(...)`` (or page through the
    framework's ordered pagination helper) so the sequence is deterministic.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            offset_calls = _attr_calls_in(node, "offset")
            if offset_calls and not _attr_calls_in(node, "order_by"):
                violations.append(
                    ArchViolation(
                        "offset_queries_declare_ordering",
                        rel,
                        offset_calls[0].lineno,
                        f"{node.name!r} paginates with .offset() but declares no .order_by(); "
                        "add a deterministic ordering so pages do not skip or repeat rows",
                    )
                )
    return violations



def check_no_raw_session_construction(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """App code never constructs a ``Session`` / engine directly; it uses ``SessionDep``."""
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = base_name(node.func)
                if name in _SESSION_CONSTRUCTORS:
                    violations.append(
                        ArchViolation(
                            "no_raw_session_construction",
                            rel,
                            node.lineno,
                            f"constructs {name!r} directly; depend on terp.core.SessionDep instead",
                        )
                    )
    return violations


_RAW_CONNECTION_ACCESSORS: frozenset[str] = frozenset({"get_bind", "connection"})


def check_no_raw_connection_access(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Modules never reach the raw DB connection / engine behind the session.

    The runtime write guard (ADR 0015) covers the request ``Session``'s own
    persistence methods, but the bound ``Engine`` / ``Connection`` it exposes can
    issue DML directly -- ``session.get_bind().connect().execute(insert(...))`` or
    ``session.connection().execute(...)`` -- bypassing the audited chokepoint (the F3
    follow-up). A module must never call ``get_bind`` / ``connection``; persist
    through ``BaseService`` so every write is audited. A ``get_bind().connect()``
    escape is already caught here at the ``get_bind`` call, and raw ``Session`` /
    engine *construction* (``create_engine`` / ``sessionmaker``) is separately banned
    by ``no_raw_session_construction`` -- so an unrelated ``.connect()`` on a domain
    object (a websocket / cache / search client) is deliberately *not* flagged.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _RAW_CONNECTION_ACCESSORS
            ):
                violations.append(
                    ArchViolation(
                        "no_raw_connection_access",
                        rel,
                        node.lineno,
                        f"module calls {node.func.attr!r}() to reach the raw DB "
                        "connection/engine, which can issue a write outside the audited "
                        "BaseService chokepoint (the write guard only covers the request "
                        "Session); persist through BaseService instead",
                    )
                )
    return violations


def check_mutations_emit_audit(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Modules never write to the session directly; mutations go through the audited chokepoint.

    Audit is auto-emitted from the single ``BaseService`` ``create`` / ``update`` /
    ``delete`` (``_save`` / ``_remove``) chokepoint inside the write's transaction.
    A module that calls ``session.add`` / ``delete`` / ``merge`` / ``commit`` /
    ``flush`` / a ``bulk_*`` helper itself — or smuggles a write through
    ``session.execute`` / ``exec`` with a DML statement (``insert`` / ``update`` /
    ``delete`` / raw ``text``) — bypasses that chokepoint and would persist a
    mutation with **no** audit trail. The receiver is recognised by the
    conventional session names **and** by any parameter annotated ``Session`` /
    ``SessionDep`` (so renaming the variable does not evade the rule). Routing every
    write through ``BaseService`` keeps the trail structural — a method call on the
    model's service (e.g. ``_service.delete(...)``) is fine; a raw ``session.*``
    write is not.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        module_body = [
            node
            for node in tree.body
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        ]
        scoped_bodies: list[tuple[list[ast.stmt], set[str]]] = [
            (module_body, set(_SESSION_VAR_NAMES))
        ]
        scoped_bodies.extend(
            (node.body, set(_SESSION_VAR_NAMES) | _annotated_session_params_for_function(node))
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        )

        for body, session_vars in scoped_bodies:
            dml_names: set[str] = set()
            for stmt in body:
                if (
                    isinstance(stmt, ast.Assign)
                    and isinstance(stmt.value, ast.Call)
                    and _is_dml_expression(stmt.value)
                ):
                    dml_names.update(
                        target.id for target in stmt.targets if isinstance(target, ast.Name)
                    )
            for stmt in body:
                for node in ast.walk(stmt):
                    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                        continue
                    if (
                        not isinstance(node, ast.Call)
                        or not isinstance(node.func, ast.Attribute)
                        or not isinstance(node.func.value, ast.Name)
                        or node.func.value.id not in session_vars
                    ):
                        continue
                    attr = node.func.attr
                    is_write = attr in _SESSION_MUTATORS or (
                        attr in _SESSION_EXECUTORS
                        and bool(node.args)
                        and (
                            _is_dml_expression(node.args[0])
                            or (isinstance(node.args[0], ast.Name) and node.args[0].id in dml_names)
                        )
                    )
                    if not is_write:
                        continue
                    call = f"{node.func.value.id}.{attr}()"
                    violations.append(
                        ArchViolation(
                            "mutations_emit_audit",
                            rel,
                            node.lineno,
                            f"module writes to the session directly ({call}); persist through "
                            "terp.core.BaseService (create/update/delete or self._save/_remove) so "
                            "every mutation is audited",
                        )
                    )
    return violations


def check_table_models_use_base_table(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Every ORM table model inherits ``BaseTable`` (no bare ``SQLModel`` tables).

    A ``table=True`` model that skips ``BaseTable`` bypasses the framework's UUID
    id, timestamps, and optimistic-concurrency ``version`` — a model living
    outside the control-plane contract.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not _is_table_model_class(node):
                continue
            if "BaseTable" not in {base_name(base) for base in node.bases}:
                violations.append(
                    ArchViolation(
                        "table_models_use_base_table",
                        rel,
                        node.lineno,
                        f"table model {node.name!r} does not inherit BaseTable; "
                        "every persisted model must extend terp.core.BaseTable",
                    )
                )
    return violations


def check_input_str_fields_have_max_length(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Every ``str`` a client can supply caps its length.

    A field is client-supplied when it lives on a table model, on a ``*Create`` /
    ``*Update`` schema, **or** on any class used as a request body (a route
    handler's body parameter, or a ``build_crud_router`` create/update schema) -- so
    an input DTO named off-convention (``LoginRequest``, ``UserProvision``) is
    capped too, not only the ``*Create`` / ``*Update`` ones. ``str``, ``str |
    None``, and sequence containers of str (``list[str]``) all count; an uncapped
    one is an unbounded-input (DoS / abuse) hole.
    """
    root = pathlib.Path(app_root)
    parsed = [(_rel(path, root), parse(path)) for path in iter_python_files(root)]
    body_models = _request_body_model_names(tree for _, tree in parsed)
    violations: list[ArchViolation] = []
    for rel, tree in parsed:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {base_name(base) for base in node.bases}
            is_table = "BaseTable" in bases
            is_input = node.name.endswith(("Create", "Update")) or node.name in body_models
            if not (is_table or is_input):
                continue
            for stmt in node.body:
                if not isinstance(stmt, ast.AnnAssign) or not _is_str_annotation(stmt.annotation):
                    continue
                if not _has_max_length(stmt.value):
                    field = stmt.target.id if isinstance(stmt.target, ast.Name) else "<field>"
                    violations.append(
                        ArchViolation(
                            "input_str_fields_have_max_length",
                            rel,
                            stmt.lineno,
                            f"{node.name}.{field}: str field declares no max_length; "
                            "cap every input string (use Field(max_length=...))",
                        )
                    )
    return violations


def check_input_schemas_exclude_managed_columns(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """No input schema declares a framework-managed column.

    An input schema is a ``*Create`` / ``*Update`` **or** any class used as a request
    body (a route handler's body parameter, or a ``build_crud_router``
    create/update schema) -- the same role-based definition the input-cap rule uses,
    so an off-convention DTO (``UserProvision``, ``LoginRequest``) is covered too.
    ``BaseService.create`` / ``update`` copy a schema's fields onto the model, so a
    client-settable ``id`` / ``version`` / ``tenant_id`` / ``created_by_id`` is an
    over-posting (mass-assignment) hole -- a client could forge the primary key,
    defeat optimistic concurrency, or cross a tenant boundary. The framework assigns
    every managed column centrally; an input schema must never expose one.
    (``BaseService`` also strips the same set at runtime -- this rule is the
    build-time half of that two-layer control.)
    """
    root = pathlib.Path(app_root)
    parsed = [(_rel(path, root), parse(path)) for path in iter_python_files(root)]
    body_models = _request_body_model_names(tree for _, tree in parsed)
    violations: list[ArchViolation] = []
    for rel, tree in parsed:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not (node.name.endswith(("Create", "Update")) or node.name in body_models):
                continue
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and stmt.target.id in _MANAGED_INPUT_COLUMNS
                ):
                    violations.append(
                        ArchViolation(
                            "input_schemas_exclude_managed_columns",
                            rel,
                            stmt.lineno,
                            f"{node.name}.{stmt.target.id}: input schema declares the "
                            f"framework-managed column {stmt.target.id!r}; a client must not "
                            "set it (the framework assigns it). Remove it to close the "
                            "over-posting hole",
                        )
                    )
    return violations


def check_schemas_exclude_sensitive_fields(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A read / response DTO never exposes a credential-shaped field.

    Routes serialize a response DTO out of the boundary, so a field whose name reads
    like a secret -- ``password`` / ``hashed_password`` / ``*secret`` / ``*api_key`` /
    ``*token`` -- would leak the credential to every caller. A response DTO is a
    ``BaseSchema`` / ``BaseUpdateSchema`` model **or** any class wired as a
    ``response_model=`` (so an input ``*Create`` / ``*Update`` mistakenly reused as a
    response is caught), excluding the inputs that are only ever request bodies (a
    client *supplies* a password) and ``table=True`` models (a table may store the
    hash). Plain helper classes are not policed. This guards the gap
    ``response_model_not_table_model`` leaves: a hand-rolled Read model that copies the
    stored hash. (``token_version`` / ``version`` are integer counters, not secrets.)
    """
    root = pathlib.Path(app_root)
    parsed = [(_rel(path, root), parse(path)) for path in iter_python_files(root)]
    body_models = _request_body_model_names(tree for _, tree in parsed)
    response_models = _response_model_names(tree for _, tree in parsed)
    violations: list[ArchViolation] = []
    for rel, tree in parsed:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            is_schema = bool({"BaseSchema", "BaseUpdateSchema"} & {base_name(b) for b in node.bases})
            is_response = node.name in response_models
            is_input = node.name.endswith(("Create", "Update")) or node.name in body_models
            if _is_table_model_class(node) or not (is_schema or is_response):
                continue
            if is_input and not is_response:
                continue
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and _is_sensitive_field_name(stmt.target.id)
                ):
                    violations.append(
                        ArchViolation(
                            "schemas_exclude_sensitive_fields",
                            rel,
                            stmt.lineno,
                            f"{node.name}.{stmt.target.id}: response DTO exposes a "
                            f"credential-shaped field {stmt.target.id!r}; a Read schema must "
                            "not serialize a password/secret/token out of the API boundary",
                        )
                    )
    return violations


def check_tables_have_migrations(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Every app module that defines a table model ships a packaged migration history.

    A deployed Terp app builds its schema from packaged migrations, not
    ``create_all`` (the production boot guard ``assert_migrations_current`` applies
    them) — so an ``app/modules/<name>`` that declares a ``table=True`` model but has
    no ``migrations/versions/`` revision would deploy with that table **missing** and
    the first request would 500 on a nonexistent table. This rule fails the build
    first; at boot the guard's ``assert_no_missing_histories`` half refuses the same
    violation fail closed (the two halves of the migration control). Run
    ``terp migrate make <name>`` and commit the generated revision.

    Scope: app modules under ``modules/<name>`` only. A capability ships its history
    via a ``terp.migrations`` entry point (declared in packaging, not visible to a
    source scan), and a non-module table model (e.g. a shared base) is out of scope —
    the runtime homeless-table check (``terp migrate make`` / ``unowned_tables``)
    covers those.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    flagged_modules: set[str] = set()
    for path in iter_python_files(root):
        tree = parse(path)
        table_classes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and _is_table_model_class(node)
        ]
        if not table_classes:
            continue
        module_name = _module_under(path, package)
        if module_name is None or module_name in flagged_modules:
            # A capability (entry-point migrations), a non-module table model, or a
            # module already reported from another file.
            continue
        index = path.parts.index("modules")
        versions = pathlib.Path(*path.parts[: index + 2]) / "migrations" / "versions"
        has_revision = versions.is_dir() and any(
            entry.is_file() and not entry.name.startswith("_")
            for entry in versions.glob("*.py")
        )
        if not has_revision:
            flagged_modules.add(module_name)
            table_models = sorted(node.name for node in table_classes)
            violations.append(
                ArchViolation(
                    "tables_have_migrations",
                    _rel(path, root),
                    min(node.lineno for node in table_classes),
                    f"module {module_name!r} defines table model(s) {table_models} but ships "
                    "no migration (modules/<name>/migrations/versions/); a deployed app builds "
                    "its schema from migrations, so the table would never be created and the "
                    f"boot guard would not notice — run `terp migrate make {module_name}` and "
                    "commit the generated revision",
                )
            )
    return violations


def check_no_manual_table_schema(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Table models never hand-write a ``schema=`` placement (the layout is managed).

    The physical schema layout is a **deployment** decision (``DB_SCHEMA_LAYOUT``,
    ADR 0070): under ``flat`` every table lives in the default schema, and under
    ``per-module`` the migration runtime routes each package's tables into its own
    PostgreSQL schema via the search_path — in both layouts the model metadata stays
    schema-free. A hand-written ``__table_args__ = {"schema": ...}`` pins one table
    to a fixed schema, silently escaping the managed layout (and breaking SQLite
    dev/test, which parses a schema prefix as an ATTACH database name).
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        if _module_under(path, package) is None:
            continue
        tree = parse(path)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign | ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(
                isinstance(target, ast.Name) and target.id == "__table_args__"
                for target in targets
            ):
                continue
            for dict_node in ast.walk(node):
                if not isinstance(dict_node, ast.Dict):
                    continue
                for key in dict_node.keys:
                    if isinstance(key, ast.Constant) and key.value == "schema":
                        violations.append(
                            ArchViolation(
                                "no_manual_table_schema",
                                _rel(path, root),
                                key.lineno,
                                "__table_args__ pins a hand-written 'schema'; the physical "
                                "layout is deployment-managed (DB_SCHEMA_LAYOUT, ADR 0070) "
                                "— remove the schema token and let the layout place the table",
                            )
                        )
    return violations


# A partial unique index must carry a predicate for *every* verified dialect
# (ADR 0069: PostgreSQL in prod + SQLite in dev/test). A Postgres-only predicate
# silently compiles to a FULL unique index on SQLite, reinstating the dead-row
# trap in the dev/test loop — so both are required before the index counts as the
# fix (an extra ``mssql_where`` etc. is welcome but not sufficient on its own).
_VERIFIED_DIALECT_WHERE_KEYWORDS: frozenset[str] = frozenset(
    {"postgresql_where", "sqlite_where"}
)


def _soft_delete_capable_class_names(root: pathlib.Path) -> frozenset[str]:
    """Class names that compose ``SoftDeleteMixin`` directly or transitively (tree-wide).

    The soft-delete trait is commonly factored into an app-owned base
    (``class AppTable(BaseTable, SoftDeleteMixin)`` — the pattern ADR 0011
    recommends), so a table inheriting *that* base is soft-delete too even though
    ``SoftDeleteMixin`` is absent from its own bases. This walks the whole app
    tree once, records each class's base names, and computes the taint closure
    from ``SoftDeleteMixin`` so the guard sees the inherited case as well as the
    direct one. Name-based, like the sibling rules; a name defined twice merges
    its bases conservatively (a class is capable if *any* definition composes the
    trait — fail closed).
    """
    bases_of: dict[str, set[str]] = {}
    for path in iter_python_files(root):
        for node in ast.walk(parse(path)):
            if isinstance(node, ast.ClassDef):
                bases_of.setdefault(node.name, set()).update(
                    base_name(base) for base in node.bases
                )
    tainted: set[str] = {"SoftDeleteMixin"}
    changed = True
    while changed:
        changed = False
        for name, bases in bases_of.items():
            if name not in tainted and bases & tainted:
                tainted.add(name)
                changed = True
    return frozenset(tainted)


def check_no_unique_columns_on_soft_delete_models(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Soft-delete models never declare a full-table unique constraint (dead rows block reuse).

    A soft-deleted row stays in the table, so it keeps occupying every full-table
    unique index: the "deleted" value (an email, a slug, a code) can never be used
    again, surfacing as an inexplicable 409 long after the delete. Scope uniqueness
    to the *live* rows with a partial unique index — ``Index("uq_note_slug_live",
    "slug", unique=True, postgresql_where=text("deleted_at IS NULL"),
    sqlite_where=text("deleted_at IS NULL"))`` in ``__table_args__``, which this
    rule accepts — or deactivate instead of deleting (how the identity user table
    keeps ``email`` unique).

    Flags ``Field(unique=True)``, ``UniqueConstraint(...)``, and a full-table
    ``Index(..., unique=True)`` on any table that composes ``SoftDeleteMixin`` —
    directly *or* through an app-owned base (``class AppTable(BaseTable,
    SoftDeleteMixin)``, ADR 0011). The partial-index fix must carry a predicate
    for **every** verified dialect (``postgresql_where`` *and* ``sqlite_where``,
    ADR 0069): a Postgres-only predicate silently compiles to a full unique index
    on SQLite (dev/test), reinstating the trap — so it stays flagged.
    """
    root = pathlib.Path(app_root)
    soft_delete_classes = _soft_delete_capable_class_names(root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        if _module_under(path, package) is None:
            continue
        tree = parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not _is_table_model_class(node):
                continue
            if not any(
                base_name(base) in soft_delete_classes for base in node.bases
            ):
                continue
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                name = base_name(call.func)
                unique_kw = any(
                    keyword.arg == "unique"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in call.keywords
                )
                where_keywords = {
                    keyword.arg
                    for keyword in call.keywords
                    if keyword.arg is not None and keyword.arg.endswith("_where")
                }
                covers_verified = _VERIFIED_DIALECT_WHERE_KEYWORDS <= where_keywords
                flagged = (
                    (name == "Field" and unique_kw)
                    or name == "UniqueConstraint"
                    or (name == "Index" and unique_kw and not covers_verified)
                )
                if flagged:
                    violations.append(
                        ArchViolation(
                            "no_unique_columns_on_soft_delete_models",
                            _rel(path, root),
                            call.lineno,
                            f"soft-delete model {node.name!r} declares a full-table "
                            "unique constraint: a soft-deleted row keeps occupying the "
                            "index, so the value can never be reused; scope it to the "
                            "live rows with a partial unique index carrying a predicate "
                            "for every verified dialect (Index(..., unique=True, "
                            "postgresql_where=text('deleted_at IS NULL'), "
                            "sqlite_where=text('deleted_at IS NULL'))) or deactivate "
                            "instead of soft-deleting",
                        )
                    )
    return violations
