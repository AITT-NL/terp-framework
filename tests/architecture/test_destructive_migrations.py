"""``no_destructive_migrations``: twenty destructive operations, each detected, and their look-alikes.

A revision meets two audiences its author's scratch database never shows: the rows
production already holds, and the release that is still running while it migrates.
The twenty operations below are the test set the rule is held to — drops, renames,
type changes, NOT NULL tightening, constraints the existing rows may break, each in
its op form, its raw-SQL form and its batch form. Every one must be found, exactly
once, on its own line, with the message for its kind; and every non-destructive
look-alike beside it must pass, because a rule whose findings are usually nothing
teaches a reviewer to wave the one that is something through.
"""

from __future__ import annotations

import pathlib
import textwrap
from typing import NamedTuple

import pytest

from terp.arch import check_app, check_no_destructive_migrations
from terp.arch.rules.destructive_migrations import _MESSAGES

_REVISION = "modules/notes/migrations/versions/0001_change.py"


class _Case(NamedTuple):
    name: str
    body: str
    kind: str


def _revision(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    """An app whose one revision's ``upgrade()`` is *body*; returns the app root."""
    app = tmp_path / "app"
    path = app / _REVISION
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "import sqlalchemy as sa\nfrom alembic import op\n\n\ndef upgrade():\n"
        + textwrap.indent(textwrap.dedent(body).strip("\n"), "    ")
        + "\n",
        encoding="utf-8",
    )
    return app


_BATCH = "with op.batch_alter_table('note') as batch_op:\n    "

#: The test set: twenty destructive operations, the last line of each the one to flag.
_TWENTY: tuple[_Case, ...] = (
    # drops
    _Case("drop table", "op.drop_table('note')", "drop"),
    _Case("drop column", "op.drop_column('note', 'legacy')", "drop"),
    # renames
    _Case("rename column", "op.alter_column('note', 'title', new_column_name='heading')", "rename"),
    _Case("rename table", "op.rename_table('note', 'entry')", "rename"),
    # type narrowing
    _Case(
        "type narrowing",
        "op.alter_column('note', 'title', existing_type=sa.String(200), type_=sa.String(50))",
        "type",
    ),
    # NOT NULL tightening, in both spellings of the call
    _Case(
        "not null tightening",
        "op.alter_column('note', 'title', existing_type=sa.String(200), nullable=False)",
        "not-null",
    ),
    _Case(
        "not null tightening by keyword",
        "op.alter_column(table_name='note', column_name='title', nullable=False)",
        "not-null",
    ),
    # constraints the existing rows may break
    _Case("unique constraint", "op.create_unique_constraint('uq_note_slug', 'note', ['slug'])", "constraint"),
    _Case(
        "foreign key on an existing column",
        "op.create_foreign_key('fk_note_owner', 'note', 'identity_user', ['owner_id'], ['id'])",
        "constraint",
    ),
    _Case("check constraint", "op.create_check_constraint('ck_note_rank', 'note', 'rank >= 0')", "constraint"),
    _Case("unique index", "op.create_index('ix_note_slug', 'note', ['slug'], unique=True)", "constraint"),
    # the same steps as raw SQL
    _Case("raw truncate", "op.execute('TRUNCATE note')", "drop"),
    _Case("raw delete", "op.execute('DELETE FROM note WHERE archived')", "drop"),
    _Case("raw rename", "op.execute('ALTER TABLE note RENAME COLUMN title TO heading')", "rename"),
    _Case("raw type change", "op.execute('ALTER TABLE note ALTER COLUMN title TYPE varchar(50)')", "type"),
    _Case("raw set not null", "op.execute('ALTER TABLE note ALTER COLUMN title SET NOT NULL')", "not-null"),
    _Case(
        "raw add constraint",
        "op.execute(sa.text('ALTER TABLE note ADD CONSTRAINT uq_note_slug UNIQUE (slug)'))",
        "constraint",
    ),
    # batch mode: the table comes from the block, so the call names none
    _Case("batch drop column", _BATCH + "batch_op.drop_column('legacy')", "drop"),
    _Case("batch rename column", _BATCH + "batch_op.alter_column('title', new_column_name='heading')", "rename"),
    _Case("batch not null tightening", _BATCH + "batch_op.alter_column('title', nullable=False)", "not-null"),
)

#: More destructive spellings the rule reads, beyond the twenty.
_MORE: tuple[_Case, ...] = (
    _Case("raw rename table", "op.execute('ALTER TABLE note RENAME TO entry')", "rename"),
    _Case("mysql rename table", "op.execute('RENAME TABLE note TO entry')", "rename"),
    _Case("f-string rename", "op.execute(f'ALTER TABLE {table} RENAME TO entry')", "rename"),
    _Case("concatenated rename", "op.execute('ALTER TABLE ' + table + ' RENAME TO entry')", "rename"),
    _Case("rename through the driver", "op.get_bind().exec_driver_sql('ALTER TABLE note RENAME TO entry')", "rename"),
    _Case("raw type change, no COLUMN", "op.execute('ALTER TABLE note ALTER type TYPE text')", "type"),
    _Case("raw set data type", "op.execute('ALTER TABLE note ALTER COLUMN rank SET DATA TYPE smallint')", "type"),
    _Case("raw unique index", "op.execute('CREATE UNIQUE INDEX ix_note_slug ON note (slug)')", "constraint"),
    _Case("raw validate", "op.execute('ALTER TABLE note VALIDATE CONSTRAINT ck_note_rank')", "constraint"),
    _Case(
        "raw unique is never NOT VALID",
        "op.execute('ALTER TABLE note ADD CONSTRAINT uq UNIQUE (slug) NOT VALID')",
        "constraint",
    ),
    _Case(
        "second statement adds the constraint",
        "op.execute('ALTER TABLE note ADD COLUMN slug text; ALTER TABLE note ADD UNIQUE (slug)')",
        "constraint",
    ),
    _Case("primary key on an existing table", "op.create_primary_key('pk_note', 'note', ['id'])", "constraint"),
    _Case(
        "exclude constraint",
        "op.create_exclude_constraint('ex_note', 'note', ('span', '&&'))",
        "constraint",
    ),
    _Case("batch type change", _BATCH + "batch_op.alter_column('title', type_=sa.String(50))", "type"),
    _Case("batch unique constraint", _BATCH + "batch_op.create_unique_constraint('uq', ['slug'])", "constraint"),
    _Case("batch unique index", _BATCH + "batch_op.create_index('ix', ['slug'], unique=True)", "constraint"),
    _Case(
        "batch foreign key on an existing column",
        _BATCH + "batch_op.create_foreign_key('fk', 'identity_user', ['owner_id'], ['id'])",
        "constraint",
    ),
    _Case("aliased handle", "ops.alter_column('note', 'title', new_column_name='heading')", "rename"),
    _Case(
        "a table that is not a literal may hold rows",
        "op.alter_column(table, 'title', nullable=False)",
        "not-null",
    ),
    _Case(
        "a tightening that names no table at all",
        "op.alter_column(column_name='title', nullable=False)",
        "not-null",
    ),
    _Case(
        "a constraint on a table that is not a literal",
        "op.create_unique_constraint('uq', table, ['slug'])",
        "constraint",
    ),
    _Case(
        "two tables that are not literals are never taken to be one",
        "op.add_column(table, sa.Column('slug', sa.String()))\n"
        "op.create_unique_constraint('uq', other_table, ['slug'])",
        "constraint",
    ),
    _Case(
        "a batch block whose table is not a literal",
        "with op.batch_alter_table(table) as batch_op:\n    batch_op.alter_column('title', nullable=False)",
        "not-null",
    ),
    _Case(
        "a new column with a server default holds it, not NULL",
        "op.add_column('note', sa.Column('slug', sa.String(), server_default='x'))\n"
        "op.create_unique_constraint('uq', 'note', ['slug'])",
        "constraint",
    ),
    _Case(
        "a new NOT NULL column holds values",
        "op.add_column('note', sa.Column('slug', sa.String(), nullable=False, server_default='x'))\n"
        "op.create_index('ix', 'note', ['slug'], unique=True)",
        "constraint",
    ),
    _Case(
        "a new primary-key column",
        "op.add_column('note', sa.Column('slug', sa.String(), primary_key=True))\n"
        "op.create_unique_constraint('uq', 'note', ['slug'])",
        "constraint",
    ),
    _Case(
        "a new column whose name is not a literal",
        "op.add_column('note', sa.Column(name, sa.String()))\n"
        "op.create_unique_constraint('uq', 'note', ['slug'])",
        "constraint",
    ),
    _Case(
        "a check constraint on a new column is still read",
        "op.add_column('note', sa.Column('rank', sa.Integer()))\n"
        "op.create_check_constraint('ck', 'note', 'rank >= 0')",
        "constraint",
    ),
    _Case(
        "constraint columns that are not literals",
        "op.add_column('note', sa.Column('slug', sa.String()))\n"
        "op.create_unique_constraint('uq', 'note', columns)",
        "constraint",
    ),
    _Case(
        "one constraint column is not new",
        "op.add_column('note', sa.Column('slug', sa.String()))\n"
        "op.create_unique_constraint('uq', 'note', ['slug', 'title'])",
        "constraint",
    ),
    _Case(
        "tightening a column this upgrade just added still races the running release",
        "op.add_column('note', sa.Column('rank', sa.Integer()))\n"
        "op.execute('UPDATE note SET rank = 0')\n"
        "op.alter_column('note', 'rank', nullable=False)",
        "not-null",
    ),
)

#: Look-alikes: every one shares a spelling with a destructive step and takes none.
_LOOK_ALIKES: tuple[tuple[str, str], ...] = (
    ("relaxing NOT NULL", "op.alter_column('note', 'title', nullable=True)"),
    (
        "restating NOT NULL",
        "op.alter_column('note', 'title', existing_type=sa.String(200), nullable=False, "
        "existing_nullable=False)",
    ),
    ("a server default", "op.alter_column('note', 'title', server_default='untitled')"),
    ("a comment", "op.alter_column('note', 'title', comment='shown in lists')"),
    ("a nullable column", "op.add_column('note', sa.Column('slug', sa.String(), nullable=True))"),
    ("a plain index", "op.create_index('ix_note_slug', 'note', ['slug'])"),
    ("an index that says it is not unique", "op.create_index('ix_note_slug', 'note', ['slug'], unique=False)"),
    (
        "a new table, tightened and constrained",
        "op.create_table('draft', sa.Column('id', sa.Integer()))\n"
        "op.alter_column('draft', 'title', nullable=False)\n"
        "op.create_unique_constraint('uq_draft_slug', 'draft', ['slug'])\n"
        "op.create_check_constraint('ck_draft_rank', 'draft', 'rank >= 0')\n"
        "op.create_index(op.f('ix_draft_slug'), 'draft', ['slug'], unique=True)",
    ),
    (
        "a new table, by batch",
        "op.create_table('draft', sa.Column('id', sa.Integer()))\n"
        "with op.batch_alter_table('draft', schema=None) as batch_op:\n"
        "    batch_op.create_index(batch_op.f('ix_draft_slug'), ['slug'], unique=True)\n"
        "    batch_op.alter_column('title', nullable=False)",
    ),
    (
        "a new reference column (autogenerate's shape)",
        "op.add_column('note', sa.Column('owner_id', sa.Uuid(), nullable=True))\n"
        "op.create_index(op.f('ix_note_owner_id'), 'note', ['owner_id'], unique=False)\n"
        "op.create_foreign_key(None, 'note', 'identity_user', ['owner_id'], ['id'])",
    ),
    (
        "a new reference column, by batch",
        "with op.batch_alter_table('note', schema=None) as batch_op:\n"
        "    batch_op.add_column(sa.Column('owner_id', sa.Uuid(), nullable=True))\n"
        "    batch_op.create_foreign_key(None, 'identity_user', ['owner_id'], ['id'])",
    ),
    (
        "a new column made unique, by keyword",
        "op.add_column('note', sa.Column('slug', sa.String()))\n"
        "op.create_unique_constraint('uq', table_name='note', columns=['slug'])",
    ),
    ("a check added NOT VALID", "op.execute('ALTER TABLE note ADD CONSTRAINT ck CHECK (rank >= 0) NOT VALID')"),
    (
        "a foreign key added NOT VALID",
        "op.execute('ALTER TABLE note ADD CONSTRAINT fk FOREIGN KEY (owner_id) "
        "REFERENCES identity_user (id) NOT VALID')",
    ),
    ("raw DROP NOT NULL", "op.execute('ALTER TABLE note ALTER COLUMN title DROP NOT NULL')"),
    ("raw SET DEFAULT on a column named type", "op.execute('ALTER TABLE note ALTER COLUMN type SET DEFAULT 1')"),
    ("a constraint rename", "op.execute('ALTER TABLE note RENAME CONSTRAINT uq_a TO uq_b')"),
    ("an index rename", "op.execute('ALTER INDEX ix_a RENAME TO ix_b')"),
    (
        "a table change, then an index rename",
        "op.execute('ALTER TABLE note ADD COLUMN slug text; ALTER INDEX ix_a RENAME TO ix_b')",
    ),
    ("a backfill", "op.execute(\"UPDATE note SET title = 'untitled' WHERE title IS NULL\")"),
    ("a plain raw index", "op.execute('CREATE INDEX ix_note_slug ON note (slug)')"),
    ("a column whose name starts with a keyword", "op.execute('ALTER TABLE note ADD COLUMN check_flag boolean')"),
    ("a table whose name starts with a keyword", "op.execute('ALTER TABLE renamed_things ADD COLUMN x int')"),
    ("a statement the rule cannot read", "op.execute(statement)\nop.execute(a + b)\nop.execute(5)"),
    ("an unrelated call", "helper()\nop.f('ix_note_slug')"),
    ("an unrelated context manager", "with open_session() as session:\n    session.flush()\nwith lock():\n    pass"),
    ("a drop index", "op.drop_index('ix_note_slug', table_name='note')"),
)


@pytest.mark.parametrize("case", _TWENTY, ids=[case.name for case in _TWENTY])
def test_each_of_the_twenty_is_detected(tmp_path: pathlib.Path, case: _Case) -> None:
    app = _revision(tmp_path, case.body)
    found = check_no_destructive_migrations(app)
    # One operation is one finding, on its own line, saying what to do for its kind.
    line = 5 + len(textwrap.dedent(case.body).strip("\n").splitlines())
    assert [(v.rule, v.line, v.message) for v in found] == [
        ("no_destructive_migrations", line, _MESSAGES[case.kind])
    ], case.body


def test_the_test_set_is_twenty_and_covers_every_kind() -> None:
    assert len(_TWENTY) == 20
    assert len({case.name for case in _TWENTY}) == 20
    assert {case.kind for case in _TWENTY} == set(_MESSAGES)
    # Each kind is spelled more than one way, and the raw-SQL and batch spellings are in it.
    assert all(sum(case.kind == kind for case in _TWENTY) >= 2 for kind in _MESSAGES)
    assert sum(case.name.startswith("raw ") for case in _TWENTY) >= 5
    assert sum(case.name.startswith("batch ") for case in _TWENTY) >= 3


@pytest.mark.parametrize("case", _MORE, ids=[case.name for case in _MORE])
def test_more_destructive_spellings_are_detected(tmp_path: pathlib.Path, case: _Case) -> None:
    app = _revision(tmp_path, case.body)
    found = check_no_destructive_migrations(app)
    assert [v.message for v in found] == [_MESSAGES[case.kind]], case.body


@pytest.mark.parametrize("name,body", _LOOK_ALIKES, ids=[name for name, _ in _LOOK_ALIKES])
def test_a_look_alike_passes(tmp_path: pathlib.Path, name: str, body: str) -> None:
    app = _revision(tmp_path, body)
    assert check_no_destructive_migrations(app) == [], name


@pytest.mark.parametrize("case", _TWENTY, ids=[case.name for case in _TWENTY])
def test_the_reviewed_contract_step_takes_the_marker(tmp_path: pathlib.Path, case: _Case) -> None:
    """Every kind is escaped the same way: one justified marker, counted by the budget."""
    lines = textwrap.dedent(case.body).strip("\n").splitlines()
    indent = lines[-1][: len(lines[-1]) - len(lines[-1].lstrip())]
    lines.insert(-1, f"{indent}# arch-allow-no-destructive-migrations: reviewed contract step")
    app = _revision(tmp_path, "\n".join(lines))
    assert check_app(app) == [], case.body


def test_every_message_says_what_to_do_instead() -> None:
    for kind, message in _MESSAGES.items():
        assert "later release" in message, kind
        assert "# arch-allow-no-destructive-migrations: <reason>" in message, kind
    assert len(set(_MESSAGES.values())) == len(_MESSAGES)


def test_only_upgrade_is_read(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    path = app / _REVISION
    path.parent.mkdir(parents=True)
    path.write_text(
        "def upgrade():\n    op.add_column('note', column)\n\n\n"
        "def downgrade():\n    op.alter_column('note', 'heading', new_column_name='title')\n"
        "    op.alter_column('note', 'title', nullable=False)\n"
        "    op.create_unique_constraint('uq', 'note', ['slug'])\n",
        encoding="utf-8",
    )
    assert check_no_destructive_migrations(app) == []


def test_two_destructive_steps_are_two_findings(tmp_path: pathlib.Path) -> None:
    app = _revision(
        tmp_path,
        "op.alter_column('note', 'title', new_column_name='heading')\n"
        "op.alter_column('note', 'rank', nullable=False)\n",
    )
    found = check_no_destructive_migrations(app)
    assert [(v.line, v.message) for v in found] == [
        (6, _MESSAGES["rename"]),
        (7, _MESSAGES["not-null"]),
    ]
