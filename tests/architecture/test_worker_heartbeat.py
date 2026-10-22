"""Worker and scheduler health is a heartbeat their own loop writes (ADR 0191).

A worker and a scheduler serve no request, so ADR 0187 rendered them with no check: ready
once running was all that was true. They now write a heartbeat from the loop whose progress
it vouches for, and the generated profile checks it with a fixed probe that reads a file:

* **the writer** (``terp.cli.heartbeat``) writes the file atomically, says how stale it may
  grow, survives a write it cannot make, and is removed when the process starts and stops;
* **the probe** the generator renders (``terp.arch.deployment``) passes on a fresh heartbeat,
  fails on a stale one, a missing one and a broken one, and prints the age a deploy tool
  reads back: run here as the container runs it, ``python -c`` in a process of its own;
* **a loop that hangs stops beating**: a worker stuck in one job writes nothing more, while
  an idle one beats every poll, and the probe then fails it;
* **the two processes write it**: ``terp jobs worker --forever`` and ``terp jobs scheduler``,
  and each stops on SIGTERM or SIGINT, the scheduler once however many signals arrive.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator

import pytest

from terp.arch.deployment.generator import HEARTBEAT_PROBE

from terp.cli.heartbeat import (
    HEARTBEAT_GRACE_SECONDS,
    SCHEDULER_BEAT_SECONDS,
    SCHEDULER_STALE_AFTER,
    Heartbeat,
    heartbeat_path,
    worker_stale_after,
)
from terp.cli.jobs import run_scheduler_command, run_worker_command


def _probe(directory: pathlib.Path, role: str) -> subprocess.CompletedProcess[str]:
    """The generated healthcheck, run as Docker runs it: its own process, the role its argument."""
    env = {**os.environ, "TMPDIR": str(directory), "TEMP": str(directory), "TMP": str(directory)}
    return subprocess.run(
        [sys.executable, "-c", HEARTBEAT_PROBE, role],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _beat_file(directory: pathlib.Path, role: str, *, age: float, stale_after: float) -> None:
    record = {"role": role, "pid": 1, "at": time.time() - age, "stale_after": stale_after}
    (directory / f"terp-{role}.heartbeat").write_text(json.dumps(record), encoding="utf-8")


# --------------------------------------------------------------------------- #
# the writer                                                                    #
# --------------------------------------------------------------------------- #
def test_a_beat_records_when_and_how_stale_it_may_grow(tmp_path: pathlib.Path) -> None:
    moments = iter([100.0, 107.5])
    beat = Heartbeat("worker", stale_after=60.0, path=tmp_path / "hb", clock=lambda: next(moments))
    beat.beat()
    first = json.loads((tmp_path / "hb").read_text(encoding="utf-8"))
    assert first == {"role": "worker", "pid": os.getpid(), "at": 100.0, "stale_after": 60.0, "beats": 1}
    beat.beat()
    assert json.loads((tmp_path / "hb").read_text(encoding="utf-8"))["at"] == 107.5
    assert [path.name for path in tmp_path.iterdir()] == ["hb"], "no partial file left behind"
    beat.clear()
    assert not (tmp_path / "hb").exists()
    beat.clear()  # nothing to remove is not an error


def test_a_beat_that_cannot_be_written_is_logged_once_and_the_work_goes_on(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    beat = Heartbeat("worker", stale_after=60.0, path=tmp_path / "missing" / "hb")
    with caplog.at_level(logging.WARNING, logger="terp.cli.heartbeat"):
        beat.beat()
        beat.beat()
        assert caplog.text.count("could not be written") == 1
        (tmp_path / "missing").mkdir()
        beat.beat()
    assert "is written to" in caplog.text and "again" in caplog.text
    assert (tmp_path / "missing" / "hb").exists()


def test_the_bounds_follow_each_process_s_own_pace() -> None:
    assert HEARTBEAT_GRACE_SECONDS == 30.0
    assert worker_stale_after(lease_seconds=30.0, poll_seconds=5.0) == 60.0
    assert worker_stale_after(lease_seconds=300.0, poll_seconds=5.0) == 330.0, "a longer lease"
    assert worker_stale_after(lease_seconds=10.0, poll_seconds=60.0) == 90.0, "a slower poll"
    assert SCHEDULER_BEAT_SECONDS == 10.0 and SCHEDULER_STALE_AFTER == 60.0


def test_the_file_is_per_role_in_the_process_s_temporary_directory(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    assert heartbeat_path("worker") == tmp_path / "terp-worker.heartbeat"
    assert heartbeat_path("scheduler") == tmp_path / "terp-scheduler.heartbeat"


# --------------------------------------------------------------------------- #
# the probe the generator renders                                               #
# --------------------------------------------------------------------------- #
def test_the_probe_passes_on_a_fresh_heartbeat_and_says_how_old_it_is(tmp_path: pathlib.Path) -> None:
    Heartbeat("worker", stale_after=60.0, path=tmp_path / "terp-worker.heartbeat").beat()
    passed = _probe(tmp_path, "worker")
    assert passed.returncode == 0, passed.stderr
    reading = json.loads(passed.stdout)
    assert reading["heartbeat"] == "worker" and reading["stale_after_seconds"] == 60.0
    assert 0 <= reading["age_seconds"] < 30


@pytest.mark.parametrize(
    ("age", "stale_after", "healthy"),
    [(10.0, 60.0, True), (59.0, 60.0, True), (61.0, 60.0, False), (400.0, 330.0, False)],
)
def test_the_probe_fails_a_heartbeat_older_than_its_own_bound(
    tmp_path: pathlib.Path, age: float, stale_after: float, healthy: bool
) -> None:
    _beat_file(tmp_path, "scheduler", age=age, stale_after=stale_after)
    result = _probe(tmp_path, "scheduler")
    assert (result.returncode == 0) is healthy, result.stdout + result.stderr
    assert json.loads(result.stdout)["age_seconds"] >= age - 1


def test_the_probe_fails_with_no_heartbeat_or_a_broken_one(tmp_path: pathlib.Path) -> None:
    missing = _probe(tmp_path, "worker")
    assert missing.returncode == 1 and "terp-worker.heartbeat" in missing.stderr
    (tmp_path / "terp-worker.heartbeat").write_text("{not json", encoding="utf-8")
    assert _probe(tmp_path, "worker").returncode == 1
    _beat_file(tmp_path, "scheduler", age=1.0, stale_after=60.0)
    assert _probe(tmp_path, "worker").returncode == 1, "a scheduler's heartbeat is not a worker's"


# --------------------------------------------------------------------------- #
# a loop that hangs stops beating                                               #
# --------------------------------------------------------------------------- #
_HANGING_APP = """\
import threading

from sqlmodel import Field, SQLModel

from terp.core import BaseSchema, ControlPlane, JobCatalog, JobContext, JobDefinition, create_app, enqueue
from terp.core._internal.engine import get_engine
from terp.core._internal.session_guard import WriteGuardedSession
from terp.capabilities.outbox import OutboxJobQueue

entered = threading.Event()
release = threading.Event()


class Payload(BaseSchema):
    label: str = Field(max_length=50)


def _handler(ctx: JobContext, payload: Payload) -> None:
    entered.set()
    release.wait(30)


JOB = JobDefinition(name="docs.stuck", payload_schema=Payload, handler=_handler)


def build():
    app = create_app([], control_plane=ControlPlane(jobs=JobCatalog([JOB])), job_queue=OutboxJobQueue())
    SQLModel.metadata.create_all(get_engine())
    return app


def stage():
    with WriteGuardedSession(get_engine()) as session:
        enqueue(session, job=JOB, payload=Payload(label="stuck"))
"""


@pytest.fixture
def worker_db(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from terp.core._internal.engine import reset_engine
    from terp.core.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{tmp_path / 'heartbeat.db'}")
    reset_engine()
    yield
    reset_engine()


def _at(path: pathlib.Path) -> float:
    return json.loads(path.read_text(encoding="utf-8"))["at"]


def test_an_idle_worker_beats_every_poll_and_a_stuck_one_stops(
    tmp_path: pathlib.Path, worker_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "hanging_app.py").write_text(_HANGING_APP, encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    sys.modules.pop("hanging_app", None)
    module = importlib.import_module("hanging_app")
    beat_file = tmp_path / "terp-worker.heartbeat"
    stop = threading.Event()
    outcome: list[str] = []
    loop = threading.Thread(
        target=lambda: outcome.append(
            run_worker_command(
                app_ref="hanging_app:build",
                app_root=tmp_path,
                forever=True,
                poll_seconds=0.1,
                stop=stop,
                heartbeat_path=beat_file,
            )
        ),
        daemon=True,
    )
    # The loop runs on a thread so this test can watch it, and only the main thread may
    # install a signal handler: the stop comes through *stop* instead.
    monkeypatch.setattr(signal, "signal", lambda number, handler: signal.getsignal(number))
    try:
        loop.start()
        deadline = time.monotonic() + 60
        while not beat_file.exists():
            assert time.monotonic() < deadline, "the worker never beat"
            time.sleep(0.05)
        idle = _at(beat_file)
        time.sleep(0.6)
        assert _at(beat_file) > idle, "an idle worker beats every poll"
        assert json.loads(beat_file.read_text(encoding="utf-8"))["stale_after"] == 60.0

        module.stage()  # one job, which never returns
        assert module.entered.wait(30)
        time.sleep(0.3)
        stuck = _at(beat_file)
        time.sleep(1.2)
        assert _at(beat_file) == stuck, "a worker stuck in a job writes no heartbeat"
        # ...so once the bound has passed, the probe fails it.
        record = json.loads(beat_file.read_text(encoding="utf-8"))
        record["at"] = stuck - record["stale_after"] - 1  # the bound, without the wait
        beat_file.write_text(json.dumps(record), encoding="utf-8")
        assert _probe(tmp_path, "worker").returncode == 1
    finally:
        stop.set()
        module.release.set()
        loop.join(30)
        sys.path.remove(str(tmp_path))
    assert outcome and outcome[0].startswith("outbox worker stopped after")
    assert not beat_file.exists(), "a stopped worker leaves no heartbeat behind"


# --------------------------------------------------------------------------- #
# the two processes write it                                                    #
# --------------------------------------------------------------------------- #
_WORKER_APP = """\
from sqlmodel import Field, SQLModel

from terp.core import BaseSchema, ControlPlane, JobCatalog, JobContext, JobDefinition, create_app, enqueue
from terp.core._internal.engine import get_engine
from terp.core._internal.session_guard import WriteGuardedSession
from terp.capabilities.outbox import OutboxJobQueue
import signal

ran: list[str] = []


class Payload(BaseSchema):
    label: str = Field(max_length=50)


def _handler(ctx: JobContext, payload: Payload) -> None:
    ran.append(payload.label)
    # The container's stop arrives while the first job runs, through the handler installed.
    signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)


JOB = JobDefinition(name="docs.create", payload_schema=Payload, handler=_handler)


def build():
    app = create_app([], control_plane=ControlPlane(jobs=JobCatalog([JOB])), job_queue=OutboxJobQueue())
    SQLModel.metadata.create_all(get_engine())
    with WriteGuardedSession(get_engine()) as session:
        for label in ("one", "two", "three"):
            enqueue(session, job=JOB, payload=Payload(label=label))
    return app
"""


def test_sigterm_mid_batch_finishes_one_job_and_gives_back_the_rest(
    tmp_path: pathlib.Path, worker_db: None
) -> None:
    (tmp_path / "stopping_app.py").write_text(_WORKER_APP, encoding="utf-8")
    sys.modules.pop("stopping_app", None)
    before = (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT))
    beat_file = tmp_path / "terp-worker.heartbeat"
    message = run_worker_command(
        app_ref="stopping_app:build",
        app_root=tmp_path,
        forever=True,
        poll_seconds=0.1,
        heartbeat_path=beat_file,
    )
    assert message.startswith("outbox worker stopped after 1 pass(es): claimed=3 dispatched=1 ")
    assert message.endswith("released=2")
    assert len(importlib.import_module("stopping_app").ran) == 1
    assert (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)) == before
    assert not beat_file.exists()


class _BlockingScheduler:
    """A scheduler whose start blocks until it is shut down, as APScheduler's does."""

    def __init__(self, signals: int) -> None:
        self.signals = signals
        self.shutdowns: list[bool] = []
        self.beats: list[tuple[float, object]] = []
        self.registered: object = None
        self.beat_file: pathlib.Path | None = None
        self.seen_beat: dict | None = None

    def register_all(self, catalog: object) -> None:
        self.registered = catalog

    def every(self, seconds: float, callback) -> None:  # type: ignore[no-untyped-def]
        self.beats.append((seconds, callback))

    def start(self) -> None:
        _seconds, callback = self.beats[0]
        callback()  # the engine runs the heartbeat job once at start
        assert self.beat_file is not None
        self.seen_beat = json.loads(self.beat_file.read_text(encoding="utf-8"))
        for _ in range(self.signals):  # the stop, perhaps more than once
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

    def shutdown(self, *, wait: bool = True) -> None:
        self.shutdowns.append(wait)


_SCHEDULER_APP = """\
from sqlmodel import Field

from terp.core import BaseSchema, ControlPlane, JobCatalog, JobContext, JobDefinition, Misfire
from terp.core import ScheduleCatalog, ScheduleDefinition, create_app


class Payload(BaseSchema):
    label: str | None = Field(default=None, max_length=50)


JOB = JobDefinition(name="sync.pull", payload_schema=Payload, handler=lambda ctx, payload: None)
SCHEDULE = ScheduleDefinition(name="sync.nightly", job=JOB, cron="0 2 * * *", misfire=Misfire.SKIP)


def build():
    return create_app(
        [], control_plane=ControlPlane(jobs=JobCatalog([JOB]), schedules=ScheduleCatalog([SCHEDULE]))
    )
"""


def test_the_scheduler_beats_from_its_engine_and_stops_once(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "beating_scheduler.py").write_text(_SCHEDULER_APP, encoding="utf-8")
    sys.modules.pop("beating_scheduler", None)
    fake = _BlockingScheduler(signals=2)
    fake.beat_file = tmp_path / "terp-scheduler.heartbeat"
    with caplog.at_level(logging.WARNING, logger="terp.cli.jobs"):
        message = run_scheduler_command(
            app_ref="beating_scheduler:build",
            app_root=tmp_path,
            scheduler=fake,
            heartbeat_path=fake.beat_file,
        )
    assert "1 schedule(s) registered: sync.nightly" in message
    assert [seconds for seconds, _callback in fake.beats] == [SCHEDULER_BEAT_SECONDS]
    assert fake.seen_beat is not None and fake.seen_beat["role"] == "scheduler"
    assert fake.seen_beat["stale_after"] == SCHEDULER_STALE_AFTER
    assert fake.shutdowns == [True], "shut down once, letting the ticks in flight finish"
    assert not fake.beat_file.exists()
    assert "the schedule ledger is per process" in caplog.text
