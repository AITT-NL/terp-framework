"""The background probe: what the production smoke relies on, held without Docker (ADR 0223).

``prod-smoke`` proves the example's worker and scheduler run work by waiting for two
dispatched probe rows: one the scheduler enqueued when it started, one enqueued by hand. On
Docker a wrong name, a schedule that only baselines on its first start, or a ledger that is
not the database's would each read as a two-minute timeout. Here each is its own failure.
"""

from __future__ import annotations

import contextlib
import logging
import pathlib
from datetime import UTC, datetime

import yaml
from fastapi import FastAPI
from sqlalchemy import Engine
from sqlmodel import Session, select

from terp.core import Misfire, enqueue
from terp.core._internal.session_guard import WriteGuardedSession

from terp.capabilities.outbox import OutboxMessage, OutboxWorker, ScheduleFire
from terp.capabilities.scheduler_apscheduler import ApschedulerScheduler

from app.probe import PROBE_RUN, ProbePayload
from control_plane import control_plane
from control_plane.schedules import PROBE_MINUTELY

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_PROD_SMOKE = _REPO_ROOT / ".github" / "workflows" / "prod-smoke.yml"
_PROD_DOCKERFILE = _REPO_ROOT / "apps" / "example" / "Dockerfile.prod"


def test_the_probe_is_declared_on_the_control_plane_and_runs_as_the_system_actor() -> None:
    assert control_plane.jobs.get(PROBE_RUN.name) is PROBE_RUN
    assert control_plane.schedules.schedules == (PROBE_MINUTELY,)
    assert PROBE_MINUTELY.job is PROBE_RUN
    # Every minute, so the minute that began under a minute ago is on time at any start.
    assert PROBE_MINUTELY.cron == "* * * * *"
    assert PROBE_MINUTELY.misfire is Misfire.RUN_ONCE
    assert control_plane.job_system_actor_id is not None
    assert control_plane.production_problems() == []


def test_a_first_scheduler_start_fires_the_probe_and_the_worker_runs_both_paths(
    app_db: FastAPI, db_engine: Engine, caplog
) -> None:
    del app_db  # composed for its side effects: the catalogs, the outbox queue, the ledger

    def sessions() -> WriteGuardedSession:
        return WriteGuardedSession(db_engine)

    started = datetime(2026, 1, 5, 12, 34, 40, tzinfo=UTC)
    scheduler = ApschedulerScheduler(sessions, clock=lambda: started)
    scheduler.register(PROBE_MINUTELY)
    (settled,) = scheduler.catch_up()
    assert (settled.outcome, settled.slot) == ("fired", started.replace(second=0))
    assert settled.job_id is not None

    with contextlib.closing(sessions()) as session:
        by_hand = enqueue(session, job=PROBE_RUN, payload=ProbePayload())

    worker = OutboxWorker(lambda: Session(db_engine), job_session_factory=sessions)
    with caplog.at_level(logging.INFO, logger="app.probe"):
        result = worker.run(max_cycles=5)
    assert (result.dispatched, result.dead_lettered) == (2, 0)
    assert [record.getMessage() for record in caplog.records if record.name == "app.probe"] == [
        "background probe ran (attempt 1)",
        "background probe ran (attempt 1)",
    ]

    with Session(db_engine) as session:
        rows = session.exec(select(OutboxMessage).where(OutboxMessage.name == PROBE_RUN.name)).all()
        assert {str(row.id) for row in rows} == {settled.job_id, by_hand}
        assert {(row.kind, row.status) for row in rows} == {("job", "dispatched")}
        fire = session.get(ScheduleFire, PROBE_MINUTELY.name)
        assert fire is not None and (fire.outcome, fire.fires) == ("fired", 1)


def test_the_production_smoke_holds_the_probe_by_the_names_the_app_declares() -> None:
    workflow = yaml.safe_load(_PROD_SMOKE.read_text(encoding="utf-8"))
    steps = {step.get("name"): step.get("run", "") for step in workflow["jobs"]["prod-smoke"]["steps"]}
    assert "up -d --wait --build api web worker scheduler" in steps["Build and start the production profile"]
    fired = steps["The scheduler fired the probe schedule and the worker ran the job it enqueued"]
    assert f"FROM outbox_schedule_fire WHERE name = '{PROBE_MINUTELY.name}'" in fired
    assert f"name = '{PROBE_RUN.name}' AND status = 'dispatched'" in fired
    by_hand = steps["A job enqueued by hand runs on the worker"]
    assert f"terp jobs run {PROBE_RUN.name} --app-root /srv" in by_hand
    assert '[ "$status" = dispatched ]' in by_hand
    # The scheduler unit runs `terp jobs scheduler`, which needs the engine in the image.
    dockerfile = _PROD_DOCKERFILE.read_text(encoding="utf-8")
    assert "packages/backend/capabilities/scheduler_apscheduler" in dockerfile
    assert "terp-cap-scheduler-apscheduler" in dockerfile
