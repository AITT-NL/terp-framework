"""``assert_migrations_reverse_cleanly`` — the rollback plan, actually rehearsed.

Every Terp app's rollback plan is ``terp migrate downgrade``, and the catalogued
``alembic_downgrades_not_empty`` rule proves only that the ``downgrade()`` body is not a
lone ``pass``. That is a source-level check: it cannot see a downgrade that dies on its
first statement, and it cannot see one that leaves the schema different from how it found
it. The forward direction has had an executed check since ``assert_migrations_match_models``
shipped; the reverse direction had reading.

These build tiny Alembic histories rather than leaning on the example app, because the
failures worth pinning are the ones a *wrong* history produces, and the example app's is
correct. The example app is exercised too — by the conformance suite, on both dialects.
"""

from __future__ import annotations

import pathlib

import pytest
from sqlalchemy import create_engine, inspect

from terp.core.migrations import MigrationTree
from terp.migrations import guard, orchestrate
from terp.migrations.errors import (
    MigrationHistoryNotEmptiedError,
    MigrationResidueError,
    MigrationReversibilityError,
)
from terp.migrations.guard import (
    _applied_revision_labels,
    _catalogue_queries_for,
    _normalise_constraint_order,
    _schema_snapshot,
    assert_migrations_reverse_cleanly,
)


def _write_revision(
    versions: pathlib.Path,
    rid: str,
    down: str | None,
    *,
    up_body: str,
    down_body: str,
) -> None:
    """One revision script with real DDL in both directions."""
    versions.joinpath(f"{rid}.py").write_text(
        f'"""rev {rid}"""\n'
        "from __future__ import annotations\n\n"
        "import sqlalchemy as sa\n"
        "from alembic import op\n\n"
        f"revision = {rid!r}\n"
        f"down_revision = {down!r}\n"
        "branch_labels = None\n"
        "depends_on = None\n\n\n"
        f"def upgrade() -> None:\n{up_body}\n\n\n"
        f"def downgrade() -> None:\n{down_body}\n",
        encoding="utf-8",
    )


@pytest.fixture
def history(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Install a single synthetic migration tree and hand back its versions directory."""
    versions = tmp_path / "migrations" / "versions"
    versions.mkdir(parents=True)
    tree = MigrationTree("audit", "terp.capabilities.audit", tmp_path / "migrations")
    monkeypatch.setattr(orchestrate, "resolve_migration_trees", lambda *a, **k: [tree])
    monkeypatch.setattr(orchestrate, "resolve_migration_target", lambda *a, **k: tree)
    return versions


@pytest.fixture
def db(tmp_path: pathlib.Path) -> str:
    return f"sqlite:///{tmp_path / 'reverse.db'}"


_CREATE = (
    "    op.create_table(\n"
    "        'rev_widget',\n"
    "        sa.Column('id', sa.Integer(), primary_key=True),\n"
    "        sa.Column('name', sa.String(length=50), nullable=False),\n"
    "    )"
)
_DROP = "    op.drop_table('rev_widget')"


# --------------------------------------------------------------------------- #
# the happy path, and the two failures the rule could never see
# --------------------------------------------------------------------------- #
def test_a_history_that_reverses_cleanly_passes(history: pathlib.Path, db: str) -> None:
    _write_revision(history, "rev0001", None, up_body=_CREATE, down_body=_DROP)
    assert_migrations_reverse_cleanly(db, schema_layout="flat")
    # …and the database is left at head, not at base: this is a rehearsal, and a check
    # that leaves the scratch database empty would be surprising to build on.
    assert "rev_widget" in set(inspect(create_engine(db)).get_table_names())


def test_a_downgrade_that_leaves_a_table_behind_is_caught(
    history: pathlib.Path, db: str
) -> None:
    """The quiet failure, and the reason this looks at the MIDDLE of the cycle.

    Revision two creates a second table and its downgrade forgets to drop it. Nothing
    errors: the downgrade runs green, and the second upgrade meets the surviving table
    and reproduces the same schema — so comparing the two ends of the cycle finds
    nothing. What is wrong is what a rollback leaves on a production database for the
    next deploy to collide with, and that is only visible with the history at base.
    """
    _write_revision(history, "rev0001", None, up_body=_CREATE, down_body=_DROP)
    _write_revision(
        history,
        "rev0002",
        "rev0001",
        up_body=(
            "    op.execute('CREATE TABLE IF NOT EXISTS rev_audit "
            "(id INTEGER PRIMARY KEY)')"
        ),
        down_body="    pass  # forgot to drop rev_audit",
    )
    with pytest.raises(MigrationResidueError) as caught:
        assert_migrations_reverse_cleanly(db, schema_layout="flat")
    message = str(caught.value)
    assert "rev_audit" in message, "it names what was left behind"
    assert "left 1 object(s) behind" in message


def test_an_index_the_downgrade_forgets_is_caught_too(
    history: pathlib.Path, db: str
) -> None:
    """Not only tables. An index left on a table that survives is the same defect."""
    _write_revision(
        history,
        "rev0001",
        None,
        up_body=_CREATE,
        down_body="    pass  # forgot everything",
    )
    with pytest.raises(MigrationResidueError) as caught:
        assert_migrations_reverse_cleanly(db, schema_layout="flat")
    assert "rev_widget" in str(caught.value)


def test_a_cycle_that_lands_a_different_schema_is_caught(
    history: pathlib.Path, db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The backstop, for a difference the middle of the cycle cannot show.

    Residue is the common shape and is caught above; this is the assertion that the two
    ENDS agree, which is what makes "the rollback plan was rehearsed" a claim about the
    schema you roll forward into rather than only about what the downgrade removed.
    Driven here by making the second upgrade build something the first did not, which is
    the only way to reach it once residue is refused.
    """
    _write_revision(history, "rev0001", None, up_body=_CREATE, down_body=_DROP)
    real_upgrade, calls = orchestrate.upgrade, []

    def _drifting_upgrade(url: str, *args: object, **kwargs: object) -> list[str]:
        applied = real_upgrade(url, *args, **kwargs)
        calls.append(url)
        if len(calls) == 2:  # the rehearsal's second pass lands one object more
            engine = create_engine(url)
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE INDEX ix_rev_widget_drift ON rev_widget (name)"
                )
            engine.dispose()
        return applied

    monkeypatch.setattr(guard, "upgrade", _drifting_upgrade)
    with pytest.raises(MigrationReversibilityError) as caught:
        assert_migrations_reverse_cleanly(db, schema_layout="flat")
    message = str(caught.value)
    assert "ix_rev_widget_drift" in message, "it names the object that changed"
    assert "does not reverse cleanly" in message


def test_a_history_that_never_went_down_is_caught_before_it_is_hidden(
    history: pathlib.Path, db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The version-table check has to run BEFORE the second upgrade.

    A package whose history never went down looks identical, afterwards, to one that
    went down and came back: the second upgrade re-stamps the version table either way.
    So the bookkeeping is asserted in the window where the two are still distinguishable.
    """
    _write_revision(history, "rev0001", None, up_body=_CREATE, down_body=_DROP)
    monkeypatch.setattr(guard, "downgrade", lambda *a, **k: [])  # a downgrade that no-ops

    with pytest.raises(MigrationHistoryNotEmptiedError) as caught:
        assert_migrations_reverse_cleanly(db, schema_layout="flat")
    assert "audit" in str(caught.value)
    assert "never went down" in str(caught.value)


def test_a_downgrade_that_cannot_run_fails_loudly(history: pathlib.Path, db: str) -> None:
    """The common failure, and the one the empty-stub rule most looks like it covers.

    A non-empty ``downgrade()`` naming an object that does not exist passes the rule and
    dies on the first rollback anyone attempts. Here it surfaces during the rehearsal
    instead — in CI, where it is a test failure rather than an outage.
    """
    _write_revision(
        history,
        "rev0001",
        None,
        up_body=_CREATE,
        down_body="    op.drop_table('rev_widget_typo')",
    )
    with pytest.raises(Exception, match="rev_widget_typo|no such table"):
        assert_migrations_reverse_cleanly(db, schema_layout="flat")


# --------------------------------------------------------------------------- #
# the snapshot: the database's own catalogue, never the inspector
# --------------------------------------------------------------------------- #
def test_the_snapshot_keeps_what_reflection_would_lose(
    history: pathlib.Path, db: str
) -> None:
    """The reason this reads ``sqlite_master.sql`` rather than the SQLAlchemy inspector.

    Reflection is the layer that drops a partial index's ``WHERE`` predicate and a
    CHECK constraint's text — the two things a batch rebuild also drops. A snapshot
    built on it would be blind to the difference it exists to see, and green.
    """
    _write_revision(
        history,
        "rev0001",
        None,
        up_body=(
            _CREATE
            + "\n    op.create_index(\n"
            "        'ix_rev_widget_live', 'rev_widget', ['name'],\n"
            "        unique=True, sqlite_where=sa.text(\"name <> ''\"),\n"
            "    )"
        ),
        down_body=_DROP,
    )
    orchestrate.upgrade(db, schema_layout="flat")
    snapshot = _schema_snapshot(db)

    assert "index ix_rev_widget_live" in snapshot
    assert "WHERE" in snapshot["index ix_rev_widget_live"].upper(), (
        "the predicate must survive into the snapshot — it is what a rebuild drops"
    )
    assert "CHECK" not in snapshot["table rev_widget"].upper(), (
        "sanity: this fixture declares no CHECK, so its absence is the baseline the "
        "predicate assertion above is read against"
    )


def test_the_snapshot_skips_the_database_s_own_internal_tables(
    history: pathlib.Path, db: str
) -> None:
    """``sqlite_sequence`` and friends appear and disappear on their own."""
    _write_revision(history, "rev0001", None, up_body=_CREATE, down_body=_DROP)
    orchestrate.upgrade(db, schema_layout="flat")
    assert not [key for key in _schema_snapshot(db) if "sqlite_" in key.split()[-1]]


def test_a_history_with_no_version_table_yet_is_not_read_as_still_applied(
    history: pathlib.Path, db: str
) -> None:
    """A package whose bookkeeping table does not exist has nothing applied.

    Alembic creates ``alembic_version_<label>`` on first upgrade, so a label that never
    ran has no table at all — and a check that treated "no table" as "cannot tell" would
    fail every history the first time it is rehearsed.
    """
    _write_revision(history, "rev0001", None, up_body=_CREATE, down_body=_DROP)
    orchestrate.upgrade(db, schema_layout="flat")
    assert _applied_revision_labels(db, ["audit"]) == ["audit"]
    assert _applied_revision_labels(db, ["audit", "never_ran"]) == ["audit"]


def test_an_unverified_dialect_is_refused_rather_than_answered_emptily() -> None:
    """Two empty snapshots compare equal, so silence here would be a passing check
    that knows nothing. It names the dialects it can read instead."""
    with pytest.raises(ValueError, match="cannot read the schema catalogue of 'oracle'"):
        _catalogue_queries_for("oracle")
    assert "sqlite" in _catalogue_queries_for("sqlite")[0]
    assert any("pg_get_constraintdef" in q for q in _catalogue_queries_for("postgresql"))


# --------------------------------------------------------------------------- #
# the one normalisation, and its limits
# --------------------------------------------------------------------------- #
def test_only_the_trailing_constraint_run_is_reordered() -> None:
    """Constraint emission order carries no meaning and is not stable across two
    upgrades in one process; column order carries plenty and is left alone."""
    definition = (
        "CREATE TABLE t (\n  a INTEGER,\n  b INTEGER,\n"
        "  CONSTRAINT z_ck CHECK (a > 0),\n  CONSTRAINT a_pk PRIMARY KEY (a)\n)"
    )
    normalised = _normalise_constraint_order(definition)
    assert normalised.index("CONSTRAINT a_pk") < normalised.index("CONSTRAINT z_ck")
    assert normalised.index("a INTEGER") < normalised.index("b INTEGER")


def test_a_nested_parenthesis_does_not_split_an_item() -> None:
    """A CHECK with a comma inside its expression is one item, not two."""
    definition = "CREATE TABLE t (\n  a INTEGER,\n  CONSTRAINT c CHECK (a IN (1, 2))\n)"
    assert _normalise_constraint_order(definition) == definition


def test_anything_that_is_not_a_create_table_is_returned_untouched() -> None:
    for definition in (
        "CREATE INDEX ix_t_a ON t (a) WHERE a > 0",
        "CREATE TRIGGER guard BEFORE UPDATE ON t BEGIN SELECT 1; END",
        "CREATE TABLE weird",
    ):
        assert _normalise_constraint_order(definition) == definition
