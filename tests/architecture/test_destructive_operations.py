"""``destructive_operations``: what ``no_destructive_migrations`` finds, as a list a reader can sign.

A reader that lists a release's destructive steps, rather than gating them, needs each
one named and told apart: its kind, its line, its place in the revision and a line of
text an approver can read. The rule's findings carry none of that but the line, so the
rule now reports exactly this list, one finding per operation. The tests below hold the
list to the rule's own test set, every kind with its text written out, and hold the rule
to the list, so the gate and such a reader can never disagree about what is destructive.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest
from terp_spec import spec_dir

from terp.arch import (
    DestructiveOperation,
    check_app,
    check_no_destructive_migrations,
    destructive_operations,
)
from terp.arch.rules.destructive_migrations import _MESSAGES
from tests.architecture.test_destructive_migrations import (
    _LOOK_ALIKES,
    _MORE,
    _REVISION,
    _TWENTY,
    _Case,
)

_REPO = pathlib.Path(__file__).resolve().parents[2]
_HEAD = "import sqlalchemy as sa\nfrom alembic import op\n\n\ndef upgrade():\n"


def _source(body: str) -> str:
    """A revision whose ``upgrade()`` is *body*, laid out as the rule's own tests write it."""
    return _HEAD + textwrap.indent(textwrap.dedent(body).strip("\n"), "    ") + "\n"


def _last_line(body: str) -> int:
    return _HEAD.count("\n") + len(textwrap.dedent(body).strip("\n").splitlines())


#: The text of every case in the rule's test set, by case name: every kind, every call
#: the rule reads, the op, batch and raw-SQL forms, and a table that is not a literal.
_TEXTS = {
    # the twenty
    "drop table": "drop_table note",
    "drop column": "drop_column note.legacy",
    "rename column": "alter_column note.title",
    "rename table": "rename_table note",
    "type narrowing": "alter_column note.title",
    "not null tightening": "alter_column note.title",
    "not null tightening by keyword": "alter_column note.title",
    "unique constraint": "create_unique_constraint note",
    "foreign key on an existing column": "create_foreign_key note",
    "check constraint": "create_check_constraint note",
    "unique index": "create_index note",
    "raw truncate": "execute: TRUNCATE note",
    "raw delete": "execute: DELETE FROM note WHERE archived",
    "raw rename": "execute: ALTER TABLE note RENAME COLUMN title TO heading",
    "raw type change": "execute: ALTER TABLE note ALTER COLUMN title TYPE varchar(50)",
    "raw set not null": "execute: ALTER TABLE note ALTER COLUMN title SET NOT NULL",
    "raw add constraint": "execute: ALTER TABLE note ADD CONSTRAINT uq_note_slug UNIQUE (slug)",
    "batch drop column": "drop_column note.legacy",
    "batch rename column": "alter_column note.title",
    "batch not null tightening": "alter_column note.title",
    # the further spellings
    "raw rename table": "execute: ALTER TABLE note RENAME TO entry",
    "mysql rename table": "execute: RENAME TABLE note TO entry",
    "f-string rename": "execute: ALTER TABLE ? RENAME TO entry",
    "concatenated rename": "execute: ALTER TABLE ? RENAME TO entry",
    "rename through the driver": "exec_driver_sql: ALTER TABLE note RENAME TO entry",
    "raw type change, no COLUMN": "execute: ALTER TABLE note ALTER type TYPE text",
    "raw set data type": "execute: ALTER TABLE note ALTER COLUMN rank SET DATA TYPE smallint",
    "raw unique index": "execute: CREATE UNIQUE INDEX ix_note_slug ON note (slug)",
    "raw validate": "execute: ALTER TABLE note VALIDATE CONSTRAINT ck_note_rank",
    "raw unique is never NOT VALID": "execute: ALTER TABLE note ADD CONSTRAINT uq UNIQUE (slug) NOT VALID",
    "second statement adds the constraint": (
        "execute: ALTER TABLE note ADD COLUMN slug text; ALTER TABLE note ADD UNIQUE (slug)"
    ),
    "primary key on an existing table": "create_primary_key note",
    "exclude constraint": "create_exclude_constraint note",
    "batch type change": "alter_column note.title",
    "batch unique constraint": "create_unique_constraint note",
    "batch unique index": "create_index note",
    "batch foreign key on an existing column": "create_foreign_key note",
    "aliased handle": "alter_column note.title",
    "a table that is not a literal may hold rows": "alter_column ?.title",
    "a tightening that names no table at all": "alter_column ?.title",
    "a constraint on a table that is not a literal": "create_unique_constraint ?",
    "two tables that are not literals are never taken to be one": "create_unique_constraint ?",
    "a batch block whose table is not a literal": "alter_column ?.title",
    "a new column with a server default holds it, not NULL": "create_unique_constraint note",
    "a new NOT NULL column holds values": "create_index note",
    "a new primary-key column": "create_unique_constraint note",
    "a new column whose name is not a literal": "create_unique_constraint note",
    "a check constraint on a new column is still read": "create_check_constraint note",
    "constraint columns that are not literals": "create_unique_constraint note",
    "one constraint column is not new": "create_unique_constraint note",
    "tightening a column this upgrade just added still races the running release": (
        "alter_column note.rank"
    ),
}

_CASES: tuple[_Case, ...] = (*_TWENTY, *_MORE)


def test_every_case_of_the_rule_has_its_text_written_out() -> None:
    assert set(_TEXTS) == {case.name for case in _CASES}
    assert {case.kind for case in _CASES} == set(_MESSAGES)


@pytest.mark.parametrize("case", _CASES, ids=[case.name for case in _CASES])
def test_each_operation_is_named_exactly(case: _Case) -> None:
    assert destructive_operations(_source(case.body)) == [
        DestructiveOperation(
            ordinal=1, kind=case.kind, line=_last_line(case.body), operation=_TEXTS[case.name]
        )
    ]


@pytest.mark.parametrize("name,body", _LOOK_ALIKES, ids=[name for name, _ in _LOOK_ALIKES])
def test_a_look_alike_is_no_operation(name: str, body: str) -> None:
    assert destructive_operations(_source(body)) == [], name


def _revisions() -> list[tuple[str, str]]:
    """Every revision the rule is held to: its test set, the spec corpus, the framework's own."""
    found = [(case.name, _source(case.body)) for case in _CASES]
    found += [(name, _source(body)) for name, body in _LOOK_ALIKES]
    corpus = spec_dir() / "corpus" / "backend" / "no_destructive_migrations"
    found += [
        (f"corpus {path.relative_to(corpus).as_posix()}", path.read_text(encoding="utf-8"))
        for path in sorted(corpus.rglob("*.py"))
    ]
    found += [
        (path.relative_to(_REPO).as_posix(), path.read_text(encoding="utf-8"))
        for root in ("packages/backend", "apps/example/app")
        for path in sorted((_REPO / root).rglob("migrations/versions/*.py"))
    ]
    return found


@pytest.mark.parametrize("name,source", _revisions(), ids=[name for name, _ in _revisions()])
def test_the_rule_reports_exactly_the_operations(
    tmp_path: pathlib.Path, name: str, source: str
) -> None:
    app = tmp_path / "app"
    path = app / _REVISION
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    assert [(v.line, v.message) for v in check_no_destructive_migrations(app)] == [
        (operation.line, _MESSAGES[operation.kind]) for operation in destructive_operations(source)
    ], name


def test_the_corpus_is_read_and_holds_operations() -> None:
    """The equivalence above is not vacuous: the corpus is found, and its violations list some."""
    corpus = [source for name, source in _revisions() if name.startswith("corpus violation-")]
    assert len(corpus) >= 5
    assert all(destructive_operations(source) for source in corpus)


def test_ordinals_count_from_one_in_source_order() -> None:
    source = _source(
        "op.drop_column('invoice', 'legacy_ref')\n"
        "with op.batch_alter_table('customer') as batch_op:\n"
        "    batch_op.alter_column('email', nullable=False)\n"
        "    batch_op.create_unique_constraint('uq_customer_email', ['email'])\n"
        "op.execute('TRUNCATE invoice_run')\n"
        "op.rename_table('ledger', 'journal'); op.drop_table('ledger_old')\n"
        "op.alter_column(\n"
        "    'customer',\n"
        "    'name',\n"
        "    type_=sa.String(50),\n"
        ")\n"
    )
    assert destructive_operations(source) == [
        DestructiveOperation(1, "drop", 6, "drop_column invoice.legacy_ref"),
        DestructiveOperation(2, "not-null", 8, "alter_column customer.email"),
        DestructiveOperation(3, "constraint", 9, "create_unique_constraint customer"),
        DestructiveOperation(4, "drop", 10, "execute: TRUNCATE invoice_run"),
        # Two on one line are told apart by their column.
        DestructiveOperation(5, "rename", 11, "rename_table ledger"),
        DestructiveOperation(6, "drop", 11, "drop_table ledger_old"),
        # A call over several lines is on the line it starts on.
        DestructiveOperation(7, "type", 12, "alter_column customer.name"),
    ]


def test_source_order_holds_wherever_an_upgrade_sits() -> None:
    """The rule reads every function named ``upgrade``; the list is still in line order."""
    source = (
        "class Legacy:\n"
        "    def upgrade(self):\n"
        "        op.drop_table('legacy')\n"
        "\n\n"
        "def upgrade():\n"
        "    op.drop_table('current')\n"
    )
    assert [(o.ordinal, o.line, o.operation) for o in destructive_operations(source)] == [
        (1, 3, "drop_table legacy"),
        (2, 7, "drop_table current"),
    ]


def test_an_excused_operation_is_still_listed(tmp_path: pathlib.Path) -> None:
    body = (
        "# arch-allow-no-destructive-migrations: contract step, expanded in the last release\n"
        "op.drop_column('invoice', 'legacy_ref')\n"
        "op.alter_column('invoice', 'total', nullable=False)\n"
    )
    app = tmp_path / "app"
    path = app / _REVISION
    path.parent.mkdir(parents=True)
    path.write_text(_source(body), encoding="utf-8")
    # The gate excuses the marked step and reports the other one ...
    assert [(v.rule, v.line) for v in check_app(app)] == [("no_destructive_migrations", 8)]
    # ... and both are destructive, so both are listed.
    assert destructive_operations(_source(body)) == [
        DestructiveOperation(1, "drop", 7, "drop_column invoice.legacy_ref"),
        DestructiveOperation(2, "not-null", 8, "alter_column invoice.total"),
    ]


def test_only_upgrade_is_read() -> None:
    assert destructive_operations("def downgrade():\n    op.drop_table('note')\n") == []
    assert destructive_operations("revision = 'a1'\ndown_revision = None\n") == []
    assert destructive_operations("") == []


def test_source_that_does_not_parse_is_refused_as_the_rule_refuses_it(
    tmp_path: pathlib.Path,
) -> None:
    source = "def upgrade(:\n    op.drop_table('note')\n"
    app = tmp_path / "app"
    path = app / _REVISION
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    with pytest.raises(SyntaxError):
        check_no_destructive_migrations(app)
    with pytest.raises(SyntaxError):
        destructive_operations(source)


def test_the_revision_is_never_executed(tmp_path: pathlib.Path) -> None:
    ran = tmp_path / "ran"
    source = (
        f"import pathlib\npathlib.Path({str(ran)!r}).write_text('module')\n"
        "raise SystemExit('a revision read as data never runs')\n\n\n"
        f"def upgrade():\n    pathlib.Path({str(ran)!r}).write_text('upgrade')\n"
        "    op.drop_table('note')\n"
    )
    assert destructive_operations(source) == [
        DestructiveOperation(1, "drop", 8, "drop_table note")
    ]
    assert not ran.exists()


@pytest.mark.parametrize(
    "body,text",
    [
        # Layout is not content: each run of white space or control characters is one
        # space, and the ends are trimmed.
        ("op.execute('''\n    TRUNCATE\n        note\n''')", "execute: TRUNCATE note"),
        ("op.execute(' TRUNCATE\\t\\x0bnote\\r\\n')", "execute: TRUNCATE note"),
        ("op.drop_table('a\\x00b\\x7fc\\x85d\\xa0e\\u2028f\\u3000g')", "drop_table a b c d e f g"),
        ("op.drop_column('note', 'x\\x1fy')", "drop_column note.x y"),
        # A statement passed by keyword, and the destructive one of two.
        ("op.execute(sqltext='TRUNCATE note')", "execute: TRUNCATE note"),
        ("conn.exec_driver_sql('SELECT 1', 'DELETE FROM note')", "exec_driver_sql: DELETE FROM note"),
        # An interpolated part is a placeholder, read as the rule reads it.
        ("op.execute(f'DROP TABLE note_{suffix}')", "execute: DROP TABLE note_ ?"),
        ("op.execute('DROP TABLE ' + name)", "execute: DROP TABLE ?"),
        # Names that are not literals.
        ("op.drop_table(name)", "drop_table ?"),
        ("op.drop_column(table, column)", "drop_column ?.?"),
        ("op.drop_column(table_name='note', column_name=f'c{n}')", "drop_column note.?"),
        ("op.rename_table(old_table_name='note', new_table_name='entry')", "rename_table note"),
        ("op.create_foreign_key('fk', source_table='note', referent_table='u', local_cols=['u'], remote_cols=['id'])",
         "create_foreign_key note"),
        ("with op.batch_alter_table(table_name='note') as b:\n    b.drop_column(column_name='legacy')",
         "drop_column note.legacy"),
        # A call on a handle with no batch block is read in the op form.
        ("batch_op.drop_column('note', 'legacy')", "drop_column note.legacy"),
    ],
)
def test_the_text_of_an_operation(body: str, text: str) -> None:
    [operation] = destructive_operations(_source(body))
    assert operation.operation == text


def test_a_long_statement_is_cut_at_two_hundred_code_points() -> None:
    def text_of(statement: str) -> str:
        [operation] = destructive_operations(_source(f"op.execute({statement!r})"))
        return operation.operation

    prefix = "execute: "
    exact = "DELETE FROM note WHERE " + "x" * (200 - len(prefix) - 23)
    assert text_of(exact) == prefix + exact
    assert len(text_of(exact)) == 200

    longer = exact + "y"
    assert text_of(longer) == (prefix + longer)[:199] + "\u2026"
    assert len(text_of(longer)) == 200

    # A cut that ends on a space drops it before the mark, and a code point outside the
    # Basic Multilingual Plane counts as one.
    spaced = "DELETE FROM note WHERE " + "x" * (199 - len(prefix) - 23 - 1) + " " + "z" * 40
    assert text_of(spaced) == (prefix + spaced)[:198] + "\u2026"
    wide = "DELETE FROM note WHERE " + "\U0001f600" * 300
    assert text_of(wide) == (prefix + wide)[:199] + "\u2026"
    assert len(text_of(wide)) == 200
