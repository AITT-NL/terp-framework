"""The schema window's parts, one at a time, with no server (ADR 0185).

``test_schema_window.py`` proves the window end to end on both dialects. These pin each
part on its own, so the gate that runs without PostgreSQL still exercises the
PostgreSQL-only paths (the catalogue diff, the database search path) through fakes,
and so every branch of the expand list is named by a case of its own.
"""

from __future__ import annotations


import pathlib
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.operations import ops
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

from terp.migrations import _catalogue, _expand, _runtime, orchestrate, window
from terp.migrations._catalogue import Snapshot, judge_catalogue
from terp.migrations._expand import ExpandJudge, ExpandScope, off_list_reason
from terp.migrations.errors import ExpandRevisionError, OrphanedRevisionsError


def _column(name: str, *args: Any, **kw: Any) -> sa.Column:
    return sa.Column(name, sa.Integer(), *args, **kw)


def _fk(target: str, ondelete: str | None) -> sa.ForeignKey:
    return sa.ForeignKey(target, ondelete=ondelete)


# --------------------------------------------------------------------------- #
# The expand list, operation by operation                                       #
# --------------------------------------------------------------------------- #
_NO_SOFT = ExpandScope(soft_delete=lambda table: False)


def _scope(*, soft: set[str] | None = None, created: set[str] | None = None) -> ExpandScope:
    scope = ExpandScope(soft_delete=lambda table: table in (soft or set()))
    scope.created.update(created or set())
    return scope


@pytest.mark.parametrize(
    ("operation", "reason"),
    [
        (ops.CreateTableOp("d", [_column("n", _fk("notes.id", "CASCADE"))]), None),
        (ops.CreateTableOp("d", [_column("n", _fk("notes.id", "set null"))]), None),
        (ops.CreateTableOp("d", [_column("n", _fk("notes.id", "RESTRICT"))]), "needs CASCADE or SET NULL"),
        (ops.CreateTableOp("d", [_column("n", _fk("notes.id", None))]), "no ON DELETE"),
        (
            ops.CreateTableOp(
                "d", [_column("n"), sa.ForeignKeyConstraint(["n"], ["notes.id"], ondelete="SET NULL")]
            ),
            None,
        ),
        (
            ops.CreateTableOp("d", [_column("n"), sa.ForeignKeyConstraint(["n"], ["notes.id"])]),
            "no ON DELETE",
        ),
        (ops.AddColumnOp("notes", _column("r")), None),
        (ops.AddColumnOp("notes", _column("r", nullable=False, server_default="0")), None),
        (ops.AddColumnOp("notes", sa.Column("t", sa.Integer(), sa.Computed("a + b"), nullable=False)), None),
        (ops.AddColumnOp("notes", _column("r", nullable=False)), "NOT NULL with no server_default"),
        (ops.AddColumnOp("notes", _column("r", primary_key=True)), "primary key"),
        (ops.AddColumnOp("notes", _column("r", unique=True)), "unique=True"),
        (ops.AddColumnOp("notes", _column("r", sa.CheckConstraint("r > 0"))), "check constraint"),
        (ops.AddColumnOp("notes", _column("p", _fk("projects.id", "SET NULL"))), None),
        (ops.AddColumnOp("notes", _column("p", _fk("projects.id", "CASCADE"))), "needs SET NULL"),
        (
            ops.AddColumnOp("notes", _column("p", _fk("projects.id", "SET NULL"), nullable=False, server_default="1")),
            "NOT NULL column",
        ),
        (ops.CreateIndexOp("ix", "notes", ["r"]), None),
        (ops.CreateIndexOp("ux", "notes", ["r"], unique=True), "unique index"),
        (ops.BulkInsertOp(sa.table("notes"), []), "did not create"),
        (ops.CreateForeignKeyOp("fk", "notes", "projects", ["p"], ["id"], ondelete="SET NULL"), "did not add nullable"),
        (ops.CreateUniqueConstraintOp("uq", "notes", ["r"]), "create_unique_constraint on the existing"),
        (ops.CreateCheckConstraintOp("ck", "notes", "r > 0"), "create_check_constraint"),
        (ops.CreatePrimaryKeyOp("pk", "notes", ["id"]), "create_primary_key"),
        (ops.ExecuteSQLOp("SELECT 1"), "execute() statement"),
        (ops.DropColumnOp("notes", "r"), "drop_column on 'notes'"),
        (ops.RenameTableOp("notes", "memos"), "rename_table on 'notes'"),
        (ops.DropIndexOp("ix"), "drop_index"),
    ],
)
def test_the_expand_list_operation_by_operation(operation: object, reason: str | None) -> None:
    found = off_list_reason(operation, _scope())
    if reason is None:
        assert found is None
    else:
        assert found is not None and reason in found, found


def test_what_a_revision_creates_or_adds_is_what_later_operations_may_build_on() -> None:
    scope = _scope()
    assert off_list_reason(ops.CreateTableOp("drafts", [_column("id", primary_key=True)]), scope) is None
    for on_the_new_table in (
        ops.AddColumnOp("drafts", _column("r", nullable=False)),
        ops.CreateIndexOp("ux", "drafts", ["r"], unique=True),
        ops.CreateUniqueConstraintOp("uq", "drafts", ["r"]),
        ops.BulkInsertOp(sa.table("drafts"), [{}]),
        ops.CreateForeignKeyOp("fk", "drafts", "notes", ["n"], ["id"], ondelete="CASCADE"),
    ):
        assert off_list_reason(on_the_new_table, scope) is None, on_the_new_table
    assert "CASCADE or SET NULL" in (
        off_list_reason(ops.CreateForeignKeyOp("fk", "drafts", "notes", ["n"], ["id"]), scope) or ""
    )
    # A nullable column the revision added may then carry a SET NULL key, and nothing else.
    assert off_list_reason(ops.AddColumnOp("notes", _column("p")), scope) is None
    over = ops.CreateForeignKeyOp("fk", "notes", "projects", ["p"], ["id"], ondelete="SET NULL")
    assert off_list_reason(over, scope) is None
    cascading = ops.CreateForeignKeyOp("fk", "notes", "projects", ["p"], ["id"], ondelete="CASCADE")
    assert "needs SET NULL" in (off_list_reason(cascading, scope) or "")


def test_neither_action_may_point_at_a_soft_deleted_table() -> None:
    scope = _scope(soft={"notes"})
    for operation in (
        ops.CreateTableOp("d", [_column("n", _fk("notes.id", "CASCADE"))]),
        ops.AddColumnOp("projects", _column("n", _fk("notes.id", "SET NULL"))),
    ):
        assert "soft-deleted" in (off_list_reason(operation, scope) or "")


def test_the_soft_delete_lookup_reads_the_model_metadata() -> None:
    table = sa.Table("sw_soft_target", SQLModel.metadata, sa.Column("id", sa.Integer), sa.Column("deleted_at", sa.DateTime))
    try:
        assert _expand.is_soft_delete_table("sw_soft_target") is True
        assert _expand.is_soft_delete_table("sw_no_such_table") is False
        assert _expand._target_table("public.sw_soft_target.id") == "sw_soft_target"
        assert _expand._target_table("bare") == "bare"
    finally:
        SQLModel.metadata.remove(table)


def test_make_says_where_raising_the_mark_is_possible_only_for_generated_operations() -> None:
    nested = ops.UpgradeOps(
        [ops.ModifyTableOps("notes", [ops.AddColumnOp("notes", _column("r"))]), ops.CreateIndexOp("ix", "notes", ["r"])]
    )
    assert _expand.generated_operations_on_list(nested) is True
    assert _expand.generated_operations_on_list(ops.UpgradeOps([])) is False
    assert _expand.generated_operations_on_list(ops.UpgradeOps([ops.DropColumnOp("notes", "r")])) is False


def test_the_note_is_left_out_when_the_command_carries_no_template() -> None:
    _runtime._note_the_expand_list(SimpleNamespace(opts={}), None, [])
    template: dict[str, object] = {}
    directive = SimpleNamespace(upgrade_ops_list=[ops.UpgradeOps([ops.CreateIndexOp("ix", "n", ["r"])])])
    _runtime._note_the_expand_list(SimpleNamespace(opts={"template_args": template}), None, [directive])
    assert template == {"terp_expand_note": True}


# --------------------------------------------------------------------------- #
# The judge: its hooks, and the catalogue path, through fakes                    #
# --------------------------------------------------------------------------- #
class _Rows:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _Catalogue:
    """A connection that answers the catalogue queries from canned rows."""

    def __init__(self, **tables: list[tuple[Any, ...]]) -> None:
        self.tables = tables

    def exec_driver_sql(self, query: str) -> _Rows:
        for marker, key in (
            ("c.relkind, c.relrowsecurity", "relations"),
            ("format_type(a.atttypid", "columns"),
            ("pg_get_indexdef", "indexes"),
            ("pg_get_constraintdef", "constraints"),
            ("pg_get_triggerdef", "triggers"),
            ("FROM pg_policies", "policies"),
            ("string_agg(e.enumlabel", "enums"),
        ):
            if marker in query:
                return _Rows(self.tables.get(key, []))
        raise AssertionError(query)  # pragma: no cover - every query is one of the above


_NOTE = {
    "relations": [("public", "note", "r", False, False)],
    "columns": [("public", "note", "id", "integer", True, None, "", "")],
    "indexes": [("public", "note_pkey", "note", True, "CREATE UNIQUE INDEX note_pkey ...")],
    "constraints": [("public", "note", "note_pkey", "p", "PRIMARY KEY (id)", " ", None, ["id"])],
}


def _with(**extra: list[tuple[Any, ...]]) -> Snapshot:
    tables = {key: list(rows) for key, rows in _NOTE.items()}
    for key, rows in extra.items():
        tables[key] = [*tables.get(key, []), *rows]
    return _catalogue.snapshot(_Catalogue(**tables))


def test_the_catalogue_snapshot_reads_every_kind_of_object() -> None:
    snap = _with(
        triggers=[("public", "note", "t", "CREATE TRIGGER t ...")],
        policies=[("public", "note", "p", "PERMISSIVE | {public} | ALL")],
        enums=[("public", "mood", "ok,bad")],
    )
    assert ("public", "note") in snap.relations
    assert snap.constraints[("public", "note", "note_pkey")][-1] == ("id",)
    assert snap.triggers and snap.policies and snap.enums


_ADDED = {
    "nothing": ({}, None),
    "a nullable column": ({"columns": [("public", "note", "r", "integer", False, None, "", "")]}, None),
    "a defaulted column": ({"columns": [("public", "note", "r", "integer", True, "0", "", "")]}, None),
    "a generated column": ({"columns": [("public", "note", "r", "integer", True, None, "s", "")]}, None),
    "a NOT NULL column": (
        {"columns": [("public", "note", "r", "integer", True, None, "", "")]},
        "NOT NULL with no default",
    ),
    "an identity column": (
        {"columns": [("public", "note", "r", "integer", True, None, "", "a")]},
        "NOT NULL with no default",
    ),
    "a non-unique index": ({"indexes": [("public", "ix", "note", False, "CREATE INDEX ix ...")]}, None),
    "a unique index": ({"indexes": [("public", "ux", "note", True, "CREATE UNIQUE INDEX ux ...")]}, "unique index"),
    "a SET NULL key over an added nullable column": (
        {
            "columns": [("public", "note", "p", "integer", False, None, "", "")],
            "constraints": [("public", "note", "fk", "f", "FOREIGN KEY (p) ...", "n", "public.project", ["p"])],
        },
        None,
    ),
    "a CASCADE key on an existing table": (
        {
            "columns": [("public", "note", "p", "integer", False, None, "", "")],
            "constraints": [("public", "note", "fk", "f", "FOREIGN KEY (p) ...", "c", "public.project", ["p"])],
        },
        "added the constraint",
    ),
    "a PostgreSQL 18 NOT NULL of an added column": (
        {
            "columns": [("public", "note", "r", "integer", True, "0", "", "")],
            "constraints": [("public", "note", "nn", "n", "NOT NULL r", " ", None, ["r"])],
        },
        None,
    ),
    "a check on an existing table": (
        {"constraints": [("public", "note", "ck", "c", "CHECK (id > 0)", " ", None, ["id"])]},
        "added the constraint",
    ),
    "a new table with its own unique index and cascading key": (
        {
            "relations": [("public", "draft", "r", False, False)],
            "columns": [("public", "draft", "n", "integer", True, None, "", "")],
            "indexes": [("public", "ux_d", "draft", True, "CREATE UNIQUE INDEX ux_d ...")],
            "constraints": [("public", "draft", "fk", "f", "FOREIGN KEY (n) ...", "c", "public.note", ["n"])],
        },
        None,
    ),
    "a new table with a RESTRICT key": (
        {
            "relations": [("public", "draft", "r", False, False)],
            "constraints": [("public", "draft", "fk", "f", "FOREIGN KEY (n) ...", "r", "public.note", ["n"])],
        },
        "neither CASCADE nor SET NULL",
    ),
    "a key onto a soft-deleted table": (
        {
            "relations": [("public", "draft", "r", False, False)],
            "columns": [("public", "note", "deleted_at", "timestamp", False, None, "", "")],
            "constraints": [("public", "draft", "fk", "f", "FOREIGN KEY (n) ...", "c", "public.note", ["n"])],
        },
        "soft-deleted",
    ),
    "a view": ({"relations": [("public", "v", "v", False, False)]}, "which is not a table"),
    "a trigger": ({"triggers": [("public", "note", "t", "CREATE TRIGGER t ...")]}, "created the trigger"),
    "a policy": ({"policies": [("public", "note", "p", "...")]}, "created the policy"),
    "an enum type": ({"enums": [("public", "mood", "ok")]}, None),
}


@pytest.mark.parametrize(("extra", "refusal"), list(_ADDED.values()), ids=list(_ADDED))
def test_what_an_expand_step_may_add_to_the_catalogue(
    extra: dict[str, list[tuple[Any, ...]]], refusal: str | None
) -> None:
    found = judge_catalogue(_with(), _with(**extra))
    if refusal is None:
        assert found is None, found
    else:
        assert found is not None and refusal in found, found


def test_nothing_may_be_removed_or_changed() -> None:
    before = _with(enums=[("public", "mood", "ok")])
    assert "removed the relation public.note" in (judge_catalogue(before, _catalogue.snapshot(_Catalogue())) or "")
    changed = _with(enums=[("public", "mood", "ok,later")])
    assert "changed the enum type public.mood" in (judge_catalogue(before, changed) or "")


def test_the_judge_reads_the_catalogue_before_and_after_an_expand_step() -> None:
    judge = ExpandJudge("notes", catalogue=True)
    judge._connection = _Catalogue(**_NOTE)
    module = SimpleNamespace(expand_only=True)
    script = SimpleNamespace(module=module, revision="e1", _normalized_down_revisions=("r1",))
    with judge.revision(script):
        pass
    assert judge.finish("other") is None  # a step it did not see start: a stamp
    assert judge.finish("e1") is True
    # The same step, ending on a catalogue with a unique index on an existing table.
    with judge.revision(script):
        judge._connection = _Catalogue(
            **{**_NOTE, "indexes": [*_NOTE["indexes"], ("public", "ux", "note", True, "...")]}
        )
    with pytest.raises(ExpandRevisionError, match="rolled back with the package's upgrade"):
        judge.finish("e1")


def test_the_judge_passes_through_what_it_does_not_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    judge = ExpandJudge("notes", catalogue=False)
    with judge.admitted():  # no step yet: nothing to count
        pass
    judge.statement("SELECT 1")
    judge.batch("note", "always")
    assert judge.invoke(ops.DropColumnOp("note", "r"), lambda: "ran") == "ran"
    # The patched dispatch defers to Alembic's own whenever no judge is active (another
    # thread, or no run at all).
    monkeypatch.setattr(_expand, "_ORIGINAL_INVOKE", lambda self, operation: ("invoked", operation))
    monkeypatch.setattr(_expand, "_ORIGINAL_FLUSH", lambda self: "flushed")
    assert _expand._judged_invoke(object(), "op") == ("invoked", "op")
    assert _expand._judged_flush(object()) == "flushed"


def test_a_contract_revision_is_never_judged() -> None:
    judge = ExpandJudge("notes", catalogue=False)
    script = SimpleNamespace(
        module=SimpleNamespace(expand_only=False), revision="c1", _normalized_down_revisions=("a", "b")
    )
    with judge.revision(script):
        judge.statement("DROP TABLE note")
    assert judge.finish("c1") is False


def test_a_wrapped_revision_is_wrapped_once() -> None:
    def upgrade() -> str:
        return "ran"

    module = SimpleNamespace(upgrade=upgrade, expand_only=True)
    script = SimpleNamespace(module=module, revision="e1", _normalized_down_revisions=("r1",))
    judge = ExpandJudge("notes", catalogue=False)
    judge.wrap(script)
    wrapped = module.upgrade
    judge.wrap(script)
    assert module.upgrade is wrapped and module.upgrade() == "ran"
    judge.wrap(SimpleNamespace(module=SimpleNamespace(), revision="x"))  # no upgrade(): left alone


# --------------------------------------------------------------------------- #
# The record and the window, piece by piece                                      #
# --------------------------------------------------------------------------- #
def test_the_heads_digest_is_canonical() -> None:
    assert window.heads_digest({"b": ["2", "1"], "a": ["x"]}) == window.heads_digest(
        {"a": ["x"], "b": ["1", "2"]}
    )
    assert len(window.heads_digest({})) == 64


def test_the_retired_list_is_empty_where_there_is_none(tmp_path: pathlib.Path) -> None:
    assert window.read_retired_migrations(None) == window.TERP_RETIRED_MIGRATIONS
    assert window.read_retired_migrations(tmp_path) == ()  # no modules/__init__.py
    (tmp_path / "modules").mkdir()
    (tmp_path / "modules" / "__init__.py").write_text('"""Modules."""\n', encoding="utf-8")
    assert window.read_retired_migrations(tmp_path) == ()
    (tmp_path / "modules" / "__init__.py").write_text(
        'RETIRED_MIGRATIONS: tuple[str, ...] = ("a", "b", "a")\n', encoding="utf-8"
    )
    assert window.read_retired_migrations(tmp_path) == ("a", "b")


def _sqlite(tmp_path: pathlib.Path) -> sa.Engine:
    return create_engine(f"sqlite:///{(tmp_path / 'w.db').as_posix()}", poolclass=NullPool)


def test_a_record_the_code_cannot_read_reads_as_none(tmp_path: pathlib.Path) -> None:
    engine = _sqlite(tmp_path)
    with engine.begin() as connection:
        assert window.read_record(connection) is None
        window.delete_record_rows(connection, "notes", revisions=["x"])  # no record: nothing
        connection.execute(text("CREATE TABLE gone (x INTEGER)"))
        connection.execute(text("CREATE VIEW terp_migration_window AS SELECT * FROM gone"))
        connection.execute(text("DROP TABLE gone"))
    with engine.connect() as connection:
        assert window.read_record(connection) is None
    engine.dispose()


def test_rows_below_the_horizon_are_ignored_and_foreign_rows_above_it_admitted(
    tmp_path: pathlib.Path,
) -> None:
    engine = _sqlite(tmp_path)
    history = window.CodeHistory("notes", ("b",), frozenset({"a", "b"}), "alembic_version_notes")

    def row(connection: Any, label: str, revision: str, kind: str, by: str) -> None:
        window.write_record_row(
            connection, label=label, revision=revision, parent=None, kind=kind,
            applied_by=by, applied_terp=window.terp_version(),
        )

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version_notes (version_num VARCHAR(32))"))
        connection.execute(text("INSERT INTO alembic_version_notes VALUES ('b')"))
        row(connection, "gone", "g1", "contract", "older")  # already there when we migrated
        row(connection, "notes", "b", "contract", "own")  # this code's own run
        row(connection, "fresh", "f1", "expand", "newest")  # a newer release's new history
    with engine.connect() as connection:
        found = window.judge_window(connection, [history], "own", retired=())
    assert found.foreign == {"fresh": ("f1",)}
    assert found.current == {"notes": ("b",)}
    engine.dispose()


def test_a_walk_through_a_cycle_is_refused(tmp_path: pathlib.Path) -> None:
    history = window.CodeHistory("notes", ("a",), frozenset({"a"}), "alembic_version_notes")
    crossed, refusal = window._walk("x", history, {"x": "y", "y": "x"})
    assert crossed == ("x", "y") and refusal is not None and "rewritten" in refusal


def test_the_classic_orphan_message_stands_without_reasons() -> None:
    message = str(OrphanedRevisionsError({"notes": ["x1"]}))
    assert "rewritten or deleted" in message and "terp migrate stamp" in message


def test_the_preflight_by_its_old_name_is_the_window(tmp_path: pathlib.Path) -> None:
    url = f"sqlite:///{(tmp_path / 'o.db').as_posix()}"
    orchestrate.assert_no_orphaned_revisions(url)  # an empty database is inside


# --------------------------------------------------------------------------- #
# The search path only grows                                                     #
# --------------------------------------------------------------------------- #
def test_the_search_path_is_the_union_and_nothing_is_sent_when_nothing_is_missing() -> None:
    statements = orchestrate.database_search_path_statements(
        "appdb", ["audit", "notes"], current=["notes", "extra", "public"], schemas={"notes", "extra"}
    )
    assert statements == [
        'CREATE SCHEMA IF NOT EXISTS "audit"',
        'ALTER DATABASE "appdb" SET search_path TO "notes", "extra", "audit", "public"',
    ]
    assert (
        orchestrate.database_search_path_statements(
            "appdb", ["notes"], current=["extra", "notes", "public"], schemas={"notes"}
        )
        == []
    )


class _Setting:
    def __init__(self, setconfig: list[str] | None) -> None:
        self.setconfig = setconfig

    def exec_driver_sql(self, statement: str) -> Any:
        rows = [] if self.setconfig is None else [(self.setconfig,)]
        return SimpleNamespace(first=lambda: rows[0] if rows else None)


def test_the_database_setting_is_read_entry_by_entry() -> None:
    assert orchestrate._database_search_path(_Setting(None)) is None
    assert orchestrate._database_search_path(_Setting(["work_mem=4MB"])) is None
    assert orchestrate._database_search_path(_Setting(['search_path="notes", audit, public'])) == [
        "notes",
        "audit",
        "public",
    ]


def test_an_existing_package_schema_is_not_created_again() -> None:
    sent: list[str] = []

    class _Existing:
        dialect = SimpleNamespace(name="postgresql", default_schema_name="public")

        def execute(self, statement: object, params: object = None) -> Any:
            return SimpleNamespace(first=lambda: (1,))

        def exec_driver_sql(self, statement: str) -> None:
            sent.append(statement)

        def commit(self) -> None:
            pass

    _runtime._enter_per_module_schema(_Existing(), "notes", ["notes"])
    assert sent == ['SET search_path TO "notes", "public"']


def test_the_cli_upgrade_answers_a_refusal_with_exit_1(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from terp.migrations import cli

    def refuse(*args: object, **kwargs: object) -> None:
        raise ExpandRevisionError("notes", "e1", "drop_column")

    monkeypatch.setattr(cli, "upgrade", refuse)
    with pytest.raises(SystemExit) as exited:
        cli.migrate_main(["upgrade", "--database-url", f"sqlite:///{(tmp_path / 'c.db').as_posix()}"])
    assert exited.value.code == 1
    assert "drop_column" in capsys.readouterr().err



