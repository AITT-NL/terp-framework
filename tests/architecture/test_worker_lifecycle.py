"""A worker finishes or gives back its work when it stops, and a killed one's job comes back.

ADR 0191's exit test for workers: no job lost, and an interrupted job redelivered. Held on
the outbox worker ``terp jobs worker --forever`` runs:

* **a stop** claims nothing more, finishes the job in flight, and releases the rest of the
  batch: their lease is cleared, so another worker takes them at once rather than after
  ``lease_seconds``, with their attempt count untouched;
* **a kill** gives the worker no say at all. The job it held is redelivered once its lease
  lapses, to another worker process, and runs again: proven with two real processes over one
  database, the first killed mid-job;
* **the durable schedule ledger** moves a schedule's record by compare-and-set inside the
  write unit of the tick's own outbox row.

The heartbeat the forever loop writes is held in ``test_worker_heartbeat.py``.
"""

from __future__ import annotations

import os
import pathlib
import signal
import subprocess
import sys
import textwrap
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from sqlmodel import Field, Session, SQLModel, create_engine, select

from terp.core import BaseSchema, JobCatalog, JobDefinition, JobEnvelope, ScheduleRecord
from terp.core.jobs import configure_jobs
from terp.core._internal.session_guard import WriteGuardedSession

from terp.capabilities.outbox import (
    KIND_JOB,
    STATUS_DISPATCHED,
    STATUS_PENDING,
    DatabaseScheduleLedger,
    DrainResult,
    OutboxJobQueue,
    OutboxMessage,
    OutboxWorker,
    ScheduleFire,
)
from terp.capabilities.outbox._serde import job_envelope_to_payload
from terp.capabilities.outbox.store import claim_due, release

_T0 = datetime(2026, 10, 22, 9, tzinfo=UTC)
_REPO = pathlib.Path(__file__).resolve().parents[2]


class _Payload(BaseSchema):
    label: str = Field(max_length=50)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def engine(tmp_path: pathlib.Path) -> Iterator[object]:
    eng = create_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _row(engine: object, name: str, label: str) -> uuid.UUID:
    message = OutboxMessage(
        kind=KIND_JOB,
        name=name,
        payload=job_envelope_to_payload(JobEnvelope(name=name, payload={"label": label})),
        available_at=_T0,
    )
    with Session(engine) as session:  # type: ignore[arg-type]
        session.add(message)
        session.commit()
        return message.id


def _rows(engine: object) -> dict[str, OutboxMessage]:
    with Session(engine) as session:  # type: ignore[arg-type]
        return {row.payload["payload"]["label"]: row for row in session.exec(select(OutboxMessage))}


def _worker(engine: object, clock: _Clock, **options: object) -> OutboxWorker:
    return OutboxWorker(
        lambda: Session(engine),  # type: ignore[arg-type]
        job_session_factory=lambda: WriteGuardedSession(engine),  # type: ignore[arg-type]
        clock=clock,
        **options,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# a stop                                                                        #
# --------------------------------------------------------------------------- #
def test_a_stop_finishes_the_job_in_flight_and_gives_the_rest_of_the_batch_back(
    engine: object,
) -> None:
    stop = Event()
    ran: list[str] = []

    def handler(ctx, payload):  # type: ignore[no-untyped-def]
        ran.append(payload.label)
        stop.set()  # the stop signal arrives while the first job runs

    job = JobDefinition(name="docs.slow", payload_schema=_Payload, handler=handler)
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    for label in ("first", "second", "third"):
        _row(engine, "docs.slow", label)
    beats: list[int] = []
    clock = _Clock(_T0)

    result = _worker(engine, clock).run(stop=stop, beat=lambda: beats.append(1))
    assert result == DrainResult(claimed=3, dispatched=1, released=2)
    [finished] = ran  # the job in flight finished; nothing more started
    assert len(beats) == 2, "a beat before the claim and one after the job that ran"
    rows = _rows(engine)
    assert rows.pop(finished).status == STATUS_DISPATCHED
    for row in rows.values():
        assert (row.status, row.attempts) == (STATUS_PENDING, 0), "given back, not attempted"
        assert row.locked_by is None and row.locked_until is None

    # Another worker takes them at once, at the same moment: no lease to wait out.
    assert _worker(engine, clock).run(stop=Event()) == DrainResult(claimed=2, dispatched=2)
    assert sorted(ran) == ["first", "second", "third"]


def test_a_worker_asked_to_stop_claims_nothing(engine: object) -> None:
    job = JobDefinition(name="docs.slow", payload_schema=_Payload, handler=lambda c, p: None)
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    _row(engine, "docs.slow", "waiting")
    stop = Event()
    stop.set()
    assert _worker(engine, _Clock(_T0)).run(stop=stop) == DrainResult()
    assert _rows(engine)["waiting"].locked_by is None


def test_release_touches_only_what_the_claim_still_holds(engine: object) -> None:
    mine = _row(engine, "docs.slow", "mine")
    taken = _row(engine, "docs.slow", "taken")
    with Session(engine) as session:  # type: ignore[arg-type]
        claim_due(session, claim_id="c1", now=_T0, lease_until=_T0 + timedelta(seconds=1), limit=10)
    # The lease lapsed and another worker reclaimed one of the rows meanwhile.
    later = _T0 + timedelta(seconds=5)
    with Session(engine) as session:  # type: ignore[arg-type]
        row = session.get(OutboxMessage, taken)
        row.locked_by, row.locked_until = "c2", later + timedelta(seconds=30)
        session.add(row)
        session.commit()
    with Session(engine) as session:  # type: ignore[arg-type]
        assert release(session, claim_id="c1", ids=[mine, taken]) == 1
    rows = _rows(engine)
    assert rows["mine"].locked_by is None
    assert rows["taken"].locked_by == "c2", "its new owner keeps it"


# --------------------------------------------------------------------------- #
# a kill                                                                        #
# --------------------------------------------------------------------------- #
_KILLABLE_APP = textwrap.dedent(
    """
    import os
    import pathlib
    import time

    from sqlmodel import Field, SQLModel

    from terp.core import BaseSchema, ControlPlane, JobCatalog, JobDefinition, create_app
    from terp.core._internal.engine import get_engine

    from terp.capabilities.outbox import OutboxJobQueue

    MARKS = pathlib.Path(os.environ["KILL_TEST_MARKS"])


    class Payload(BaseSchema):
        label: str = Field(max_length=50)


    def _handler(ctx, payload):
        with (MARKS / "runs").open("a", encoding="utf-8") as runs:
            runs.write(f"{os.getpid()}\\n")
        if os.environ.get("KILL_TEST_HANG") == "1":
            (MARKS / "started").write_text("1", encoding="utf-8")
            time.sleep(600)  # longer than any stop grace: the worker is killed here
        (MARKS / "done").write_text(payload.label, encoding="utf-8")


    JOB = JobDefinition(name="docs.slow", payload_schema=Payload, handler=_handler)


    def build():
        app = create_app(
            [], control_plane=ControlPlane(jobs=JobCatalog([JOB])), job_queue=OutboxJobQueue()
        )
        SQLModel.metadata.create_all(get_engine())
        return app
    """
)


def _worker_process(
    tmp_path: pathlib.Path, database: str, *args: str, hang: bool
) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "DATABASE_URL": database,
        "KILL_TEST_MARKS": str(tmp_path),
        "KILL_TEST_HANG": "1" if hang else "0",
        "TMPDIR": str(tmp_path),
        "TEMP": str(tmp_path),
        "TMP": str(tmp_path),
    }
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from terp.cli import main; main()",
            "jobs",
            "worker",
            "--app",
            "killable_app:build",
            "--app-root",
            str(tmp_path),
            "--lease-seconds",
            "2",
            *args,
        ],
        env=env,
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _wait_for(path: pathlib.Path, process: subprocess.Popen[bytes], *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if process.poll() is not None:
            output = process.stdout.read().decode() if process.stdout else ""
            raise AssertionError(f"the worker exited before {path.name}: {output}")
        assert time.monotonic() < deadline, f"no {path.name} within {timeout}s"
        time.sleep(0.1)


def test_a_killed_worker_s_job_is_redelivered_to_the_next_worker(tmp_path: pathlib.Path) -> None:
    """Two real processes over one database. The first takes the job and is killed in it (no
    handler runs, nothing is released or finalized); the second, started after the lease
    lapsed, takes the same row and runs it to the end."""
    (tmp_path / "killable_app.py").write_text(_KILLABLE_APP, encoding="utf-8")
    database = f"sqlite:///{(tmp_path / 'kill.db').as_posix()}"
    engine = create_engine(database)
    SQLModel.metadata.create_all(engine)
    job = JobDefinition(name="docs.slow", payload_schema=_Payload, handler=lambda c, p: None)
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    with WriteGuardedSession(engine) as session:
        from terp.core import enqueue

        enqueue(session, job=job, payload=_Payload(label="the-job"))

    first = _worker_process(tmp_path, database, "--forever", "--poll-seconds", "0.2", hang=True)
    try:
        _wait_for(tmp_path / "started", first, timeout=120)
        first.kill()  # SIGKILL / TerminateProcess: the worker gets no say
        first.wait(timeout=30)
    finally:
        if first.poll() is None:
            first.kill()
    with Session(engine) as session:
        held = session.exec(select(OutboxMessage)).one()
    assert (held.status, held.attempts) == (STATUS_PENDING, 0)
    assert held.locked_by is not None, "the dead worker's lease is still on the row"

    time.sleep(2.5)  # the lease (2s) lapses
    second = _worker_process(tmp_path, database, "--max-cycles", "5", hang=False)
    output, _ = second.communicate(timeout=180)
    assert second.returncode == 0, output.decode()
    assert "dispatched=1" in output.decode()
    runs = (tmp_path / "runs").read_text(encoding="utf-8").split()
    assert len(runs) == 2 and runs[0] != runs[1], "run once in each worker process"
    assert (tmp_path / "done").read_text(encoding="utf-8") == "the-job"
    with Session(engine) as session:
        assert session.exec(select(OutboxMessage)).one().status == STATUS_DISPATCHED
    engine.dispose()


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM to another process is POSIX")
def test_sigterm_finishes_the_job_in_flight_and_releases_the_batch(tmp_path: pathlib.Path) -> None:
    """The real signal, through the handler the worker installs: the container's stop."""
    app = _KILLABLE_APP.replace("time.sleep(600)", "time.sleep(1.5)")
    (tmp_path / "killable_app.py").write_text(app, encoding="utf-8")
    database = f"sqlite:///{(tmp_path / 'term.db').as_posix()}"
    engine = create_engine(database)
    SQLModel.metadata.create_all(engine)
    job = JobDefinition(name="docs.slow", payload_schema=_Payload, handler=lambda c, p: None)
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    with WriteGuardedSession(engine) as session:
        from terp.core import enqueue

        for label in ("first", "second"):
            enqueue(session, job=job, payload=_Payload(label=label))
    worker = _worker_process(tmp_path, database, "--forever", hang=True)
    _wait_for(tmp_path / "started", worker, timeout=120)
    worker.send_signal(signal.SIGTERM)
    output, _ = worker.communicate(timeout=60)
    assert worker.returncode == 0, output.decode()
    assert "dispatched=1" in output.decode() and "released=1" in output.decode()
    with Session(engine) as session:
        statuses = sorted(row.status for row in session.exec(select(OutboxMessage)))
        assert statuses == [STATUS_DISPATCHED, STATUS_PENDING]
        assert all(row.locked_by is None for row in session.exec(select(OutboxMessage)))
    engine.dispose()


# --------------------------------------------------------------------------- #
# the durable schedule ledger                                                   #
# --------------------------------------------------------------------------- #
def test_the_database_ledger_records_a_slot_with_its_outbox_row_in_one_unit(
    engine: object,
) -> None:
    job = JobDefinition(name="docs.slow", payload_schema=_Payload, handler=lambda c, p: None)
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    ledger = DatabaseScheduleLedger()

    def settle(expected, slot, outcome, *, runs: bool = True):  # type: ignore[no-untyped-def]
        with WriteGuardedSession(engine) as session:  # type: ignore[arg-type]
            from terp.core import enqueue

            return ledger.settle(
                session,
                "reports.hourly",
                expected=expected,
                slot=slot,
                outcome=outcome,
                enqueue=(lambda: enqueue(session, job=job, payload=_Payload(label=outcome)))
                if runs
                else None,
            )

    def last() -> ScheduleRecord | None:
        with Session(engine) as session:  # type: ignore[arg-type]
            return ledger.last(session, "reports.hourly")

    assert last() is None
    moved, job_id = settle(None, _T0, "fired")
    assert moved and job_id is not None
    first = last()
    assert first == ScheduleRecord(slot=_T0, outcome="fired", fires=1)
    assert first.slot.tzinfo is not None, "read back aware, though SQLite stores it naive"

    later = _T0 + timedelta(hours=1)
    assert settle(first, later, "skipped", runs=False) == (True, None)
    # A second scheduler that read the same record loses, and its outbox row goes with it.
    lost, orphan = settle(first, later, "late")
    assert not lost and orphan is not None
    assert settle(None, later, "fired")[0] is False, "a record that exists is not made twice"
    with Session(engine) as session:  # type: ignore[arg-type]
        assert [row.payload["payload"]["label"] for row in session.exec(select(OutboxMessage))] == [
            "fired"
        ], "a lost compare-and-set rolled its own outbox row back"
        [row] = session.exec(select(ScheduleFire)).all()
    assert (row.slot.replace(tzinfo=UTC), row.outcome, row.fires) == (later, "skipped", 2)
