"""What an expand-only step left, read from PostgreSQL's own catalogue (ADR 0185 decision 1).

The operation and statement checks judge what a revision *asks* for. A batch block's
flush can still rebuild its table, and a rebuild is exactly the step that loses a
partial index's predicate or a check constraint's text without asking. So, online, the
run also reads the catalogue before and after each expand-only step and refuses a
difference the expand list does not admit.

The reads go to the server's own renderers (``format_type``, ``pg_get_indexdef``,
``pg_get_constraintdef``, ``pg_get_triggerdef``), never to SQLAlchemy reflection, for
the reason ``assert_migrations_reverse_cleanly`` gives: reflection is the layer that
loses the two things a rebuild loses. They span every schema, not only the current
one, and add triggers, row-level security policies and enum types to the guard's
columns, indexes and constraints. The bookkeeping tables (``alembic_version_*`` and the
window record) are left out, so the first step does not count the record's creation.

PostgreSQL only. SQLite keeps a table's constraints only inside the text of its
``CREATE TABLE``, so there is no catalogue to diff by object; there the operation and
statement checks stand alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Each query is one literal, with no ``%`` anywhere: it goes to the driver as written, and a
# pyformat driver reads ``%`` as a placeholder. Every one leaves out the system schemas.
_RELATIONS = (
    "SELECT n.nspname, c.relname, c.relkind, c.relrowsecurity, c.relforcerowsecurity"
    " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
    " WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')"
    " AND n.nspname NOT IN ('pg_catalog', 'information_schema')"
    " AND NOT starts_with(n.nspname, 'pg_toast') AND NOT starts_with(n.nspname, 'pg_temp')"
)
_COLUMNS = (
    "SELECT n.nspname, c.relname, a.attname, format_type(a.atttypid, a.atttypmod),"
    " a.attnotnull, pg_get_expr(d.adbin, d.adrelid), a.attgenerated, a.attidentity"
    " FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid"
    " JOIN pg_namespace n ON n.oid = c.relnamespace"
    " LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum"
    " WHERE a.attnum > 0 AND NOT a.attisdropped AND c.relkind IN ('r', 'p', 'v', 'm', 'f')"
    " AND n.nspname NOT IN ('pg_catalog', 'information_schema')"
    " AND NOT starts_with(n.nspname, 'pg_toast') AND NOT starts_with(n.nspname, 'pg_temp')"
)
_INDEXES = (
    "SELECT n.nspname, i.relname, t.relname, x.indisunique, pg_get_indexdef(x.indexrelid)"
    " FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid"
    " JOIN pg_class t ON t.oid = x.indrelid JOIN pg_namespace n ON n.oid = i.relnamespace"
    " WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')"
    " AND NOT starts_with(n.nspname, 'pg_toast') AND NOT starts_with(n.nspname, 'pg_temp')"
)
_CONSTRAINTS = (
    "SELECT n.nspname, t.relname, con.conname, con.contype, pg_get_constraintdef(con.oid),"
    " con.confdeltype, fn.nspname || '.' || ft.relname,"
    " ARRAY(SELECT a.attname FROM pg_attribute a WHERE a.attrelid = con.conrelid"
    "  AND a.attnum = ANY(con.conkey) ORDER BY a.attname)"
    " FROM pg_constraint con JOIN pg_class t ON t.oid = con.conrelid"
    " JOIN pg_namespace n ON n.oid = t.relnamespace"
    " LEFT JOIN pg_class ft ON ft.oid = con.confrelid"
    " LEFT JOIN pg_namespace fn ON fn.oid = ft.relnamespace"
    " WHERE con.conrelid <> 0 AND n.nspname NOT IN ('pg_catalog', 'information_schema')"
    " AND NOT starts_with(n.nspname, 'pg_toast') AND NOT starts_with(n.nspname, 'pg_temp')"
)
_TRIGGERS = (
    "SELECT n.nspname, c.relname, tg.tgname, pg_get_triggerdef(tg.oid)"
    " FROM pg_trigger tg JOIN pg_class c ON c.oid = tg.tgrelid"
    " JOIN pg_namespace n ON n.oid = c.relnamespace"
    " WHERE NOT tg.tgisinternal AND n.nspname NOT IN ('pg_catalog', 'information_schema')"
)
_POLICIES = (
    "SELECT schemaname, tablename, policyname,"
    " concat_ws(' | ', permissive, roles::text, cmd, qual, with_check) FROM pg_policies"
)
_ENUMS = (
    "SELECT n.nspname, t.typname, string_agg(e.enumlabel, ',' ORDER BY e.enumsortorder)"
    " FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid"
    " JOIN pg_namespace n ON n.oid = t.typnamespace"
    " WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') GROUP BY 1, 2"
)


def _bookkeeping(schema: str, table: str) -> bool:
    """The tables outside every history: the version tables and the window record."""
    return schema == "public" and (
        table.startswith("alembic_version_") or table == "terp_migration_window"
    )


@dataclass(frozen=True)
class Snapshot:
    """The parts of a PostgreSQL catalogue an expand step may and may not change."""

    relations: dict[tuple[str, str], tuple[Any, ...]] = field(default_factory=dict)
    columns: dict[tuple[str, str, str], tuple[Any, ...]] = field(default_factory=dict)
    indexes: dict[tuple[str, str], tuple[Any, ...]] = field(default_factory=dict)
    constraints: dict[tuple[str, str, str], tuple[Any, ...]] = field(default_factory=dict)
    triggers: dict[tuple[str, str, str], str] = field(default_factory=dict)
    policies: dict[tuple[str, str, str], str] = field(default_factory=dict)
    enums: dict[tuple[str, str], str] = field(default_factory=dict)


def snapshot(connection: Any) -> Snapshot:
    """Read the catalogue through *connection*, inside whatever transaction it holds."""

    def rows(query: str) -> list[tuple[Any, ...]]:
        return [tuple(row) for row in connection.exec_driver_sql(query).all()]

    return Snapshot(
        relations={
            (r[0], r[1]): tuple(r[2:]) for r in rows(_RELATIONS) if not _bookkeeping(r[0], r[1])
        },
        columns={
            (r[0], r[1], r[2]): tuple(r[3:])
            for r in rows(_COLUMNS)
            if not _bookkeeping(r[0], r[1])
        },
        indexes={
            (r[0], r[1]): tuple(r[2:]) for r in rows(_INDEXES) if not _bookkeeping(r[0], r[2])
        },
        constraints={
            (r[0], r[1], r[2]): (*r[3:7], tuple(r[7]))
            for r in rows(_CONSTRAINTS)
            if not _bookkeeping(r[0], r[1])
        },
        triggers={(r[0], r[1], r[2]): str(r[3]) for r in rows(_TRIGGERS)},
        policies={(r[0], r[1], r[2]): str(r[3]) for r in rows(_POLICIES)},
        enums={(r[0], r[1]): str(r[2]) for r in rows(_ENUMS)},
    )


def _changed(before: dict[Any, Any], after: dict[Any, Any], kind: str) -> str | None:
    for key in sorted(before, key=str):
        if key not in after:
            return f"the step removed {kind} {'.'.join(key)}"
        if after[key] != before[key]:
            return f"the step changed {kind} {'.'.join(key)}"
    return None


def judge_catalogue(before: Snapshot, after: Snapshot) -> str | None:
    """What *after* holds that the expand list does not admit over *before*, or ``None``.

    Nothing may be removed or changed. What may be added is what the list admits: a new
    table with everything that is its own (a foreign key from it carrying ``CASCADE`` or
    ``SET NULL`` onto a table that is not soft-deleted), and on an existing table a column
    that is nullable, has a default or is generated, a non-unique index, and a ``SET
    NULL`` foreign key over added nullable columns; a new enum type too. No trigger,
    policy or view may appear at all, because no operation on the list creates one.
    """
    for kind, field_name in (
        ("the relation", "relations"),
        ("the column", "columns"),
        ("the index", "indexes"),
        ("the constraint", "constraints"),
        ("the trigger", "triggers"),
        ("the policy", "policies"),
        ("the enum type", "enums"),
    ):
        refusal = _changed(getattr(before, field_name), getattr(after, field_name), kind)
        if refusal:
            return refusal

    new_tables: set[tuple[str, str]] = set()
    for key, (relkind, *_rest) in after.relations.items():
        if key in before.relations:
            continue
        if relkind not in ("r", "p"):
            return f"the step created {'.'.join(key)}, which is not a table"
        new_tables.add(key)

    added: dict[tuple[str, str], dict[str, bool]] = {}
    for key, (_type, notnull, default, generated, identity) in after.columns.items():
        if key in before.columns or key[:2] in new_tables:
            continue
        if identity or not (not notnull or default is not None or generated):
            return (
                f"the step added the column {'.'.join(key)} NOT NULL with no default to "
                "an existing table"
            )
        added.setdefault(key[:2], {})[key[2]] = not notnull

    for key, (table, unique, _definition) in after.indexes.items():
        if key in before.indexes or (key[0], table) in new_tables:
            continue
        if unique:
            return f"the step added the unique index {'.'.join(key)} to an existing table"

    soft = {
        f"{schema}.{table}"
        for (schema, table, column) in after.columns
        if column == "deleted_at"
    }
    for key, (contype, _definition, deltype, target, columns) in after.constraints.items():
        if key in before.constraints:
            continue
        table = key[:2]
        if table in new_tables:
            if contype == "f" and (deltype not in ("c", "n") or target in soft):
                return (
                    f"the step added the foreign key {'.'.join(key)} from a new table "
                    "with neither CASCADE nor SET NULL, or onto a soft-deleted table"
                )
            continue
        nullable_added = added.get(table, {})
        if contype == "f" and deltype == "n" and target not in soft and columns and all(
            nullable_added.get(column) for column in columns
        ):
            continue
        if contype == "n" and columns and all(column in nullable_added for column in columns):
            continue  # PostgreSQL 18 records NOT NULL as a constraint of the added column
        return f"the step added the constraint {'.'.join(key)} to an existing table"

    for kind, field_name in (
        ("trigger", "triggers"),
        ("policy", "policies"),
    ):
        for key in getattr(after, field_name):
            if key not in getattr(before, field_name):
                return f"the step created the {kind} {'.'.join(key)}"
    return None


__all__ = ["Snapshot", "judge_catalogue", "snapshot"]
