"""The Alembic ``env.py`` delegate (covered logic behind the thin shim).

``_alembic/env.py`` is intentionally three lines that call :func:`run_migrations`;
the real per-run logic lives here so it is exercised (and line-covered) by the
migration test suite rather than hidden inside an Alembic-exec'd script.

Each run targets exactly one package: its models are imported to register their
tables, its ``alembic_version_<label>`` table isolates its history, and
autogenerate is scoped to the tables that package *owns* (a table whose mapped
class lives under the package's import path), so one package's ``make`` never
proposes another package's tables.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import pathlib
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy import MetaData, create_engine, pool
from sqlmodel import SQLModel

from terp.core.migrations import MigrationTree, resolve_all_migration_trees
from terp.migrations.errors import MigrationError


def owned_table_names(import_path: str) -> frozenset[str]:
    """Table names whose mapped class lives under *import_path* (ownership scope)."""
    prefix = f"{import_path}."
    owned: set[str] = set()
    for mapper in SQLModel._sa_registry.mappers:
        module = getattr(mapper.class_, "__module__", "")
        if module == import_path or module.startswith(prefix):
            owned.add(mapper.local_table.name)
    return frozenset(owned)


def scoped_filters(
    owned: frozenset[str],
) -> tuple[Callable[..., bool], Callable[..., bool]]:
    """Alembic ``include_name`` / ``include_object`` limiting tables to *owned*.

    Non-table objects (columns, indexes, constraints) are always included — they
    belong to an owned table that already passed the table filter — while a table
    outside the owning package is excluded from both reflection and metadata
    comparison, keeping autogenerate scoped to this package.
    """

    def include_name(name: str | None, type_: str, parent_names: Any) -> bool:
        if type_ == "table":
            return name in owned
        return True

    def include_object(
        obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
    ) -> bool:
        if type_ == "table":
            return name in owned
        return True

    return include_name, include_object


def _render_as_batch(connection: Any) -> bool:
    """Batch ALTER is a SQLite workaround; native dialects ALTER directly (ADR 0027).

    Rendering every change as ``op.batch_alter_table`` is required only for SQLite
    (which cannot ``ALTER`` in place); on Postgres / MySQL it is needless noise and a
    latent footgun — an op that trips a batch *recreate* becomes a destructive
    copy-and-swap of the whole table — so batch mode is gated to the SQLite dialect.
    """
    return connection.dialect.name == "sqlite"


def _model_modules(import_path: str, app_root: str | None, package: str) -> list[str]:
    """The target's models module plus every model-bearing declared package's.

    Autogenerate compares ``SQLModel.metadata``, so a cross-package / cross-module
    foreign key only resolves when the *target* table is registered too. Importing
    every discovered package's models populates the shared metadata (the FK targets
    resolve) while ``include_name`` / ``include_object`` still scope the *emitted*
    tables to the package being migrated — the independent per-package history is
    unchanged, only FK resolution is fixed. The *all-trees* discovery is used (not the
    runnable set) so a referenced module that has authored no revision yet — e.g. a
    sibling targeted by this package's very first migration — is still imported, so its
    table resolves as a foreign-key target. A route-only/support module with no
    ``models.py`` is skipped; only the target package itself must define models.
    """
    target_module = f"{import_path}.models"
    modules = {target_module}
    for tree in resolve_all_migration_trees(app_root, package=package):
        if tree.models_module == target_module or _tree_has_models(tree):
            modules.add(tree.models_module)
    return sorted(modules)


def _tree_has_models(tree: MigrationTree) -> bool:
    """True when a discovered package actually ships a models module/package."""
    package_dir = tree.path.parent
    return (package_dir / "models.py").is_file() or (package_dir / "models").is_dir()


def _import_model_module(module: str, *, required: bool) -> bool:
    """Import *module*, optionally treating a missing module as an absent table owner.

    Table-owning migration targets must define ``models.py`` so autogenerate has a
    source of truth. Other discovered modules are imported only when present: a
    route-only/support module with no ``models.py`` is not a migration participant.
    Import errors raised *inside* an existing models module still propagate loudly.
    """
    try:
        importlib.import_module(module)
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing == module or module.startswith(f"{missing}."):
            if required:
                package = module.removesuffix(".models")
                raise MigrationError(
                    f"migration target {package!r} has no importable models module "
                    f"({module}); table-owning packages must define models.py"
                ) from exc
            return False
        raise
    return True


def unowned_tables(import_paths: Iterable[str]) -> frozenset[str]:
    """Mapped tables owned by none of *import_paths* (a homeless table, surfaced loudly).

    A table whose mapped class lives under no migration-owning package — most often a
    bare SQLAlchemy-core association ``Table`` (which has no mapper) or a model in a
    shared base module — is silently skipped by every package's scoped autogenerate, so
    it would never be created. A consumer's test can compare against the full discovered
    set (see :func:`terp.migrations.assert_migrations_match_models`) to catch it.
    """
    owned: set[str] = set()
    for path in import_paths:
        owned |= owned_table_names(path)
    return frozenset(SQLModel.metadata.tables) - owned


def _mapped_table_names() -> frozenset[str]:
    """Names of every table backed by a SQLModel mapped class in the shared registry."""
    return frozenset(mapper.local_table.name for mapper in SQLModel._sa_registry.mappers)


def unmapped_tables() -> frozenset[str]:
    """Tables in the shared metadata with no mapped class (a bare association ``Table``).

    A bare SQLAlchemy-core ``Table`` has no mapper, so no package owns it and every
    package's scoped autogenerate skips it silently — it would never be created.
    ``make`` fails closed on these so the omission is loud, not silent.
    """
    return frozenset(SQLModel.metadata.tables) - _mapped_table_names()


def _references_any(table: Any, owned: set[str]) -> bool:
    """True if *table* has a foreign key into one of the *owned* tables."""
    return any(fk.column.table.name in owned for fk in table.foreign_keys)


def _homeless_tables(
    tables: Any, owned: set[str], mapped: frozenset[str]
) -> tuple[list[str], list[str]]:
    """Split unowned-but-FK-connected tables into ``(bare, mapped_unowned)``.

    A table owned by no migration package is "homeless" — every package's scoped
    autogenerate skips it, so it would never be created — *when it is wired into the
    schema by a foreign key into or out of an owned table*. That FK-connection test is
    what keeps the check scoped: an unrelated table polluting the shared
    ``SQLModel.metadata`` (no foreign key to an owned table) is ignored, so the guard
    never false-positives. The connected homeless tables are returned split by whether a
    mapped class backs them, because the remedy differs — a bare ``Table`` should become
    a SQLModel link-model, while a mapped-but-unowned class should move under (or
    declare) a migration-owning package.
    """
    referenced_by_owned: set[str] = set()
    for name in owned:
        table = tables.get(name)
        if table is not None:
            referenced_by_owned.update(fk.column.table.name for fk in table.foreign_keys)
    bare: list[str] = []
    mapped_unowned: list[str] = []
    for name, table in tables.items():
        if name in owned:
            continue
        if name not in referenced_by_owned and not _references_any(table, owned):
            continue
        (mapped_unowned if name in mapped else bare).append(name)
    return sorted(bare), sorted(mapped_unowned)


def assert_no_homeless_tables(
    tree: MigrationTree, app_root: str | None, package: str
) -> None:
    """Fail closed if a table wired into the schema is owned by no migration package.

    Imports the target package's models plus every *declared* package's (runnable or
    not — a referenced module may have no revision yet), then raises if a table that no
    package owns is wired into an owned table by a foreign key. Two kinds slip through a
    package's scoped autogenerate and would never be created:

    * a bare association ``Table`` (no mapped class, so no package owns it), and
    * a *mapped* SQLModel class whose module lives outside every discovered package's
      import prefix (e.g. a shared base module that ships no migration history).

    Each is reported with its own remedy. Unrelated tables (no foreign key into or out
    of an owned table) are ignored, so the check never false-positives on a test fixture
    or an externally-managed table polluting the shared metadata.
    """
    trees = resolve_all_migration_trees(app_root, package=package)
    _import_model_module(tree.models_module, required=True)
    for other in trees:
        if other.models_module != tree.models_module and _tree_has_models(other):
            _import_model_module(other.models_module, required=False)
    owned: set[str] = set(owned_table_names(tree.import_path))
    for other in trees:
        owned |= owned_table_names(other.import_path)
    bare, mapped_unowned = _homeless_tables(
        SQLModel.metadata.tables, owned, _mapped_table_names()
    )
    if bare:
        raise MigrationError(
            f"these tables have no mapped model yet are wired into the schema by a "
            f"foreign key, so no package owns them and autogenerate would silently skip "
            f"them: {bare}; define each as a SQLModel link-model class (table=True)"
        )
    if mapped_unowned:
        raise MigrationError(
            f"these tables are mapped but no migration package owns them (their model "
            f"lives outside every discovered package's import path) yet they are wired "
            f"into the schema by a foreign key, so autogenerate would silently skip "
            f"them: {mapped_unowned}; move each model under a migration-owning package, "
            f"or give its package a terp.migrations entry point or a migrations/ directory"
        )


_SPLIT_OWNERSHIP_MARKER = "arch-allow-table-ownership-is-not-split:"


def _waives_split_ownership(tree: MigrationTree) -> bool:
    """True if *tree*'s models module carries a reasoned split-ownership marker.

    The governed opt-out for an app that has ALREADY shipped the move and is deferring
    the expand/contract to a later release. It lives in the owning package's models
    module (next to the model that moved), so it is greppable and counted by the
    escape-hatch ratchet like any other marker.
    """
    try:
        spec = importlib.util.find_spec(tree.models_module)
    except (ImportError, ValueError):
        return False
    if spec is None or spec.origin is None:
        return False
    try:
        source = pathlib.Path(spec.origin).read_text(encoding="utf-8")
    except OSError:
        return False
    return _SPLIT_OWNERSHIP_MARKER in source


def _tables_created_by(tree: MigrationTree) -> frozenset[str]:
    """Table names *tree*'s own revisions create, from a static scan of ``upgrade()``.

    Only literal ``create_table("name", ...)`` calls inside ``upgrade`` count — a create
    in ``downgrade`` is reverting a drop, not owning a table. A table the history creates
    under one name and later renames is deliberately NOT reported (the current name has
    no literal create), which keeps the caller conservative: it only ever fires on an
    exact, statically provable creator.
    """
    created: set[str] = set()
    versions = tree.path / "versions"
    if not versions.is_dir():
        return frozenset()
    for path in sorted(versions.glob("*.py")):
        try:
            module = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for function in ast.walk(module):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if function.name != "upgrade":
                continue
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "create_table"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    created.add(node.args[0].value)
    return frozenset(created)


def misowned_tables(trees: Iterable[MigrationTree]) -> dict[str, tuple[str, str]]:
    """``{table: (owning_label, creating_label)}`` for every split ownership.

    A table is *owned* by the package whose models declare it and *created* by the
    package whose history holds its ``create_table``. Moving a model between packages
    silently splits the two: no DDL is generated at all (the losing package stops owning
    the table, so its scoped autogenerate cannot propose a drop; the gaining package
    diffs against a database where the table already exists, so it proposes no create).
    The database in front of you keeps upgrading cleanly — and then the NEXT schema
    change to that model is authored into the gaining package's history, which is an
    INDEPENDENT history ordered only by foreign-key dependencies. With no FK between the
    two packages the order falls back to label sort, so a fresh install can run the
    ``add_column`` before the ``create_table`` and fail with "no such table".

    That failure reaches only fresh installs — a new environment, a new developer, a
    restore — long after the commit that caused it, which is why this is a fail-closed
    check rather than a documented caveat. Callers must import every package's models
    first so ownership is complete.
    """
    trees = list(trees)
    creator_of: dict[str, str] = {}
    for tree in trees:
        for table in _tables_created_by(tree):
            creator_of.setdefault(table, tree.label)
    split: dict[str, tuple[str, str]] = {}
    for tree in trees:
        for table in owned_table_names(tree.import_path):
            creator = creator_of.get(table)
            if creator is not None and creator != tree.label:
                split[table] = (tree.label, creator)
    return split


def assert_no_split_table_ownership(app_root: str | None, package: str) -> None:
    """Fail closed when a package's models own a table another package's history creates.

    See :func:`misowned_tables` for why this is silent and why it only bites a fresh
    install. Raised at authoring time (``terp migrate make``) and in the build-time
    guard, so the split is caught at the commit that creates it.
    """
    trees = resolve_all_migration_trees(app_root, package=package)
    for tree in trees:
        if _tree_has_models(tree):
            _import_model_module(tree.models_module, required=False)
    label_of = {tree.label: tree for tree in trees}
    split = {
        table: pair
        for table, pair in misowned_tables(trees).items()
        if not _waives_split_ownership(label_of[pair[0]])
    }
    if not split:
        return
    detail = "; ".join(
        f"{table!r} is owned by {owner!r} but created by {creator!r}"
        for table, (owner, creator) in sorted(split.items())
    )
    raise MigrationError(
        f"split table ownership: {detail}. Each package's history is independent and "
        f"ordered only by foreign keys, so the next schema change to this model is "
        f"authored into a history that a fresh install may run BEFORE the one that "
        f"creates the table - your existing database keeps working while new "
        f"installs break. Either move the model back to the package whose history "
        f"creates the table, or move the table properly: give the new package its own "
        f"table (a new __tablename__), copy the rows in a migration, and retire the old "
        f"table in a later release. See `terp guide migrations`. If the move has already "
        f"shipped and the expand/contract is planned for a later release, the owning "
        f"package's models module may carry a reasoned "
        f"`# {_SPLIT_OWNERSHIP_MARKER} <reason>` marker, counted by the escape-hatch "
        f"budget."
    )


def _dependency_edges(
    metadata: MetaData, label_of_table: dict[str, str]
) -> dict[str, set[str]]:
    """Map each package label to the labels its tables' foreign keys reference."""
    deps: dict[str, set[str]] = {}
    for table in metadata.tables.values():
        owner = label_of_table.get(table.name)
        if owner is None:
            continue
        edges = deps.setdefault(owner, set())
        for foreign_key in table.foreign_keys:
            target = label_of_table.get(foreign_key.column.table.name)
            if target is not None and target != owner:
                edges.add(target)
    return deps


def _toposort(
    trees: list[MigrationTree], deps: dict[str, set[str]]
) -> list[MigrationTree]:
    """Order *trees* so a package precedes any it references (FK-dependency order).

    Kahn's algorithm with the input order as a deterministic tie-break, so without
    cross-package foreign keys the order is unchanged (capabilities first, then app
    modules, each alphabetical). A cross-package FK cycle cannot be linearised, so it
    fails closed rather than produce an order that breaks at create time.
    """
    order_index = {tree.label: position for position, tree in enumerate(trees)}
    remaining = list(trees)
    placed: set[str] = set()
    ordered: list[MigrationTree] = []
    while remaining:
        ready = [tree for tree in remaining if deps.get(tree.label, set()) <= placed]
        if not ready:
            cycle = sorted(tree.label for tree in remaining)
            raise MigrationError(
                f"cross-package foreign-key cycle among {cycle}; break it (e.g. a "
                "nullable FK populated in a later migration) so the histories can order"
            )
        chosen = min(ready, key=lambda tree: order_index[tree.label])
        ordered.append(chosen)
        placed.add(chosen.label)
        remaining.remove(chosen)
    return ordered


def order_trees_by_dependencies(trees: list[MigrationTree]) -> list[MigrationTree]:
    """Order discovered *trees* so a referenced package migrates before a referencing one.

    Capabilities are FK-less leaves, so this is identity for them; it matters for a
    consumer whose app modules carry cross-module foreign keys, making ``upgrade``
    create the referenced table first regardless of label ordering (``downgrade``
    reverses it). Reads the shared metadata, so it imports each package's models first.
    """
    for tree in trees:
        importlib.import_module(tree.models_module)
    label_of_table: dict[str, str] = {}
    for tree in trees:
        for name in owned_table_names(tree.import_path):
            label_of_table[name] = tree.label
    deps = _dependency_edges(SQLModel.metadata, label_of_table)
    return _toposort(trees, deps)


def run_migrations(context: Any) -> None:
    """Run the migrations for the package named by the active Alembic *context*."""
    config = context.config
    import_path = config.get_main_option("terp_import_path")
    version_table = config.get_main_option("terp_version_table")
    label = config.get_main_option("terp_label")
    database_url = config.get_main_option("sqlalchemy.url")
    app_root = config.get_main_option("terp_app_root") or None
    package = config.get_main_option("terp_package") or "app"
    schema_layout = config.get_main_option("terp_schema_layout") or "flat"

    target_module = f"{import_path}.models"
    for module in _model_modules(import_path, app_root, package):
        _import_model_module(module, required=module == target_module)
    include_name, include_object = scoped_filters(owned_table_names(import_path))

    if context.is_offline_mode():
        # Offline (--sql) rendering: no engine, no connection — Alembic renders the
        # DDL (and the version-table bookkeeping) against the URL's dialect only.
        # The per-module layout rides *session* state (search_path) that a static
        # script cannot carry faithfully, so it fails closed here (ADR 0072).
        if schema_layout == "per-module":
            raise MigrationError(
                "offline SQL (--sql) supports the flat layout only; a per-module "
                "database migrates online so the layout's session state routes "
                "each package's DDL (ADR 0072)"
            )
        context.configure(
            url=database_url,
            target_metadata=SQLModel.metadata,
            version_table=version_table,
            include_name=include_name,
            include_object=include_object,
            compare_type=True,
            literal_binds=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = create_engine(database_url, poolclass=pool.NullPool)
    try:
        with connectable.connect() as connection:
            configure_opts: dict[str, Any] = {}
            if schema_layout == "per-module":
                labels = [
                    tree.label for tree in resolve_all_migration_trees(app_root, package=package)
                ]
                _enter_per_module_schema(connection, label, labels)
                # The version table stays in the default schema so status / the boot
                # guard read it over a plain connection, layout-unaware (ADR 0070).
                configure_opts["version_table_schema"] = "public"
            context.configure(
                connection=connection,
                target_metadata=SQLModel.metadata,
                version_table=version_table,
                include_name=include_name,
                include_object=include_object,
                compare_type=True,
                render_as_batch=_render_as_batch(connection),
                **configure_opts,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


def search_path_statement(own_label: str, labels: Iterable[str]) -> str:
    """The session ``SET search_path`` for one package's migration run (ADR 0070).

    The owning package's schema comes **first** — PostgreSQL creates unqualified
    tables in the first search_path entry, which is exactly how a revision written
    without any schema token lands in its package's schema. Every other package's
    schema follows so a cross-module foreign key's unqualified target still
    resolves, and ``public`` stays last for anything shared (extensions, the
    pinned ``alembic_version_*`` tables).
    """
    ordered = [own_label, *[item for item in labels if item != own_label], "public"]
    joined = ", ".join(f'"{name}"' for name in dict.fromkeys(ordered))
    return f"SET search_path TO {joined}"


def _enter_per_module_schema(connection: Any, label: str, labels: Iterable[str]) -> None:
    """Route this run's DDL into the owning package's PostgreSQL schema.

    The documented Alembic recipe for schema-level separation: create the schema,
    point the session ``search_path`` at it (own schema first), and pin the
    dialect's ``default_schema_name`` so autogenerate reflects the package's tables
    as schema-less — keeping revisions token-free and the drift check meaningful
    under the layout. Fails closed on any non-PostgreSQL dialect: schemas are a
    PostgreSQL feature, and silently running flat would desynchronize the layout.
    """
    if connection.dialect.name != "postgresql":
        raise MigrationError(
            "schema layout 'per-module' requires PostgreSQL; "
            f"got dialect {connection.dialect.name!r} (ADR 0070)"
        )
    connection.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{label}"')
    connection.exec_driver_sql(search_path_statement(label, labels))
    # Commit the autobegun setup transaction: Alembic treats a connection with an
    # in-progress transaction as caller-managed and would never commit the migration
    # DDL (a silent full rollback). The session-level search_path survives the commit.
    connection.commit()
    connection.dialect.default_schema_name = label


__all__ = [
    "assert_no_homeless_tables",
    "order_trees_by_dependencies",
    "owned_table_names",
    "run_migrations",
    "scoped_filters",
    "search_path_statement",
    "unmapped_tables",
    "unowned_tables",
]
