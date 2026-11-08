"""``terp secrets reseal`` works a batch of rows at a time, and never waits on a held row (ADR 0189).

A re-seal runs against a live database, beside workers that write the same tables: a queued
mail's row is claimed, sent and settled while the run walks the outbox. One transaction per
table kept every row it re-sealed locked until the whole table was done, so a worker's update
of any of them waited for the run, however large the table. These tests are written from
that seat, on SQLite and on PostgreSQL (``terp_db_url``) wherever both apply:

* a table larger than a batch is re-sealed whole, one transaction per batch, whatever its key;
* a batch that cannot be written rolls back alone: the batches before it keep their re-seal and
  are counted, and the table is named;
* a row deleted between the read and the write is counted as changed, and nothing is written;
* a row another transaction holds locked is passed over at once and counted as held, which keeps
  the verdict from being clean until the next run re-seals it (PostgreSQL alone: SQLite has no
  row locks, and its writers take turns).
"""

from __future__ import annotations

import pathlib
import secrets
import sys
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Column, Engine, Integer, MetaData, String, Table, create_engine, delete, event, insert, select
from sqlalchemy.exc import OperationalError

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli.reseal import ResealReport, survey
from terp.cli.reseal_report import render

from terp.core import SealState, check_sealed_value, encrypt_config, settings

_OLD = secrets.token_urlsafe(32)
_NEW = secrets.token_urlsafe(32)
_TABLE = "cli_reseal_batched"


@pytest.fixture(autouse=True)
def _old_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", _OLD)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", [])
    monkeypatch.setattr(settings, "SECRET_KEY_DECRYPT_FALLBACKS", [])


def _rotate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", _NEW)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", [_OLD])
    monkeypatch.setattr(settings, "SECRET_KEY_DECRYPT_FALLBACKS", [_OLD])


@pytest.fixture
def engine(terp_db_url: str) -> Iterator[Engine]:
    eng = create_engine(terp_db_url)
    yield eng
    eng.dispose()


def _single(mapping: MetaData) -> Table:
    return Table(
        _TABLE,
        mapping,
        Column("id", Integer, primary_key=True, autoincrement=False),
        Column("token", String(512), nullable=True),
    )


def _seed(engine: Engine, table: Table, rows: list[dict[str, Any]]) -> None:
    """*rows*, each with a value sealed under the current key in ``token``."""
    with engine.begin() as conn:
        conn.execute(insert(table), [{**row, "token": encrypt_config(f"value {index}")} for index, row in enumerate(rows)])


def _states(engine: Engine, table: Table) -> list[SealState]:
    keys = list(table.primary_key.columns)
    with engine.connect() as conn:
        tokens = conn.execute(select(table.c.token).order_by(*keys)).scalars().all()
    return [check_sealed_value(token).state for token in tokens]


def _counts(report: ResealReport) -> dict[str, int]:
    (tally,) = [tally for tally in report.columns if tally.table == _TABLE]
    names = ("current", "resealed", "fallback", "unreadable", "changed", "held")
    return {name: getattr(tally, name) for name in names if getattr(tally, name)}


def _commits(engine: Engine) -> list[None]:
    """Every transaction *engine* commits from now on, one entry each."""
    committed: list[None] = []
    event.listen(engine, "commit", lambda _conn: committed.append(None))
    return committed


def test_a_table_larger_than_a_batch_is_resealed_whole_one_transaction_per_batch(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    mapping = MetaData()
    table = _single(mapping)
    mapping.create_all(engine)
    _seed(engine, table, [{"id": key} for key in range(1, 6)])
    with engine.begin() as conn:  # a row holding nothing sealed is never read into a batch
        conn.execute(insert(table).values(id=6, token="plain text"))
    _rotate(monkeypatch)

    committed = _commits(engine)
    report = survey(engine, write=True, metadata=mapping, batch=2)
    assert _counts(report) == {"resealed": 5} and report.clean
    assert len(committed) == 3, "five sealed rows, two to a batch, each batch its own transaction"
    assert _states(engine, table)[:5] == [SealState.CURRENT] * 5


def test_a_composite_key_is_walked_in_its_own_order(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    mapping = MetaData()
    table = Table(
        _TABLE,
        mapping,
        Column("shelf", Integer, primary_key=True, autoincrement=False),
        Column("slot", String(8), primary_key=True),
        Column("token", String(512), nullable=True),
    )
    mapping.create_all(engine)
    keys = [(1, "a"), (1, "b"), (2, "a"), (2, "b"), (3, "a")]
    _seed(engine, table, [{"shelf": shelf, "slot": slot} for shelf, slot in keys])
    _rotate(monkeypatch)

    committed = _commits(engine)
    report = survey(engine, write=True, metadata=mapping, batch=2)
    assert _counts(report) == {"resealed": 5} and report.clean
    assert len(committed) == 3
    assert _states(engine, table) == [SealState.CURRENT] * 5


def test_a_batch_that_cannot_be_written_rolls_back_alone(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    import terp.cli.reseal as reseal

    mapping = MetaData()
    table = _single(mapping)
    mapping.create_all(engine)
    _seed(engine, table, [{"id": key} for key in range(1, 7)])
    _rotate(monkeypatch)
    real_swap, swaps = reseal._swap, []

    def lost_on_the_sixth(*args: Any) -> bool:
        # Rows 5 and 6 are the third batch: the fifth swap succeeds, the sixth fails.
        swaps.append(None)
        if len(swaps) == 6:
            raise OperationalError("UPDATE cli_reseal_batched", {}, Exception("the connection was lost"))
        return real_swap(*args)

    monkeypatch.setattr(reseal, "_swap", lost_on_the_sixth)
    report = survey(engine, write=True, metadata=mapping, batch=2)
    assert report.failed == {_TABLE: "OperationalError: the connection was lost"} and not report.clean
    assert _counts(report) == {"resealed": 4}, "what the first two batches re-sealed is counted"
    assert _states(engine, table) == [SealState.CURRENT] * 4 + [SealState.FALLBACK] * 2
    assert (
        "Could not re-seal cli_reseal_batched (OperationalError: the connection was lost); the "
        "transaction that failed was rolled back, and nothing after it was read." in render(report)
    )


def test_a_row_deleted_between_the_read_and_the_write_is_counted_changed(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    import terp.core

    mapping = MetaData()
    table = _single(mapping)
    mapping.create_all(engine)
    _seed(engine, table, [{"id": key} for key in range(1, 4)])
    with engine.connect() as conn:
        doomed = conn.execute(select(table.c.token).where(table.c.id == 2)).scalar_one()
    _rotate(monkeypatch)
    real_check = terp.core.check_sealed_value

    def deleting_check(stored: str) -> Any:
        # The app deletes the row after the re-seal read it and before it writes.
        if stored == doomed:
            with engine.begin() as other:
                other.execute(delete(table).where(table.c.id == 2))
        return real_check(stored)

    monkeypatch.setattr(terp.core, "check_sealed_value", deleting_check)
    report = survey(engine, write=True, metadata=mapping)
    assert _counts(report) == {"resealed": 2, "changed": 1} and not report.clean
    assert _states(engine, table) == [SealState.CURRENT] * 2


def test_a_table_the_app_maps_and_the_database_does_not_hold_is_passed_over(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mapped table that was never created (a capability installed and not wired) has no
    value to judge: it is neither counted nor a failure."""
    mapping = MetaData()
    table = _single(mapping)
    Table("cli_reseal_never_created", mapping, Column("id", Integer, primary_key=True), Column("token", String(512)))
    table.create(engine)
    _seed(engine, table, [{"id": 1}])
    _rotate(monkeypatch)

    report = survey(engine, write=True, metadata=mapping)
    assert not report.failed and report.clean
    assert [tally.table for tally in report.columns] == [_TABLE]
    assert _counts(report) == {"resealed": 1}


def test_a_row_another_transaction_holds_is_passed_over_and_counted_held(
    terp_pg_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker that claimed a row holds it until its own transaction ends. The run does not
    wait: the lock timeout turns a wait into a failure here, rather than a test that hangs."""
    engine = create_engine(terp_pg_url, connect_args={"options": "-c lock_timeout=5000"})
    mapping = MetaData()
    table = _single(mapping)
    mapping.create_all(engine)
    _seed(engine, table, [{"id": key} for key in range(1, 4)])
    _rotate(monkeypatch)

    with engine.connect() as worker, worker.begin():
        worker.execute(select(table.c.id).where(table.c.id == 2).with_for_update())
        held = survey(engine, write=True, metadata=mapping, batch=2)
    assert not held.failed, held.failed
    assert _counts(held) == {"resealed": 2, "held": 1} and not held.clean
    assert "1 value(s) under a fallback were in rows another transaction held" in render(held)
    assert _states(engine, table) == [SealState.CURRENT, SealState.FALLBACK, SealState.CURRENT]

    # Control: once the worker's transaction ends, the next run re-seals the row it held.
    settled = survey(engine, write=True, metadata=mapping, batch=2)
    assert _counts(settled) == {"current": 2, "resealed": 1} and settled.clean
    engine.dispose()
