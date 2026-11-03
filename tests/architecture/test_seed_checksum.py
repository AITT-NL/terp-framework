"""A seed is deterministic: a second run writes nothing, and two fresh runs agree.

"The same state twice, verified by a checksum" cannot pass as first written, because a
fresh run does not reproduce what a write generates: every primary key is a fresh
``uuid4``, every timestamp is the moment of that run, a password hash carries a fresh
salt, and every owner, actor stamp and audit target carries some row's generated id.
Seeding the reference app twice into fresh databases differs in exactly those columns
and in no other.

So the claim is made over the BUSINESS columns, by the rule ``seed_checksum`` states:
leave out a table's own single-column primary key and every ``DateTime``, compare a PHC
hash by its scheme and parameters, and compare a reference through the row it points
at. The first half of this module holds that rule to its edges; the second holds the
two seeds the framework ships — the reference app's and the one a new project is
rendered with — to both properties, on SQLite and again on PostgreSQL.
"""

from __future__ import annotations

import datetime
import importlib
import importlib.util
import pathlib
import uuid
from collections.abc import Callable, Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from terp.core.testing import seed_checksum

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------- #
# the rule
# --------------------------------------------------------------------------- #
_HASH = "$argon2id$v=19$m=65536,t=3,p=4${salt}${digest}"


def _schema() -> sa.MetaData:
    metadata = sa.MetaData()
    sa.Table(
        "person",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(100)),
        sa.Column("hashed_password", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("joined_on", sa.Date()),
    )
    sa.Table(
        "task",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(100)),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("person.id")),
        # An untyped reference, as an audit record keeps its target: text, not a UUID.
        sa.Column("target", sa.String(36)),
        sa.Column("payload", sa.JSON()),
        sa.Column("tenant_id", sa.Uuid()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    sa.Table(
        "membership",
        metadata,
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("person.id"), primary_key=True),
        sa.Column("team", sa.String(20), primary_key=True),
    )
    sa.Table(
        "counter",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(20)),
        sa.Column("amount", sa.Numeric(10, 2)),
        sa.Column("blob", sa.LargeBinary()),
    )
    # Declared, never created: a table the database does not hold is not read.
    sa.Table("absent", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    return metadata


_TENANT = uuid.uuid5(uuid.NAMESPACE_DNS, "example.test")


def _populate(
    tmp_path: pathlib.Path,
    name: str,
    *,
    owner: int = 0,
    title: str = "Write the plan",
    scheme: str = "m=65536,t=3,p=4",
    joined_on: datetime.date = datetime.date(2026, 1, 1),
    dangling: bool = False,
    reverse: bool = False,
    counter_id: int | None = None,
) -> tuple[Engine, sa.MetaData]:
    """A database with the same business content each time, and fresh generated values."""
    metadata = _schema()
    engine = create_engine(f"sqlite:///{(tmp_path / f'{name}.db').as_posix()}")
    tables = [metadata.tables[n] for n in ("person", "task", "membership", "counter")]
    metadata.create_all(engine, tables=tables)
    people = [uuid.uuid4(), uuid.uuid4()]
    now = datetime.datetime.now(datetime.UTC)
    person_rows = [
        {
            "id": people[index],
            "email": email,
            "hashed_password": _HASH.replace("m=65536,t=3,p=4", scheme).format(
                salt=uuid.uuid4().hex, digest=uuid.uuid4().hex
            ),
            "created_at": now,
            "joined_on": joined_on,
        }
        for index, email in enumerate(("admin@example.test", "editor@example.test"))
    ]
    target = uuid.uuid4() if dangling else people[owner]
    task_rows = [
        {
            "id": uuid.uuid4(),
            "title": title,
            "owner_id": people[owner],
            "target": str(target),
            "payload": {"actor": str(people[owner]), "steps": [str(people[1]), 3]},
            "tenant_id": _TENANT,
            "updated_at": now,
        },
        {
            "id": uuid.uuid4(),
            "title": "Review it",
            "owner_id": people[1],
            "target": None,
            "payload": None,
            "tenant_id": _TENANT,
            "updated_at": now,
        },
    ]
    if reverse:
        person_rows.reverse()
        task_rows.reverse()
    with engine.begin() as connection:
        connection.execute(metadata.tables["person"].insert(), person_rows)
        connection.execute(metadata.tables["task"].insert(), task_rows)
        connection.execute(
            metadata.tables["membership"].insert(),
            [{"person_id": people[0], "team": "core"}],
        )
        counter: dict[str, object] = {"name": "visits", "amount": "12.50", "blob": b"\x00\x01"}
        if counter_id is not None:
            counter["id"] = counter_id
        connection.execute(metadata.tables["counter"].insert(), [counter])
    return engine, metadata


def _checksum(engine: Engine, metadata: sa.MetaData, **kwargs: bool) -> str:
    try:
        return seed_checksum(engine, metadata=metadata, **kwargs)
    finally:
        engine.dispose()


def test_two_runs_with_fresh_ids_timestamps_and_salts_agree(tmp_path: pathlib.Path) -> None:
    first = _checksum(*_populate(tmp_path, "a"))
    second = _checksum(*_populate(tmp_path, "b"))
    assert first == second
    # And the order the rows went in, or come back in, does not count.
    assert _checksum(*_populate(tmp_path, "c", reverse=True)) == first
    # Nor does the key a sequence handed out: an integer id is generated as well.
    assert _checksum(*_populate(tmp_path, "d", counter_id=7)) == first


def test_every_column_counts_when_generated_values_are_asked_for(tmp_path: pathlib.Path) -> None:
    engine, metadata = _populate(tmp_path, "a")
    with engine.connect() as connection:
        # Read twice with nothing written in between: the same, by Engine and by Connection.
        assert seed_checksum(connection, metadata=metadata, generated=True) == seed_checksum(
            engine, metadata=metadata, generated=True
        )
    before = _checksum(engine, metadata, generated=True)
    assert _checksum(*_populate(tmp_path, "b"), generated=True) != before


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"title": "Write the other plan"}, id="a business value"),
        pytest.param({"owner": 1}, id="who a reference points at"),
        pytest.param({"scheme": "m=19456,t=2,p=1"}, id="a hash's parameters"),
        pytest.param({"joined_on": datetime.date(2026, 2, 1)}, id="a date the seed set"),
        pytest.param({"dangling": True}, id="a reference to no row"),
    ],
)
def test_a_business_difference_changes_the_checksum(
    tmp_path: pathlib.Path, change: dict[str, object]
) -> None:
    assert _checksum(*_populate(tmp_path, "a")) != _checksum(
        *_populate(tmp_path, "b", **change)  # type: ignore[arg-type]
    )


def test_the_default_metadata_is_the_one_every_model_registers_on(tmp_path: pathlib.Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    try:
        # No model table exists in an empty database, so nothing is read; the checksum is
        # still a checksum, and the same one each time.
        assert seed_checksum(engine) == seed_checksum(engine)
    finally:
        engine.dispose()


def test_a_type_decorated_timestamp_is_still_a_timestamp() -> None:
    from terp.core._seed_checksum import _is_timestamp

    class Stamp(sa.types.TypeDecorator[datetime.datetime]):
        impl = sa.DateTime
        cache_ok = True

    assert _is_timestamp(sa.Column("at", Stamp()))
    assert not _is_timestamp(sa.Column("on", sa.Date()))


def test_values_are_carried_by_meaning() -> None:
    from terp.core._seed_checksum import _phc_scheme, _plain, _uuid_key

    assert _phc_scheme("$2b$12$abcdefghijklmnopqrstuv") == "$2b"
    assert _phc_scheme("$5 off") is None
    assert _uuid_key("z" * 32) is None
    assert _plain(datetime.time(9, 30)) == "09:30:00"
    assert _plain(("a", 1)) == ["a", 1]
    assert _plain(_Opaque()) == "<opaque>"


class _Opaque:
    def __repr__(self) -> str:
        return "<opaque>"


# --------------------------------------------------------------------------- #
# the seeds the framework ships
# --------------------------------------------------------------------------- #
#: The reference app's tables: the ones its own test fixtures create.
_MODEL_MODULES = (
    "app.modules.journals.models",
    "app.modules.notes.models",
    "app.modules.projects.models",
    "app.modules.tasks.models",
    "terp.capabilities.access.models",
    "terp.capabilities.audit.models",
    "terp.capabilities.files.models",
    "terp.capabilities.groups.models",
    "terp.capabilities.identity.models",
    "terp.capabilities.outbox.models",
    "terp.capabilities.webhooks.models",
)


def _reference_tables() -> list[sa.Table]:
    tables: set[sa.Table] = set()
    for name in _MODEL_MODULES:
        for value in vars(importlib.import_module(name)).values():
            table = getattr(value, "__table__", None)
            if isinstance(table, sa.Table):
                tables.add(table)
    return sorted(tables, key=lambda table: table.name)


def _reference_seed(tmp_path: pathlib.Path) -> Callable[[Session], object]:
    from app.seed import seed

    return seed


def _template_seed(tmp_path: pathlib.Path) -> Callable[[Session], object]:
    """The seed a new project is rendered with, rendered and imported from a file."""
    source = (_REPO_ROOT / "template" / "project" / "app" / "seed.py.jinja").read_text(
        encoding="utf-8"
    )
    path = tmp_path / "rendered_template_seed.py"
    path.write_text(source.replace("{{ project_name }}", "Example"), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("rendered_template_seed", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.seed


@pytest.fixture
def seeded_engine(terp_db_url: str) -> Iterator[tuple[Engine, list[sa.Table]]]:
    from app.main import build

    build()  # the runtime a seed writes through: audit, events, the password policy
    tables = _reference_tables()
    engine = create_engine(terp_db_url)
    try:
        yield engine, tables
    finally:
        tables[0].metadata.drop_all(engine, tables=tables)
        engine.dispose()


def _seed(engine: Engine, seed: Callable[[Session], object]) -> None:
    with Session(engine) as session:
        seed(session)
        session.commit()


@pytest.mark.parametrize(
    "load_seed",
    [pytest.param(_reference_seed, id="reference app"), pytest.param(_template_seed, id="template")],
)
def test_the_seed_is_deterministic(
    seeded_engine: tuple[Engine, list[sa.Table]],
    load_seed: Callable[[pathlib.Path], Callable[[Session], object]],
    tmp_path: pathlib.Path,
) -> None:
    engine, tables = seeded_engine
    metadata = tables[0].metadata
    seed = load_seed(tmp_path)

    metadata.create_all(engine, tables=tables)
    _seed(engine, seed)
    first = seed_checksum(engine)
    stored = seed_checksum(engine, generated=True)

    # A second run on the same database writes nothing: not a row added, changed or
    # re-stamped, so even the generated columns are what they were.
    _seed(engine, seed)
    assert seed_checksum(engine, generated=True) == stored
    assert seed_checksum(engine) == first

    # A fresh database seeded again holds the same business data, though every id,
    # timestamp and salt in it is new.
    metadata.drop_all(engine, tables=tables)
    metadata.create_all(engine, tables=tables)
    _seed(engine, seed)
    assert seed_checksum(engine, generated=True) != stored
    assert seed_checksum(engine) == first
