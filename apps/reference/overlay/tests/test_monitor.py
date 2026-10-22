"""The companion: it reads the outbox backlog, and says so loudly once nothing drains it."""

from __future__ import annotations

import logging
import signal
import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, update

from terp.core import trigger_schedule
from terp.core.scheduling import active_schedule_catalog

from terp.capabilities.outbox import OutboxBacklog, OutboxMessage

import monitor
from monitor import __main__ as entrypoint


def _backlog(age: float | None) -> OutboxBacklog:
    return OutboxBacklog(
        pending=0 if age is None else 1,
        due=0 if age is None else 1,
        dead_lettered=0,
        oldest_due_at=None,
        oldest_due_age_seconds=age,
    )


@pytest.mark.parametrize(
    ("age", "level"),
    [(None, logging.INFO), (30.0, logging.INFO), (monitor.STALE_AFTER_SECONDS + 1, logging.WARNING)],
    ids=["empty", "draining", "stale"],
)
def test_the_verdict_turns_to_a_warning_only_once_due_work_goes_stale(age, level) -> None:
    assert monitor.verdict(_backlog(age)) == level


def _enqueue_one(engine) -> None:
    schedule = active_schedule_catalog().get("notices.snapshot.hourly")
    with Session(engine) as session:
        trigger_schedule(session, schedule)


def test_it_reads_the_backlog_the_worker_would_drain(application, db_engine, caplog) -> None:
    _enqueue_one(db_engine)
    with caplog.at_level(logging.INFO, logger="monitor"):
        measured = monitor.check_once(lambda: Session(db_engine))
    assert (measured.pending, measured.due) == (1, 1)
    assert [record.levelno for record in caplog.records] == [logging.INFO]


def test_work_nobody_drains_is_a_warning_naming_the_worker(application, db_engine, caplog) -> None:
    _enqueue_one(db_engine)
    long_ago = datetime.now(UTC) - timedelta(seconds=monitor.STALE_AFTER_SECONDS * 2)
    with Session(db_engine) as session:
        session.exec(update(OutboxMessage).values(available_at=long_ago))
        session.commit()

    with caplog.at_level(logging.INFO, logger="monitor"):
        monitor.check_once(lambda: Session(db_engine))
    [record] = caplog.records
    assert record.levelno == logging.WARNING
    assert "terp jobs worker" in record.getMessage()


def test_the_loop_survives_a_failed_read_and_stops_when_asked(caplog) -> None:
    stop = threading.Event()
    reads: list[int] = []

    def _broken_session() -> Session:
        reads.append(1)
        if len(reads) == 2:
            stop.set()
        raise ConnectionError("the database is away")

    with caplog.at_level(logging.ERROR, logger="monitor"):
        checks = monitor.run(_broken_session, stop, interval=0)
    assert checks == 2
    assert len(caplog.records) == 2
    assert all("could not be read" in record.getMessage() for record in caplog.records)


def test_the_entrypoint_watches_the_configured_database_until_signalled(
    monkeypatch, tmp_path
) -> None:
    # The settings object is read once per process, so the entrypoint is pointed at a
    # database by replacing what it reads rather than by the environment.
    monkeypatch.setattr(
        entrypoint,
        "get_settings",
        lambda: type("Settings", (), {"DATABASE_URL": f"sqlite:///{tmp_path / 'watch.db'}"})(),
    )
    handlers: dict[int, object] = {}
    monkeypatch.setattr(entrypoint.signal, "signal", lambda signum, handler: handlers.update({signum: handler}))
    seen: list[threading.Event] = []

    def _run(session_factory, stop: threading.Event) -> int:
        with session_factory() as session:
            assert session.bind is not None
        handlers[signal.SIGTERM](signal.SIGTERM, None)  # what `docker compose stop` sends
        seen.append(stop)
        return 1

    monkeypatch.setattr(entrypoint, "run", _run)
    assert entrypoint.main() == 0
    assert set(handlers) == {signal.SIGINT, signal.SIGTERM}
    assert seen[0].is_set()

