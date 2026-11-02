"""ADR 0185: a release declares the schema window it accepts, and the proofs that it holds.

Each test builds releases the way a deployment meets them: an app root per release, its
own package name (so two releases never share an imported module), one module history
``wnotes`` they share, and the installed capabilities every release runs. A release that
"runs" here does exactly what its image would: ``terp migrate upgrade`` as its migration
step, ``assert_migrations_current`` as its boot guard (armed, as in production), and
``terp migrate check`` as the rollback check a deploy tool runs from the target's image.

Most proofs run on both verified dialects through ``terp_db_url``; the ones the ADR puts
on the PostgreSQL lane (the catalogue diff, the per-module layout, the runtime role) take
``terp_pg_url``. CI's PostgreSQL lane runs this module with the flag that turns a skip
into a failure.
"""

from __future__ import annotations

import contextlib
import logging
import os
import pathlib
import re
import subprocess
import sys
import textwrap
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from alembic import command
from sqlalchemy import (
    Column,
    Engine,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    event,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.pool import NullPool

from terp.core.migrations import resolve_migration_trees
from terp.migrations import (
    ExpandRevisionError,
    OrphanedRevisionsError,
    PendingMigrationsError,
    RetiredMigrationsError,
    _runtime,
    assert_migrations_current,
    downgrade,
    grant_runtime_role,
    make,
    orchestrate,
    read_record,
    stamp,
    upgrade,
    upgrade_sql,
)
from terp.migrations._config import alembic_config_for
from terp.migrations.cli import migrate_main
from terp.migrations.window import RECORD_TABLE, terp_version

LABEL = "wnotes"


@dataclass(frozen=True)
class Rev:
    """One revision file: id, parent, upgrade body, downgrade body, and its mark."""

    rid: str
    parent: str | tuple[str, ...] | None
    up: str
    down: str = "pass"
    expand: bool | None = None


R1 = Rev(
    "r1",
    None,
    "op.create_table('wnote', sa.Column('id', sa.Integer(), primary_key=True),"
    " sa.Column('title', sa.String(50), nullable=True))",
    "op.drop_table('wnote')",
)
# N's expand step, written the batch way, as autogenerate writes it on SQLite.
E1 = Rev(
    "e1",
    "r1",
    "with op.batch_alter_table('wnote') as batch_op:\n"
    "    batch_op.add_column(sa.Column('rank', sa.Integer(), nullable=True))",
    "with op.batch_alter_table('wnote') as batch_op:\n    batch_op.drop_column('rank')",
    expand=True,
)
E2 = Rev(
    "e2",
    "e1",
    "op.create_index('ix_wnote_rank', 'wnote', ['rank'], unique=False)",
    "op.drop_index('ix_wnote_rank', table_name='wnote')",
    expand=True,
)
C2 = Rev(
    "c2",
    "e1",
    "op.execute('UPDATE wnote SET rank = 0 WHERE rank IS NULL')\n"
    "with op.batch_alter_table('wnote') as batch_op:\n"
    "    batch_op.alter_column('rank', existing_type=sa.Integer(), nullable=False)",
    "with op.batch_alter_table('wnote') as batch_op:\n"
    "    batch_op.alter_column('rank', existing_type=sa.Integer(), nullable=True)",
)
X1 = Rev(
    "x1",
    None,
    "op.create_table('wextra', sa.Column('id', sa.Integer(), primary_key=True))",
    "op.drop_table('wextra')",
)


@dataclass(frozen=True)
class Release:
    """One release's code: its app root and the package it is imported as."""

    root: pathlib.Path
    package: str

    def upgrade(self, url: str, **kw: object) -> list[str]:
        return upgrade(url, self.root, package=self.package, **kw)

    def boot(self, url: str) -> None:
        """The boot guard, armed as the template arms it in production."""
        engine = create_engine(url, poolclass=NullPool)
        try:
            assert_migrations_current(engine, self.root, package=self.package)
        finally:
            engine.dispose()

    def check(self, url: str) -> int:
        """``terp migrate check`` from this release: the rollback classification."""
        try:
            migrate_main(
                ["check", "--database-url", url, "--app-root", str(self.root), "--package", self.package]
            )
        except SystemExit as exc:
            return int(exc.code or 0)
        return 0

    def digest(self, url: str) -> str:
        return orchestrate.run_digest(orchestrate._code_histories(url, self.root, self.package))


def _revision_source(rev: Rev) -> str:
    mark = "" if rev.expand is None else f"expand_only = {rev.expand}\n"
    return (
        f"revision = {rev.rid!r}\ndown_revision = {rev.parent!r}\nbranch_labels = None\n"
        f"depends_on = None\n{mark}\n"
        "from alembic import op\nimport sqlalchemy as sa\n\n\n"
        f"def upgrade():\n{textwrap.indent(rev.up, '    ')}\n\n\n"
        f"def downgrade():\n{textwrap.indent(rev.down, '    ')}\n"
    )


@pytest.fixture
def release(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Write a release: ``release(wnotes=[R1, E1], wextra=[X1], retired=...)``."""
    monkeypatch.syspath_prepend(str(tmp_path))

    def build(retired: str | None = None, models: str = "", **modules: list[Rev]) -> Release:
        package = f"swr{uuid.uuid4().hex[:10]}"
        root = tmp_path / package
        (root / "modules").mkdir(parents=True)
        (root / "__init__.py").write_text("", encoding="utf-8")
        (root / "modules" / "__init__.py").write_text(retired or "", encoding="utf-8")
        for label, revisions in modules.items():
            module = root / "modules" / label
            versions = module / "migrations" / "versions"
            versions.mkdir(parents=True)
            (module / "__init__.py").write_text("", encoding="utf-8")
            (module / "models.py").write_text(models if label == LABEL else "", encoding="utf-8")
            for rev in revisions:
                (versions / f"{rev.rid}.py").write_text(_revision_source(rev), encoding="utf-8")
        return Release(root, package)

    return build


@pytest.fixture
def db_url(terp_db_url: str) -> str:
    return terp_db_url


@pytest.fixture
def pg_url(terp_pg_url: str) -> str:
    return terp_pg_url


def _rows(url: str, label: str = LABEL) -> list:
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return sorted(
                (row for row in read_record(connection) or [] if row.label == label),
                key=lambda row: row.seq,
            )
    finally:
        engine.dispose()


def _scalar(url: str, sql: str) -> object:
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return connection.execute(text(sql)).scalar()
    finally:
        engine.dispose()


def _columns(url: str, table: str) -> set[str]:
    engine = create_engine(url, poolclass=NullPool)
    try:
        return {column["name"] for column in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


_WRITES = re.compile(
    r"^\s*(CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|TRUNCATE|GRANT|REVOKE|COMMENT|SET\s+search_path)\b",
    re.IGNORECASE,
)


@contextlib.contextmanager
def _statements() -> Iterator[list[str]]:
    """Every statement any engine sends while the block runs."""
    seen: list[str] = []

    def record(conn: object, cursor: object, statement: str, *rest: object) -> None:
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(Engine, "before_cursor_execute", record)


# --------------------------------------------------------------------------- #
# Decision 2: the record                                                       #
# --------------------------------------------------------------------------- #
def test_every_applied_revision_is_recorded_with_the_run_that_applied_it(db_url: str, release) -> None:
    n = release(wnotes=[R1, E1])
    n.upgrade(db_url)
    rows = _rows(db_url)
    assert [(row.revision, row.parent, row.kind) for row in rows] == [
        ("r1", None, "contract"),
        ("e1", "r1", "expand"),
    ]
    # No option and no variable: the run's own heads and its own Terp version.
    assert {row.applied_by for row in rows} == {n.digest(db_url)}
    assert {row.applied_terp for row in rows} == {terp_version()}
    assert rows[0].seq < rows[1].seq
    # Every capability history the run applied is recorded the same way.
    assert {row.label for row in _rows_all(db_url)} >= {
        tree.label for tree in resolve_migration_trees(n.root, package=n.package)
    }


def _rows_all(url: str) -> list:
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return read_record(connection) or []
    finally:
        engine.dispose()


def test_the_record_carries_the_same_digest_however_the_step_is_run(db_url: str, release) -> None:
    # The orchestrator passes the digest down; a bare Alembic command over one package's
    # config reads it from the same revision files, and the CLI is the orchestrator.
    n = release(wnotes=[R1, E1])
    for tree in resolve_migration_trees(n.root, package=n.package):
        if tree.label != LABEL:
            continue
        command.upgrade(alembic_config_for(tree, db_url, app_root=n.root, package=n.package), "r1")
    migrate_main(
        ["upgrade", "--database-url", db_url, "--app-root", str(n.root), "--package", n.package]
    )
    assert {row.applied_by for row in _rows(db_url)} == {n.digest(db_url)}


def test_downgrade_deletes_and_stamp_clears_the_rows_above(db_url: str, release) -> None:
    n = release(wnotes=[R1, E1, E2])
    n.upgrade(db_url)
    downgrade(db_url, n.root, package=n.package, label=LABEL, revision="r1")
    assert [row.revision for row in _rows(db_url)] == ["r1"]

    n.upgrade(db_url)  # a revision applied again replaces its row
    assert [row.revision for row in _rows(db_url)] == ["r1", "e1", "e2"]

    # A recovery stamp writes none and clears what it moves past, so a revision applied
    # again after it meets no stale row, and a stamped database never opens a window.
    stamp(db_url, n.root, package=n.package, revision="base")
    assert _rows(db_url) == []
    stamp(db_url, n.root, package=n.package, revision="head")
    assert _rows(db_url) == []


def test_offline_sql_writes_no_record(release) -> None:
    # A release applied from a script leaves revisions the record does not hold, so it
    # rolls back by restore: the guard refuses to walk them (ADR 0072, decision 2).
    n = release(wnotes=[R1, E1])
    script = upgrade_sql("postgresql+psycopg://u:p@h/db", n.root, package=n.package)
    assert "ALTER TABLE wnote ADD COLUMN rank" in script
    assert RECORD_TABLE not in script


# --------------------------------------------------------------------------- #
# Decision 1, the runtime half: the run holds a raised mark to the list         #
# --------------------------------------------------------------------------- #
_OFF_LIST = {
    "a drop": ("op.drop_column('wnote', 'title')", "drop_column"),
    "a tightening": ("op.alter_column('wnote', 'title', existing_type=sa.String(50), nullable=False)", "alter_column"),
    "execute": ("op.execute(\"UPDATE wnote SET title = 'x'\")", "execute() statement"),
    "a statement through get_bind": (
        "op.get_bind().execute(sa.text(\"UPDATE wnote SET title = 'x'\"))",
        "a statement sent outside an operation",
    ),
    "a unique index on an existing table": (
        "op.create_index('ux_wnote_title', 'wnote', ['title'], unique=True)",
        "unique index",
    ),
    "a batch block that always rebuilds": (
        "with op.batch_alter_table('wnote', recreate='always') as batch_op:\n"
        "    batch_op.add_column(sa.Column('rank', sa.Integer(), nullable=True))",
        "recreate=\"always\"",
    ),
    "a NOT NULL column with nothing to fill it": (
        "op.add_column('wnote', sa.Column('rank', sa.Integer(), nullable=False))",
        "NOT NULL with no server_default",
    ),
}


@pytest.mark.parametrize(("body", "named"), list(_OFF_LIST.values()), ids=list(_OFF_LIST))
def test_an_off_list_operation_raises_before_its_ddl(
    db_url: str, release, body: str, named: str
) -> None:
    previous = release(wnotes=[R1])
    previous.upgrade(db_url)
    _scalar(db_url, "SELECT 1")
    engine = create_engine(db_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO wnote (id, title) VALUES (1, 'kept')"))
    engine.dispose()

    bad = release(wnotes=[R1, Rev("eb", "r1", body, expand=True)])
    with pytest.raises(ExpandRevisionError) as caught:
        bad.upgrade(db_url)
    assert named in str(caught.value)
    assert "eb" in str(caught.value) and "expand_only = False" in str(caught.value)
    # Nothing it would have run was applied: the version table, the record, the schema
    # and the data are as the previous release left them.
    assert _scalar(db_url, "SELECT version_num FROM alembic_version_wnotes") == "r1"
    assert [row.revision for row in _rows(db_url)] == ["r1"]
    assert _columns(db_url, "wnote") == {"id", "title"}
    assert _scalar(db_url, "SELECT title FROM wnote WHERE id = 1") == "kept"


def test_a_batch_block_of_admitted_operations_runs_with_its_flush(db_url: str, release) -> None:
    # On SQLite a server_default that is an expression makes the flush rebuild the table:
    # reflection, a copy and a swap, none of it dispatched as an operation. The block is
    # admitted because every operation it recorded is.
    n = release(
        wnotes=[
            R1,
            Rev(
                "eb",
                "r1",
                "with op.batch_alter_table('wnote') as batch_op:\n"
                "    batch_op.add_column(sa.Column('rank', sa.Integer(), nullable=False,"
                " server_default=sa.text('0')))\n"
                "    batch_op.create_index('ix_wnote_rank', ['rank'], unique=False)",
                expand=True,
            ),
        ]
    )
    n.upgrade(db_url)
    assert "rank" in _columns(db_url, "wnote")
    assert [row.kind for row in _rows(db_url)] == ["contract", "expand"]


def test_a_merge_revision_is_never_expand_only(db_url: str, release) -> None:
    n = release(
        wnotes=[
            R1,
            Rev("ba", "r1", "pass"),
            Rev("bb", "r1", "pass"),
            Rev("mm", ("ba", "bb"), "pass", expand=True),
        ]
    )
    with pytest.raises(ExpandRevisionError, match="a merge revision"):
        n.upgrade(db_url)


def test_offline_sql_refuses_to_render_an_off_list_operation(
    release, capsys: pytest.CaptureFixture[str]
) -> None:
    url = "postgresql+psycopg://u:p@h/db"
    for body, named in (
        ("op.drop_column('wnote', 'title')", "drop_column"),
        # get_bind() returns a mock connection in --sql mode that writes into the script.
        ("op.get_bind().execute(sa.text('DELETE FROM wnote'))", "DELETE FROM wnote"),
    ):
        bad = release(wnotes=[R1, Rev("eb", "r1", body, expand=True)])
        with pytest.raises(ExpandRevisionError, match=re.escape(named)):
            upgrade_sql(url, bad.root, package=bad.package)
        with pytest.raises(SystemExit) as exited:
            migrate_main(
                ["upgrade", "--sql", "--database-url", url, "--app-root", str(bad.root),
                 "--package", bad.package]
            )
        assert exited.value.code == 1
        out, err = capsys.readouterr()
        assert named in err
        assert out == "", "a refused render is not a release script"


def test_the_catalogue_judges_what_no_operation_asked_for(pg_url: str, release) -> None:
    # A raw driver cursor reaches past every SQLAlchemy event: the operation and
    # statement checks cannot see it. The catalogue each expand step leaves can.
    previous = release(wnotes=[R1])
    previous.upgrade(pg_url)
    sneaky = Rev(
        "eb",
        "r1",
        "op.add_column('wnote', sa.Column('rank', sa.Integer(), nullable=True))\n"
        "op.get_bind().connection.dbapi_connection.cursor().execute("
        "'ALTER TABLE wnote ADD CONSTRAINT uq_wnote_title UNIQUE (title)')",
        expand=True,
    )
    bad = release(wnotes=[R1, sneaky])
    with pytest.raises(ExpandRevisionError, match="the step added the unique index") as caught:
        bad.upgrade(pg_url)
    assert "rolled back" in str(caught.value)
    # The step's transaction went with it: no column, no constraint, no version, no row.
    assert _columns(pg_url, "wnote") == {"id", "title"}
    assert _scalar(pg_url, "SELECT count(*) FROM pg_constraint WHERE conname = 'uq_wnote_title'") == 0
    assert _scalar(pg_url, "SELECT version_num FROM alembic_version_wnotes") == "r1"


def test_make_writes_the_mark_false_and_says_where_raising_it_is_possible(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from terp.core.migrations import MigrationTree

    tree = MigrationTree("audit", "terp.capabilities.audit", tmp_path / "migrations")
    monkeypatch.setattr(orchestrate, "resolve_migration_target", lambda *a, **k: tree)
    url = f"sqlite:///{(tmp_path / 'make.db').as_posix()}"

    # A new table is on the list: the comment says so, and the mark stays False.
    make("audit", "create audit", url, autogenerate=True)
    (generated,) = (tmp_path / "migrations" / "versions").glob("*.py")
    body = generated.read_text(encoding="utf-8")
    assert "\nexpand_only = False\n" in body
    assert "# every operation is on the expand list; set True once the previous release" in body

    # A hand-written revision generated nothing, so nothing is said about the list.
    make("audit", "by hand", url, autogenerate=False)
    (hand,) = [path for path in (tmp_path / "migrations" / "versions").glob("*.py") if path != generated]
    text_ = hand.read_text(encoding="utf-8")
    assert "\nexpand_only = False\n" in text_
    assert "every operation is on the expand list" not in text_


# --------------------------------------------------------------------------- #
# Decisions 3, 4 and 6: the window, the rollback that never migrates, the check #
# --------------------------------------------------------------------------- #
def test_n_minus_1_boots_on_an_expanded_database_and_its_migrate_runs_no_ddl(
    db_url: str, release, caplog: pytest.LogCaptureFixture
) -> None:
    n_minus_1 = release(wnotes=[R1])
    n = release(wnotes=[R1, E1])
    n_minus_1.upgrade(db_url)
    n.upgrade(db_url)

    with caplog.at_level(logging.WARNING, logger="terp.migrations"):
        n_minus_1.boot(db_url)
    assert "runs behind wnotes (e1)" in caplog.text
    assert n_minus_1.check(db_url) == 0  # restore-free, by the target's own check

    # Its migration step finds nothing to apply and sends nothing but reads.
    with _statements() as seen:
        n_minus_1.upgrade(db_url)
    writes = [statement for statement in seen if _WRITES.match(statement)]
    assert writes == [], writes
    assert _scalar(db_url, "SELECT version_num FROM alembic_version_wnotes") == "e1"

    # Rolling forward to N finds N's heads and applies nothing.
    with _statements() as seen:
        n.upgrade(db_url)
    assert [statement for statement in seen if _WRITES.match(statement)] == []
    n.boot(db_url)


def test_the_round_trip_n_then_n_minus_1_then_n(db_url: str, release) -> None:
    n_minus_1 = release(wnotes=[R1])
    n = release(wnotes=[R1, E1])
    n_minus_1.upgrade(db_url)
    n.upgrade(db_url)
    old = Table("wnote", MetaData(), Column("id", Integer, primary_key=True), Column("title", String(50)))
    new = Table(
        "wnote",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("title", String(50)),
        Column("rank", Integer),
    )
    engine = create_engine(db_url, poolclass=NullPool)
    try:
        with engine.begin() as connection:  # N writes, in the new shape
            connection.execute(new.insert().values(id=1, title="from N", rank=7))
        n_minus_1.boot(db_url)
        with engine.begin() as connection:  # N-1 reads what N wrote, inserts, updates
            assert connection.execute(select(old.c.title).where(old.c.id == 1)).scalar() == "from N"
            connection.execute(old.insert().values(id=2, title="from N-1"))
            connection.execute(old.update().where(old.c.id == 1).values(title="edited by N-1"))
        n.boot(db_url)
        with engine.connect() as connection:  # N reads both, its own column untouched
            rows = connection.execute(select(new).order_by(new.c.id)).all()
        assert [tuple(row) for row in rows] == [(1, "edited by N-1", 7), (2, "from N-1", None)]
    finally:
        engine.dispose()


def test_a_contract_step_ships_in_a_later_release_and_that_release_rolls_back_by_restore(
    db_url: str, release
) -> None:
    n_minus_1 = release(wnotes=[R1])
    n = release(wnotes=[R1, E1])
    n_plus_1 = release(wnotes=[R1, E1, C2])  # tighten in a later release
    n_minus_1.upgrade(db_url)
    n.upgrade(db_url)
    assert n_minus_1.check(db_url) == 0  # N expanded only: restore-free
    n_plus_1.upgrade(db_url)
    assert n.check(db_url) == 1  # N+1 contracted: restore-based
    with pytest.raises(OrphanedRevisionsError, match="contract revision"):
        n.boot(db_url)
    # And N's migration step refuses before any DDL.
    with _statements() as seen, pytest.raises(OrphanedRevisionsError):
        n.upgrade(db_url)
    assert [statement for statement in seen if _WRITES.match(statement)] == []


def test_a_missing_or_unreadable_record_puts_the_database_outside_the_window(
    db_url: str, release
) -> None:
    n_minus_1 = release(wnotes=[R1])
    n = release(wnotes=[R1, E1])
    n_minus_1.upgrade(db_url)
    n.upgrade(db_url)
    engine = create_engine(db_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM terp_migration_window WHERE revision = 'e1'"))
    with pytest.raises(OrphanedRevisionsError, match="nor in the migration record"):
        n_minus_1.boot(db_url)
    # A record whose shape this code cannot read is the same answer, never a crash.
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE terp_migration_window"))
        connection.execute(text("CREATE TABLE terp_migration_window (label VARCHAR(10))"))
    engine.dispose()
    assert n_minus_1.check(db_url) == 1
    n.boot(db_url)  # a database at the code's heads needs no record at all


def test_two_expanding_releases_are_one_run_too_many(db_url: str, release) -> None:
    n_minus_2 = release(wnotes=[R1])
    n_minus_1 = release(wnotes=[R1, E1])
    n = release(wnotes=[R1, E1, E2])
    for each in (n_minus_2, n_minus_1, n):
        each.upgrade(db_url)
    assert n_minus_1.check(db_url) == 0  # N to N-1: restore-free
    assert n_minus_2.check(db_url) == 1  # N to N-2: restore-based
    with pytest.raises(OrphanedRevisionsError, match="more than one migration run ahead"):
        n_minus_2.boot(db_url)


def test_an_older_run_that_only_installed_a_contract_history_is_refused(db_url: str, release) -> None:
    n_minus_2 = release(wnotes=[R1])
    n_minus_1 = release(wnotes=[R1], wextra=[X1])  # installs a module, contract first revision
    n = release(wnotes=[R1, E1], wextra=[X1])
    for each in (n_minus_2, n_minus_1, n):
        each.upgrade(db_url)
    with pytest.raises(OrphanedRevisionsError) as caught:
        n_minus_2.boot(db_url)
    assert "revisions of 'wextra', which this code does not define" in str(caught.value)
    assert n_minus_1.check(db_url) == 0


def test_a_fresh_environment_first_deployed_at_n_in_one_run(db_url: str, release) -> None:
    n_minus_1 = release(wnotes=[R1])
    expanding = release(wnotes=[R1, E1])
    expanding.upgrade(db_url)  # one run: N-1's history and N's expand step
    assert n_minus_1.check(db_url) == 0


def test_a_fresh_environment_whose_one_run_installed_a_contract_module_is_refused(
    db_url: str, release
) -> None:
    n_minus_1 = release(wnotes=[R1])
    n = release(wnotes=[R1, E1], wextra=[X1])
    n.upgrade(db_url)
    with pytest.raises(OrphanedRevisionsError, match="wextra"):
        n_minus_1.boot(db_url)


def test_n_minus_2_refuses_a_database_first_deployed_at_n_minus_1(db_url: str, release) -> None:
    # The first deploy, at N-1, applied N-2's history and N-1's contract revision in one
    # run, which was not N-2's own; then N expanded. The horizon is N-2's own newest row,
    # and N-2 never migrated here, so the contract row is above it and not the newest's.
    n_minus_2 = release(wnotes=[R1])
    n_minus_1 = release(wnotes=[R1, E1, C2])
    n = release(wnotes=[R1, E1, C2, Rev("e3", "c2", "op.create_index('ix_t', 'wnote', ['title'])", expand=True)])
    n_minus_1.upgrade(db_url)
    n.upgrade(db_url)
    with pytest.raises(OrphanedRevisionsError):
        n_minus_2.boot(db_url)
    assert n_minus_1.check(db_url) == 0


def test_a_run_on_another_terp_version_is_never_crossed(
    db_url: str, release, monkeypatch: pytest.MonkeyPatch
) -> None:
    n_minus_1 = release(wnotes=[R1])
    n = release(wnotes=[R1, E1])
    n_minus_1.upgrade(db_url)
    monkeypatch.setattr(_runtime, "terp_version", lambda: "0.0.1")
    n.upgrade(db_url)
    monkeypatch.undo()
    with pytest.raises(OrphanedRevisionsError, match="never crosses a Terp update"):
        n_minus_1.boot(db_url)


def test_a_rollback_over_a_release_that_applied_nothing_is_restore_free(db_url: str, release) -> None:
    # Rule zero: a release whose migration step applied no revision (a framework update,
    # a code-only change) has its predecessor's heads, so its predecessor runs as before.
    n_minus_1 = release(wnotes=[R1, E1])
    n = release(wnotes=[R1, E1])
    n_minus_1.upgrade(db_url)
    with _statements() as seen:
        n.upgrade(db_url)
    assert [statement for statement in seen if _WRITES.match(statement)] == []
    assert n_minus_1.check(db_url) == 0
    assert n_minus_1.digest(db_url) == n.digest(db_url)


def test_a_release_that_dropped_ns_revisions_is_refused_once_it_adds_one(db_url: str, release) -> None:
    n_minus_1 = release(wnotes=[R1])
    n = release(wnotes=[R1, E1])
    n_minus_1.upgrade(db_url)
    n.upgrade(db_url)
    # A fix cut from N-1 runs while it adds nothing...
    assert n_minus_1.check(db_url) == 0
    # ...and the first revision it adds hangs off N-1's head, where the walk ends on an
    # older ancestor: refused by the migrate preflight, before any DDL.
    cut_from_n_minus_1 = release(
        wnotes=[R1, Rev("f1", "r1", "op.create_index('ix_title', 'wnote', ['title'])", expand=True)]
    )
    with pytest.raises(OrphanedRevisionsError, match="expand revisions this release's history dropped"):
        cut_from_n_minus_1.upgrade(db_url)
    assert _scalar(db_url, "SELECT version_num FROM alembic_version_wnotes") == "e1"


_REVERT_MODELS = '''
import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class WNote(SQLModel, table=True):
    __tablename__ = "wnote"
    id: int | None = Field(default=None, primary_key=True)
    title: str | None = Field(default=None, sa_type=sa.String(50))
    rank: int | None = Field(default=None)  # N's field, kept by the revert
'''


def test_a_revert_release_keeps_ns_revisions_and_models_and_boots(
    db_url: str, release, tmp_path: pathlib.Path
) -> None:
    n_minus_1 = release(wnotes=[R1])
    n = release(wnotes=[R1, E1])
    n_minus_1.upgrade(db_url)
    n.upgrade(db_url)
    revert = release(models=_REVERT_MODELS, wnotes=[R1, E1])
    revert.boot(db_url)  # current: it has N's heads
    # The drift check imports the models into a fresh process, as an app's suite does.
    driver = tmp_path / "drift.py"
    driver.write_text(
        "import sys\n"
        "from terp.migrations import assert_migrations_match_models, upgrade\n"
        f"assert_migrations_match_models({db_url!r}, {str(revert.root)!r}, package={revert.package!r})\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(tmp_path), environment.get("PYTHONPATH", "")) if part
    )
    result = subprocess.run(  # noqa: S603 - our own interpreter and file
        [sys.executable, str(driver)], capture_output=True, text=True, env=environment, check=False
    )
    assert result.returncode == 0, result.stderr


def test_a_removed_package_is_retired_in_the_release_that_removes_it(db_url: str, release) -> None:
    with_extra = release(wnotes=[R1], wextra=[X1])
    with_extra.upgrade(db_url)  # the newest run's rows include wextra's contract revision
    removed = release(wnotes=[R1])
    with pytest.raises(OrphanedRevisionsError) as caught:
        removed.boot(db_url)
    assert "if this release removed it, retire it in this release" in str(caught.value)

    retired = release(retired='RETIRED_MIGRATIONS = ("wextra",)\n', wnotes=[R1])
    retired.boot(db_url)
    retired.upgrade(db_url)  # the preflight reads the window alike
    assert retired.check(db_url) == 0
    # Its tables stay the app's.
    assert "wextra" in inspect(create_engine(db_url, poolclass=NullPool)).get_table_names()


@pytest.mark.parametrize(
    "source",
    [
        'RETIRED_MIGRATIONS = ["wextra"]\n',
        "RETIRED_MIGRATIONS = tuple(['wextra'])\n",
        'RETIRED_MIGRATIONS = ("wextra", 3)\n',
        'RETIRED_MIGRATIONS = ("wextra",)\nRETIRED_MIGRATIONS += ("other",)\n',
        'if True:\n    RETIRED_MIGRATIONS = ("wextra",)\n',
        "RETIRED_MIGRATIONS = (\n",
    ],
    ids=["a list", "computed", "not strings", "assigned twice", "not module level", "unparseable"],
)
def test_a_retired_list_that_cannot_be_read_refuses(db_url: str, release, source: str) -> None:
    # Read as empty, it would quietly un-retire every package and bring the stall back.
    unreadable = release(retired=source, wnotes=[R1])
    with pytest.raises(RetiredMigrationsError):
        unreadable.boot(db_url)


def test_a_retired_label_the_code_still_defines_refuses(db_url: str, release) -> None:
    still = release(retired='RETIRED_MIGRATIONS = ("wextra",)\n', wnotes=[R1], wextra=[X1])
    with pytest.raises(RetiredMigrationsError, match="still defines"):
        still.boot(db_url)
    with pytest.raises(RetiredMigrationsError):
        still.upgrade(db_url)


def test_a_retired_label_in_the_check_and_the_guard_alike(db_url: str, release) -> None:
    # One judgment, three readers: the guard, the preflight and the check cannot disagree.
    with_extra = release(wnotes=[R1], wextra=[X1])
    with_extra.upgrade(db_url)
    removed = release(wnotes=[R1])
    assert removed.check(db_url) == 1
    with pytest.raises(OrphanedRevisionsError):
        removed.upgrade(db_url)


def test_a_package_behind_is_pending_beside_a_package_ahead(db_url: str, release) -> None:
    # The window admits the package that is ahead; a package that is behind is still
    # behind, and the guard still refuses it.
    n_minus_1 = release(wnotes=[R1], wextra=[X1])
    n = release(wnotes=[R1, E1])
    n.upgrade(db_url)
    with pytest.raises(PendingMigrationsError, match="wextra"):
        n_minus_1.boot(db_url)


# --------------------------------------------------------------------------- #
# The PostgreSQL lane: per-module layout, the runtime role                      #
# --------------------------------------------------------------------------- #
def _search_path(url: str) -> list[str] | None:
    """The database-level search_path, entry by entry (PostgreSQL drops needless quotes)."""
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT s.setconfig FROM pg_db_role_setting s JOIN pg_database d"
                " ON d.oid = s.setdatabase WHERE d.datname = current_database()"
                " AND s.setrole = 0"
            ).first()
    finally:
        engine.dispose()
    if row is None:
        return None
    (setting,) = [entry for entry in row[0] if entry.startswith("search_path=")]
    return [part.strip().strip('"') for part in setting.removeprefix("search_path=").split(",")]


def test_a_per_module_rollback_writes_nothing_and_keeps_the_newer_schema_on_the_path(
    pg_url: str, release
) -> None:
    n_minus_1 = release(wnotes=[R1])
    n = release(wnotes=[R1, E1], wextra=[X1])
    n_minus_1.upgrade(pg_url, schema_layout="per-module")
    n.upgrade(pg_url, schema_layout="per-module")
    path = _search_path(pg_url)
    assert path is not None and "wextra" in path and path[-1] == "public"
    with _statements() as seen, contextlib.suppress(OrphanedRevisionsError):
        n_minus_1.upgrade(pg_url, schema_layout="per-module")
    assert [statement for statement in seen if _WRITES.match(statement)] == []
    assert _search_path(pg_url) == path  # never drops a schema


def test_a_per_module_database_restored_into_a_clean_one_is_routed_by_the_next_migrate(
    pg_url: str, release
) -> None:
    n = release(wnotes=[R1, E1])
    n.upgrade(pg_url, schema_layout="per-module")
    assert _search_path(pg_url) is not None
    # A restore into a clean database carries no database-level setting: that is the
    # state, so it is made here without a dump the client tools would have to match.
    engine = create_engine(pg_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        database = make_url(pg_url).database
        connection.exec_driver_sql(f'ALTER DATABASE "{database}" RESET search_path')
    engine.dispose()
    assert _search_path(pg_url) is None
    n.upgrade(pg_url, schema_layout="per-module")  # nothing pending, routed again
    assert "wnotes" in (_search_path(pg_url) or [])
    n.boot(pg_url)


def test_the_runtime_role_reads_the_record_and_cannot_write_it_per_module(pg_url: str, release) -> None:
    n = release(wnotes=[R1, E1])
    n.upgrade(pg_url, schema_layout="per-module")
    role = f"terp_rt_{uuid.uuid4().hex[:10]}"
    admin = create_engine(pg_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f"CREATE ROLE \"{role}\" LOGIN PASSWORD 'rt-secret'")
        grant_runtime_role(
            pg_url, role, n.root, package=n.package, schema_layout="per-module",
            owner_role=make_url(pg_url).username,
        )
        runtime_url = make_url(pg_url).set(username=role, password="rt-secret").render_as_string(
            hide_password=False
        )
        runtime = create_engine(runtime_url, poolclass=NullPool)
        try:
            with runtime.connect() as connection:  # the boot guard's read
                assert connection.exec_driver_sql(
                    "SELECT count(*) FROM public.terp_migration_window"
                ).scalar()
            for refused in (
                "INSERT INTO public.terp_migration_window"
                " SELECT * FROM public.terp_migration_window WHERE 1=0",
                "UPDATE public.terp_migration_window SET kind = 'expand' WHERE 1=0",
                "DELETE FROM public.terp_migration_window WHERE 1=0",
            ):
                with runtime.connect() as connection, pytest.raises(ProgrammingError) as caught:
                    connection.exec_driver_sql(refused)
                assert "permission denied" in str(caught.value)
        finally:
            runtime.dispose()
    finally:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP OWNED BY "{role}"')
            connection.exec_driver_sql(f'DROP ROLE "{role}"')
        admin.dispose()


def test_the_lane_runs_this_module() -> None:
    """Held here as well as in test_ci_postgres_lane: the proofs are PostgreSQL proofs."""
    workflow = (pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml")
    assert "tests/architecture/test_schema_window.py" in workflow.read_text(encoding="utf-8")

