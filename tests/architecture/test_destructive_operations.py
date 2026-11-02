"""``destructive_operations``: what ``no_destructive_migrations`` finds, as a list a reader can sign.

A reader that lists a release's destructive steps, rather than gating them, needs each
one named and told apart: its kind, its line, its place in the revision and a line of
text an approver can read. The rule's findings carry none of that but the line, so the
rule now reports exactly this list's five kinds, one finding per operation. The tests
below hold the list to the rule's own test set, every kind with its text written out,
and hold the rule to the list, so the gate and such a reader can never disagree about
what is destructive.

The list holds one more kind the rule never reports, ``opaque``: what the reading cannot
see into, a statement with no static text or a call it cannot follow. A reader that must
not miss a step has a person confirm each one, so it is held here just as exactly.
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
    _FOLLOWED,
    _LOOK_ALIKES,
    _MORE,
    _NOT_FOLLOWED,
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
    "raw drop schema": "execute: DROP SCHEMA billing CASCADE",
    "drop by a literal getattr": "drop_table note",
    "a literal getattr on a batch handle": "alter_column note.title",
    "raw unique is never NOT VALID": "execute: ALTER TABLE note ADD CONSTRAINT uq UNIQUE (slug) NOT VALID",
    # The statement that is destructive, not the text it was split from.
    "second statement adds the constraint": "execute: ALTER TABLE note ADD UNIQUE (slug)",
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


#: The look-alikes that run something the reading cannot see into, and what each lists.
_OPAQUE_LOOK_ALIKES = {
    "a statement the rule cannot read": ["execute: ?", "execute: ?", "execute: ?"],
    "an unrelated call": ["call helper"],
    "an unrelated context manager": ["call open_session", "call lock"],
}


@pytest.mark.parametrize("name,body", _LOOK_ALIKES, ids=[name for name, _ in _LOOK_ALIKES])
def test_a_look_alike_is_no_destructive_operation(name: str, body: str) -> None:
    listed = destructive_operations(_source(body))
    assert [(o.kind, o.operation) for o in listed] == [
        ("opaque", text) for text in _OPAQUE_LOOK_ALIKES.get(name, [])
    ], name


def test_the_opaque_look_alikes_are_look_alikes() -> None:
    assert set(_OPAQUE_LOOK_ALIKES) <= {name for name, _ in _LOOK_ALIKES}


def _revisions() -> list[tuple[str, str]]:
    """Every revision the rule is held to: its test set, the spec corpus, the framework's own."""
    found = [(case.name, _source(case.body)) for case in _CASES]
    found += [(name, _source(body)) for name, body in _LOOK_ALIKES]
    found += [(name, textwrap.dedent(source).lstrip("\n")) for name, source, _ in _FOLLOWED]
    found += [(name, textwrap.dedent(source).lstrip("\n")) for name, source in _NOT_FOLLOWED]
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
        (operation.line, _MESSAGES[operation.kind])
        for operation in destructive_operations(source)
        if operation.kind != "opaque"
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


#: The text of each operation the rule finds beyond what ``upgrade()`` spells itself.
_FOLLOWED_TEXTS = {
    "a helper upgrade() calls": ["drop_column invoice.legacy_ref"],
    "helpers that call each other, each read once": [
        "drop_table invoice_legacy",
        "alter_column invoice.ref",
    ],
    "an operation imported by name": [
        "drop_column invoice.legacy_ref",
        "rename_table invoice",
        "alter_column invoice.total",
    ],
    "upgrade named by an alias": ["drop_table invoice_legacy"],
    "an alias chain that comes back on itself ends": ["drop_table invoice_legacy"],
    "two statements in one call": [
        "execute: DROP TABLE invoice_legacy",
        "execute: ALTER TABLE invoice RENAME TO bill",
    ],
    "a dollar-quoted body is one statement": [
        "execute: DO $$ BEGIN DROP TABLE invoice_a; DROP TABLE invoice_b; END $$"
    ],
    "a table created by name is still new": ["alter_column invoice.title"],
}


@pytest.mark.parametrize(("name", "source", "found"), _FOLLOWED, ids=[n for n, _, _ in _FOLLOWED])
def test_what_the_migration_runs_is_listed(name: str, source: str, found: list[tuple[int, str]]) -> None:
    assert set(_FOLLOWED_TEXTS) == {case for case, _, _ in _FOLLOWED}
    listed = destructive_operations(textwrap.dedent(source).lstrip("\n"))
    assert [(o.ordinal, o.line, o.kind, o.operation) for o in listed] == [
        (ordinal, line, kind, text)
        for ordinal, ((line, kind), text) in enumerate(zip(found, _FOLLOWED_TEXTS[name], strict=True), 1)
    ], name


# --------------------------------------------------------------------------- #
# opaque: what the reading cannot see into
# --------------------------------------------------------------------------- #
_OPAQUE_HEAD = (
    "import uuid\n"
    "from datetime import datetime\n"
    "\n"
    "import sqlalchemy as sa\n"
    "from alembic import op\n"
    "from sqlalchemy import text\n"
    "\n"
    "import app_steps\n"
    "from app.steps import contract\n"
    "from .local_steps import tidy\n"
    "\n"
    "len = app_steps.length\n"
    "\n"
    "\n"
    "class _Steps:\n"
    "    pass\n"
    "\n"
    "\n"
    "def upgrade():\n"
)


@pytest.mark.parametrize(
    "body,listed",
    [
        # An executed statement whose text is not in the source.
        ("op.execute(statement)", [("opaque", "execute: ?")]),
        ("op.get_bind().exec_driver_sql(statement)", [("opaque", "exec_driver_sql: ?")]),
        ("op.execute(sa.text(statement))", [("opaque", "execute: ?")]),
        ("op.execute(invoice.delete().where(invoice.c.state == 'void'))", [("opaque", "execute: ?")]),
        ("op.execute(sqltext=statement)", [("opaque", "execute: ?")]),
        ("op.execute()", [("opaque", "execute: ?")]),
        # One whose text is, however it is spelt.
        ("op.execute(sa.text('UPDATE invoice SET state = :s').bindparams(s='open'))", []),
        ("op.execute(text(text='UPDATE invoice SET state = 1').columns())", []),
        ("op.execute(sqltext=f'UPDATE {table} SET state = 1')", []),
        ("op.get_bind().execute(statement=sa.text('SELECT 1'))", []),
        # A drop read from the text, and the rest of the call still unread.
        ("op.execute(statement, 'TRUNCATE invoice')", [("drop", "execute: TRUNCATE invoice"), ("opaque", "execute: ?")]),
        # A call the reading cannot follow.
        ("contract('invoice')", [("opaque", "call contract")]),
        ("tidy()", [("opaque", "call tidy")]),
        ("app_steps.contract('invoice')", [("opaque", "call app_steps.contract")]),
        ("app_steps.legacy.contract()", [("opaque", "call app_steps.legacy.contract")]),
        ("getattr(app_steps, 'contract')()", [("opaque", "call app_steps.contract")]),
        ("_Steps()", [("opaque", "call _Steps")]),
        ("_Steps.run()", [("opaque", "call _Steps.run")]),
        ("drop = op.drop_table\ndrop('invoice')", [("opaque", "call drop")]),
        ("from alembic.op import drop_table\ndrop_table('invoice')", [("opaque", "call drop_table")]),
        ("exec(\"op.drop_table('invoice')\")", [("opaque", "call exec")]),
        ("len(rows)", [("opaque", "call len")]),
        ("getattr(op, name)('invoice')", [("opaque", "call getattr")]),
        ("steps[0]()", [("opaque", "call ?")]),
        ("make()()", [("opaque", "call ?"), ("opaque", "call make")]),
        # An operation is read by its name, on any receiver: never opaque as well.
        ("app_steps.drop_table('invoice')", [("drop", "drop_table invoice")]),
        # What runs nothing the reading needs: a library, a builtin, a function it reads.
        (
            "print(uuid.uuid4(), datetime.now(), text('SELECT 1'), sorted([]))\n"
            "op.add_column('invoice', sa.Column('ref', sa.String(20)))\n"
            "def _local():\n"
            "    return 1\n"
            "_local()",
            [],
        ),
    ],
)
def test_what_the_reading_cannot_see_into_is_opaque(body: str, listed: list[tuple[str, str]]) -> None:
    source = _OPAQUE_HEAD + textwrap.indent(body, "    ") + "\n"
    assert [(o.kind, o.operation) for o in destructive_operations(source)] == listed


def test_an_opaque_operation_is_never_a_finding(tmp_path: pathlib.Path) -> None:
    source = _OPAQUE_HEAD + "    contract('invoice')\n    op.execute(statement)\n"
    app = tmp_path / "app"
    path = app / _REVISION
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    assert check_no_destructive_migrations(app) == []
    assert [o.kind for o in destructive_operations(source)] == ["opaque", "opaque"]


def test_a_helper_that_is_read_lists_what_it_cannot_follow_once() -> None:
    source = (
        "from alembic import op\n"
        "from app.steps import contract\n\n\n"
        "def _shared():\n"
        "    contract('invoice')\n\n\n"
        "def upgrade():\n"
        "    _shared()\n"
        "    _shared()\n"
    )
    assert destructive_operations(source) == [DestructiveOperation(1, "opaque", 6, "call contract")]


#: What each whole revision the rule follows lists as opaque besides its findings.
_NOT_FOLLOWED_OPAQUE = {
    "a helper only downgrade() calls": [],
    "a semicolon inside a quoted string, a quoted name, a comment or a dollar-quoted body": [],
    "an operation named by a computed getattr": ["call getattr"],
    "a statement held in a variable": ["execute: ?"],
    "a helper from another module, a callable bound to a name, an attribute alias": [
        "call contract",
        "call remove",
    ],
}


@pytest.mark.parametrize("name,source", _NOT_FOLLOWED, ids=[name for name, _ in _NOT_FOLLOWED])
def test_what_the_rule_cannot_read_is_listed_opaque(name: str, source: str) -> None:
    assert set(_NOT_FOLLOWED_OPAQUE) == {case for case, _ in _NOT_FOLLOWED}
    listed = destructive_operations(textwrap.dedent(source).lstrip("\n"))
    assert [(o.kind, o.operation) for o in listed] == [
        ("opaque", text) for text in _NOT_FOLLOWED_OPAQUE[name]
    ], name
