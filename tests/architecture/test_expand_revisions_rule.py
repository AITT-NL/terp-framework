"""``expand_revisions_only_expand``: a revision marked expand-only holds only the expand list.

The build-time half of ADR 0185 decision 1. The mark is a promise that the previous
release keeps running on the schema the revision leaves, which is what lets a release
roll back without a restore. These cases pin the list from both sides: every form an
author (or autogenerate) writes for an admitted operation stays quiet, and every form
of an operation off the list is refused, once, on its own line. The runtime half, the
migration run refusing the same operations as Alembic dispatches them, is pinned in
``test_schema_window.py``.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from terp.arch import (
    RULES_WITHOUT_AN_OPT_OUT,
    check_app,
    check_escape_hatch_budget,
    check_expand_revisions_only_expand,
)

_REVISION = "modules/notes/migrations/versions/0001_change.py"


def _write(app: pathlib.Path, relative: str, source: str) -> None:
    path = app / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _marked(body: str, *, header: str = "") -> str:
    return f"{header}expand_only = True\n\n\ndef upgrade():\n" + "".join(
        f"    {line}\n" for line in body.splitlines()
    )


_ADMITTED = {
    "a nullable add_column": "op.add_column('notes', sa.Column('rank', sa.Integer(), nullable=True))",
    "an add_column that takes the default nullability": "op.add_column('notes', sa.Column('rank', sa.Integer()))",
    "a NOT NULL add_column with a server_default": (
        "op.add_column('notes', sa.Column('rank', sa.Integer(), nullable=False, server_default='0'))"
    ),
    "a generated add_column": (
        "op.add_column('notes', sa.Column('total', sa.Integer(), sa.Computed('a + b'), nullable=False))"
    ),
    "the keyword spelling": (
        "op.add_column(table_name='notes', column=sa.Column('rank', sa.Integer(), nullable=True))"
    ),
    "a batch block of admitted operations, as autogenerate writes it on SQLite": (
        "with op.batch_alter_table('notes', schema=None) as batch_op:\n"
        "    batch_op.add_column(sa.Column('rank', sa.Integer(), nullable=True))\n"
        "    batch_op.create_index(batch_op.f('ix_notes_rank'), ['rank'], unique=False)"
    ),
    "a batch block with recreate='auto'": (
        "with op.batch_alter_table('notes', recreate='auto') as batch_op:\n"
        "    batch_op.add_column(sa.Column('rank', sa.Integer(), nullable=True))"
    ),
    "a non-unique index": "op.create_index(op.f('ix_notes_rank'), 'notes', ['rank'], unique=False)",
    "a new table with its own constraints, unique index, cascading key and seed rows": (
        "drafts = op.create_table('drafts',\n"
        "    sa.Column('id', sa.Integer(), primary_key=True),\n"
        "    sa.Column('note_id', sa.Uuid(), nullable=False),\n"
        "    sa.ForeignKeyConstraint(['note_id'], ['notes.id'], ondelete='CASCADE'),\n"
        "    sa.UniqueConstraint('note_id'))\n"
        "op.create_index('ix_drafts_note', 'drafts', ['note_id'], unique=True)\n"
        "op.add_column('drafts', sa.Column('rank', sa.Integer(), nullable=False))\n"
        "op.create_check_constraint('ck_drafts_rank', 'drafts', 'rank > 0')\n"
        "op.bulk_insert(drafts, [{'id': 1}])\n"
        "op.bulk_insert(sa.table('drafts', sa.column('id')), [{'id': 2}])"
    ),
    "a SET NULL key on a new nullable column, inline": (
        "op.add_column('notes', sa.Column('project_id', sa.Uuid(),"
        " sa.ForeignKey('project.id', ondelete='SET NULL'), nullable=True))"
    ),
    "a SET NULL key over a new nullable column, as autogenerate writes it": (
        "op.add_column('notes', sa.Column('project_id', sa.Uuid(), nullable=True))\n"
        "op.create_foreign_key(op.f('fk_notes_project'), 'notes', 'project',"
        " ['project_id'], ['id'], ondelete='SET NULL')"
    ),
    "an unqualified key from a new table": (
        "op.create_table('drafts', Column('note_id', Uuid(), ForeignKey('notes.id', ondelete='CASCADE')))"
    ),
    "a key from a new table, written after it": (
        "op.create_table('drafts', sa.Column('note_id', sa.Uuid()))\n"
        "op.create_foreign_key('fk_drafts_note', 'drafts', 'notes', ['note_id'], ['id'], ondelete='CASCADE')"
    ),
    "a SET NULL key whose target is a name": (
        "op.add_column('notes', sa.Column('p', sa.Uuid(), sa.ForeignKey(PROJECT_ID, ondelete='SET NULL')))"
    ),
    "a call that names no operation at all": "HELPERS['note']()",
    "a concurrent index in an autocommit block": (
        "with op.get_context().autocommit_block():\n"
        "    op.create_index('ix_notes_rank', 'notes', ['rank'], postgresql_concurrently=True)"
    ),
}


@pytest.mark.parametrize("body", list(_ADMITTED.values()), ids=list(_ADMITTED))
def test_an_admitted_operation_is_not_refused(tmp_path: pathlib.Path, body: str) -> None:
    app = tmp_path / "app"
    _write(app, _REVISION, _marked(body))
    assert check_expand_revisions_only_expand(app) == []


_REFUSED = {
    "a drop": ("op.drop_column('notes', 'legacy')", "drop_column"),
    "a drop through another name for the handle": (
        "operations = op\noperations.drop_column('notes', 'legacy')",
        "drop_column",
    ),
    "a rename": ("op.rename_table('notes', 'memos')", "rename_table"),
    "a type change": ("op.alter_column('notes', 'title', type_=sa.Text())", "alter_column"),
    "tightening to NOT NULL": ("op.alter_column('notes', 'rank', nullable=False)", "alter_column"),
    "a NOT NULL add_column with nothing to fill it": (
        "op.add_column('notes', sa.Column('rank', sa.Integer(), nullable=False))",
        "NOT NULL with no server_default",
    ),
    "a unique add_column": (
        "op.add_column('notes', sa.Column('code', sa.String(8), unique=True))",
        "with unique",
    ),
    "a computed uniqueness": (
        "op.add_column('notes', sa.Column('code', sa.String(8), unique=CODES_ARE_UNIQUE))",
        "with unique",
    ),
    "a primary key column": (
        "op.add_column('notes', sa.Column('id2', sa.Integer(), primary_key=True))",
        "primary key",
    ),
    "a checked add_column": (
        "op.add_column('notes', sa.Column('rank', sa.Integer(), sa.CheckConstraint('rank > 0')))",
        "check constraint",
    ),
    "a column the check cannot read": ("op.add_column('notes', column)", "cannot read"),
    "a unique index on an existing table": (
        "op.create_index('ix_notes_code', 'notes', ['code'], unique=True)",
        "unique index",
    ),
    "a unique constraint on an existing table": (
        "op.create_unique_constraint('uq_notes_code', 'notes', ['code'])",
        "create_unique_constraint",
    ),
    "a check constraint on an existing table": (
        "op.create_check_constraint('ck_notes_rank', 'notes', 'rank > 0')",
        "create_check_constraint",
    ),
    "a primary key change": (
        "op.create_primary_key('pk_notes', 'notes', ['id', 'code'])",
        "create_primary_key",
    ),
    "execute, whatever it sends": ("op.execute('UPDATE notes SET rank = 0')", "execute()"),
    "a statement through get_bind": (
        "op.get_bind().execute(sa.text('UPDATE notes SET rank = 0'))",
        "execute()",
    ),
    "a data write into an existing table": (
        "op.bulk_insert(sa.table('notes', sa.column('id')), [{'id': 1}])",
        "bulk_insert",
    ),
    "a batch block that always rebuilds its table": (
        "with op.batch_alter_table('notes', recreate='always') as batch_op:\n"
        "    batch_op.add_column(sa.Column('rank', sa.Integer(), nullable=True))",
        "recreate='always'",
    ),
    "a refused operation inside a batch block": (
        "with op.batch_alter_table('notes') as batch_op:\n"
        "    batch_op.drop_column('legacy')",
        "drop_column",
    ),
    "a CASCADE key on a column added to an existing table": (
        "op.add_column('notes', sa.Column('project_id', sa.Uuid(),"
        " sa.ForeignKey('project.id', ondelete='CASCADE'), nullable=True))",
        "needs SET NULL",
    ),
    "a key on a NOT NULL column added to an existing table": (
        "op.add_column('notes', sa.Column('project_id', sa.Uuid(),"
        " sa.ForeignKey('project.id', ondelete='SET NULL'), nullable=False, server_default='x'))",
        "NOT NULL column",
    ),
    "a key over a column this revision did not add": (
        "op.create_foreign_key('fk_notes_project', 'notes', 'project',"
        " ['project_id'], ['id'], ondelete='SET NULL')",
        "does not add nullable",
    ),
    "a RESTRICT key from a new table": (
        "op.create_table('drafts', sa.Column('note_id', sa.Uuid(),"
        " sa.ForeignKey('notes.id', ondelete='RESTRICT')))",
        "CASCADE or SET NULL",
    ),
    "a key from a new table that chose no action": (
        "op.create_table('drafts', sa.Column('note_id', sa.Uuid()),"
        " sa.ForeignKeyConstraint(['note_id'], ['notes.id']))",
        "no ondelete",
    ),
    "an operation the list does not name": ("op.create_table_comment('notes', 'x')", "create_table_comment"),
    "a custom operation on the op handle": ("op.create_sequence('notes_seq')", "does not name"),
}


@pytest.mark.parametrize(("body", "named"), list(_REFUSED.values()), ids=list(_REFUSED))
def test_an_operation_off_the_list_is_refused_once(
    tmp_path: pathlib.Path, body: str, named: str
) -> None:
    app = tmp_path / "app"
    _write(app, _REVISION, _marked(body))
    found = check_expand_revisions_only_expand(app)
    assert len(found) == 1, [violation.message for violation in found]
    assert found[0].rule == "expand_revisions_only_expand"
    assert named in found[0].message
    # The message says what to do, and that no marker excuses it.
    assert "expand_only = False" in found[0].message
    assert "No marker excuses it" in found[0].message


def test_a_revision_that_makes_no_promise_is_not_read(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    for header in ("", "expand_only = False\n"):
        _write(app, _REVISION, f"{header}def upgrade():\n    op.drop_column('notes', 'legacy')\n")
        assert check_expand_revisions_only_expand(app) == []


def test_a_mark_the_check_cannot_read_is_refused(tmp_path: pathlib.Path) -> None:
    # The run evaluates the expression; the check cannot, so it takes neither answer.
    app = tmp_path / "app"
    _write(app, _REVISION, "expand_only = EXPANDING\ndef upgrade():\n    pass\n")
    found = check_expand_revisions_only_expand(app)
    assert [violation.line for violation in found] == [1]
    assert "not the literal True or False" in found[0].message


def test_a_merge_revision_is_off_the_list(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(
        app,
        _REVISION,
        "down_revision = ('aaa', 'bbb')\nexpand_only = True\ndef upgrade():\n    pass\n",
    )
    found = check_expand_revisions_only_expand(app)
    assert [violation.line for violation in found] == [1]
    assert "merge revision" in found[0].message


def test_a_key_onto_a_soft_deleted_table_is_refused(tmp_path: pathlib.Path) -> None:
    # Neither action can ever fire onto a table whose rows are stamped, not deleted.
    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/models.py",
        "from terp.core import BaseTable, SoftDeleteMixin\n"
        "class Note(SoftDeleteMixin, BaseTable, table=True):\n"
        "    __tablename__ = 'notes'\n",
    )
    _write(
        app,
        _REVISION,
        _marked(
            "op.create_table('drafts', sa.Column('note_id', sa.Uuid(),"
            " sa.ForeignKey('notes.id', ondelete='CASCADE')))"
        ),
    )
    found = check_expand_revisions_only_expand(app)
    assert len(found) == 1 and "soft-deleted" in found[0].message


def test_no_marker_excuses_an_off_list_operation(tmp_path: pathlib.Path) -> None:
    """Neither this rule's own token nor ``no_destructive_migrations``' suppresses it."""
    app = tmp_path / "app"
    assert RULES_WITHOUT_AN_OPT_OUT == {"expand_revisions_only_expand"}
    for marker in (
        "# arch-allow-expand-revisions-only-expand: reviewed",
        "# arch-allow-no-destructive-migrations: reviewed",
    ):
        _write(app, _REVISION, _marked(f"{marker}\nop.drop_column('notes', 'legacy')"))
        assert "expand_revisions_only_expand" in {violation.rule for violation in check_app(app)}

    # And the budget refuses the token outright: it names no rule with a governed opt-out.
    budget = tmp_path / "escape-hatch-budget.json"
    budget.write_text(json.dumps({"arch-allow-expand-revisions-only-expand": 1}), encoding="utf-8")
    _write(
        app,
        _REVISION,
        _marked("# arch-allow-expand-revisions-only-expand: reviewed\nop.drop_column('notes', 'x')"),
    )
    refusals = check_escape_hatch_budget(app, budget_path=budget)
    assert any(
        "arch-allow-expand-revisions-only-expand" in violation.message for violation in refusals
    )
