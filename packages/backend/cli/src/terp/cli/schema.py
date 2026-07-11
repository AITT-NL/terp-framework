"""``terp inspect schema`` — the Schema Graph: every table, owned and alarmed.

The database schema has one sanctioned source of truth: the shared SQLModel
metadata, populated by importing every declared **migration tree**'s models
module (exactly how ``terp migrate`` discovers models). This module projects
that metadata into one structured report — JSON-first so
external tooling (Terp Studio) can visualize the data model without importing
``terp.*`` — and reconciles it fail-visibly, mirroring the access graph:

* **``tables``** — every mapped table, attributed to its owning migration tree
  (``module`` + ``kind``) with its column/foreign-key detail and the enforced
  kernel traits (``BaseTable`` lineage, soft-delete / owned / tenant-scoped /
  actor-stamped).
* **``unowned_tables``** — mapped tables whose model module NO migration tree
  owns: ``terp migrate`` will never manage their schema (drift risk). Alarmed,
  never silently mislabeled.
* **``non_canonical_models``** — mapped classes that do not inherit
  ``BaseTable``: they bypass the kernel's id/timestamps/OCC contract (the
  ``table_models_use_base_table`` gate rule is the build-time half; this is the
  inspection's fail-visible view of the same drift).
* **``unmapped_tables``** — raw ``Table`` objects on the metadata with no
  mapped class (hand-rolled DDL; the ``no_manual_table_schema`` rule's
  build-time territory) — reported, never dropped.
* **``unimported_models``** — ``table=True`` models found by a SOURCE SCAN of
  the app tree that never landed on the metadata: a model defined outside the
  sanctioned ``models.py`` import path would otherwise be invisible to every
  runtime view. The scan is the reconciliation ground truth the metadata is
  held against, exactly like ``app.openapi()`` for routes.

This is a **view, never a second source of truth** (ADR 0011).
"""

from __future__ import annotations

import ast
import importlib
import json
import pathlib
from collections.abc import Iterable, Sequence

from sqlmodel import SQLModel

from terp.core import ActorStampedMixin, BaseTable, OwnedMixin, SoftDeleteMixin
from terp.core.migrations import MigrationTree, resolve_all_migration_trees


def import_declared_models(
    app_root: str | pathlib.Path | None = None, *, package: str = "app"
) -> list[MigrationTree]:
    """Import every declared migration tree's models module (the sanctioned loader).

    Mirrors ``terp migrate``'s model discovery: each tree's ``<import_path>.models``
    is imported into the shared SQLModel metadata. A tree without a models module is
    a route-only package — skipped, exactly like the migration runtime does.
    """
    trees = resolve_all_migration_trees(app_root, package=package)
    for tree in trees:
        module = tree.models_module
        try:
            importlib.import_module(module)
        except ModuleNotFoundError as exc:
            missing = exc.name or ""
            if missing == module or module.startswith(missing + "."):
                continue  # route-only package: not a table owner
            raise
    return trees


def _owning_tree(model_module: str, trees: Sequence[MigrationTree]) -> MigrationTree | None:
    """The tree whose ``import_path`` is the longest ownership prefix of *model_module*."""
    best: MigrationTree | None = None
    best_len = -1
    for tree in trees:
        path = tree.import_path
        owns = model_module == path or model_module.startswith(path + ".")
        if owns and len(path) > best_len:
            best, best_len = tree, len(path)
    return best


def _mro_names(model: type) -> set[str]:
    return {klass.__name__ for klass in model.__mro__}


def _column_json(column: object) -> dict[str, object]:
    try:
        type_name = str(column.type)  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - exotic custom types only
        type_name = type(column.type).__name__  # type: ignore[attr-defined]
    return {
        "name": column.name,  # type: ignore[attr-defined]
        "type": type_name,
        "nullable": bool(column.nullable),  # type: ignore[attr-defined]
        "primary_key": bool(column.primary_key),  # type: ignore[attr-defined]
        "unique": bool(column.unique),  # type: ignore[attr-defined]
    }


def _table_json(table: object) -> dict[str, object]:
    return {
        "name": table.name,  # type: ignore[attr-defined]
        "schema": table.schema,  # type: ignore[attr-defined]
        "columns": [_column_json(column) for column in table.columns],  # type: ignore[attr-defined]
        "foreign_keys": sorted(
            (
                {
                    "column": fk.parent.name,
                    "references_table": fk.column.table.name,
                    "references_column": fk.column.name,
                }
                for fk in table.foreign_keys  # type: ignore[attr-defined]
            ),
            key=lambda item: (item["column"], item["references_table"]),
        ),
    }


def _traits_json(model: type) -> dict[str, bool]:
    return {
        "base_table": issubclass(model, BaseTable),
        "soft_delete": issubclass(model, SoftDeleteMixin),
        "owned": issubclass(model, OwnedMixin),
        "tenant_scoped": "TenantScopedMixin" in _mro_names(model),
        "actor_stamped": issubclass(model, ActorStampedMixin),
    }


def scan_declared_table_models(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> dict[tuple[str, str], tuple[str, int]]:
    """Source-scan ground truth: every ``table=True`` class in the app tree.

    Maps ``(class name, dotted module derived from the file path)`` ->
    ``(relative file, line)``. AST-only (nothing is imported), so a model defined
    anywhere in the tree is found even when no sanctioned import path reaches it —
    the reconciliation that makes "never skip a model" checkable. Keying by the
    (class, module) pair means a stray app model cannot hide behind an
    already-mapped capability class of the same name.
    """
    root = pathlib.Path(app_root)
    found: dict[tuple[str, str], tuple[str, int]] = {}
    skip = {"__pycache__", "tests", ".venv", "node_modules", "migrations"}
    for path in sorted(root.rglob("*.py")):
        if any(part in skip for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - unparseable files are the gate's job
            continue
        relative = path.relative_to(root).as_posix()
        # app/modules/x/models.py -> app.modules.x.models (app_root sits on sys.path,
        # so this is the module name the class would carry once imported).
        dotted = relative[: -len(".py")].replace("/", ".")
        if dotted.endswith(".__init__"):  # pragma: no cover - models never live there
            dotted = dotted[: -len(".__init__")]
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            table_kw = any(
                keyword.arg == "table"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            )
            if table_kw:
                found[(node.name, dotted)] = (relative, node.lineno)
    return found


def build_schema_graph(
    trees: Sequence[MigrationTree],
    *,
    mappers: Iterable[object] | None = None,
    metadata_tables: Iterable[object] | None = None,
    source_models: dict[tuple[str, str], tuple[str, int]] | None = None,
) -> dict[str, object]:
    """The Schema Graph as plain data: tables -> ownership -> traits -> alarms.

    ``mappers`` / ``metadata_tables`` default to the live SQLModel registry and
    metadata (the runtime truth); they are injectable so alarm shapes are testable
    without polluting the process-global registry. ``source_models`` is the AST
    ground truth from :func:`scan_declared_table_models`; any scanned model whose
    table never reached the metadata is alarmed under ``unimported_models``.
    """
    live_mappers = (
        mappers if mappers is not None else list(SQLModel._sa_registry.mappers)
    )
    live_tables = (
        metadata_tables
        if metadata_tables is not None
        else sorted(SQLModel.metadata.tables.values(), key=lambda table: table.name)
    )
    tables: list[dict[str, object]] = []
    unowned: list[dict[str, object]] = []
    non_canonical: list[dict[str, object]] = []
    mapped_table_names: set[str] = set()
    mapped_models: set[tuple[str, str]] = set()
    for mapper in sorted(
        live_mappers, key=lambda item: item.local_table.name if item.local_table is not None else ""
    ):
        table = mapper.local_table  # type: ignore[attr-defined]
        model = mapper.class_  # type: ignore[attr-defined]
        if table is None:  # pragma: no cover - non-table mappers only
            continue
        mapped_table_names.add(table.name)
        mapped_models.add((model.__name__, model.__module__))
        tree = _owning_tree(model.__module__, trees)
        entry = {
            **_table_json(table),
            "model": model.__name__,
            "module": tree.label if tree is not None else None,
            "kind": (
                ("capability" if tree.import_path.startswith("terp.") else "app")
                if tree is not None
                else None
            ),
            "traits": _traits_json(model),
        }
        tables.append(entry)
        if tree is None:
            unowned.append(
                {
                    "table": table.name,
                    "model": model.__name__,
                    "model_module": model.__module__,
                    "detail": "no migration tree owns this model's module -- "
                    "terp migrate will never manage its schema",
                }
            )
        # The BaseTable contract is alarmed for the APP's own models (and unowned
        # strays). A capability's non-BaseTable primitive (e.g. the append-only
        # audit event) is the framework's governed territory -- its escape-hatch
        # budget covers it, and the trait stays visible on the table entry.
        if not issubclass(model, BaseTable) and (
            tree is None or not tree.import_path.startswith("terp.")
        ):
            non_canonical.append(
                {
                    "table": table.name,
                    "model": model.__name__,
                    "detail": "does not inherit terp.core.BaseTable -- it bypasses the "
                    "kernel id/timestamps/optimistic-concurrency contract",
                }
            )
    unmapped = [
        {
            "table": table.name,  # type: ignore[attr-defined]
            "detail": "raw Table on the shared metadata with no mapped model class "
            "(hand-rolled DDL outside the model layer)",
        }
        for table in live_tables
        if table.name not in mapped_table_names  # type: ignore[attr-defined]
    ]
    unimported = [
        {
            "model": name,
            "path": location[0],
            "line": location[1],
            "detail": "declared table=True in source but never imported onto the "
            "shared metadata -- invisible to migrations AND to this schema view "
            "until its module is imported from a models.py the app reaches",
        }
        for (name, module), location in sorted((source_models or {}).items())
        if (name, module) not in mapped_models
    ]
    return {
        "tables": tables,
        "unowned_tables": unowned,
        "non_canonical_models": non_canonical,
        "unmapped_tables": unmapped,
        "unimported_models": unimported,
    }


def _render_schema_text(graph: dict[str, object]) -> str:
    lines = ["Schema graph", ""]
    for table in graph["tables"]:  # type: ignore[index, union-attr]
        owner = table["module"] or "<unowned>"
        traits = table["traits"]
        flags = ",".join(
            name
            for name in ("soft_delete", "owned", "tenant_scoped", "actor_stamped")
            if traits[name]
        )
        lines.append(
            f"  {table['name']:24} {owner:12} {table['kind'] or '!':10} "
            f"{table['model']:20} {flags or '-'}"
        )
    for key, header in (
        ("unowned_tables", "! UNOWNED tables (no migration tree manages them):"),
        ("non_canonical_models", "! NON-CANONICAL models (no BaseTable lineage):"),
        ("unmapped_tables", "! UNMAPPED raw tables on the metadata:"),
        ("unimported_models", "! UNIMPORTED table models (declared in source, never loaded):"),
    ):
        entries: list = graph[key]  # type: ignore[assignment]
        if entries:
            lines.append("")
            lines.append(header)
            for entry in entries:
                subject = entry.get("table") or entry.get("model")
                lines.append(f"  {subject}: {entry['detail']}")
    return "\n".join(lines)


def render_schema_graph(graph: dict[str, object], fmt: str = "text") -> str:
    """Render a prebuilt schema *graph* as ``text`` or ``json``."""
    if fmt == "json":
        return json.dumps(graph, indent=2)
    return _render_schema_text(graph)


__all__ = [
    "build_schema_graph",
    "import_declared_models",
    "render_schema_graph",
    "scan_declared_table_models",
]
