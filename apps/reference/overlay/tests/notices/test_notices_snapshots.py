"""The schedule enqueues the snapshot, the worker fetches the upstream and stores what came back."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session, select

from terp.core import Misfire, Roles, is_durable_schedule_ledger, trigger_schedule
from terp.core.scheduling import active_schedule_catalog, active_schedule_ledger

from terp.capabilities.egress import EgressClient, EgressFailedError, EgressRefusedError
from terp.capabilities.files import FileService
from terp.capabilities.scheduler_apscheduler import ApschedulerScheduler

from app.modules.notices import upstream
from app.modules.notices.models import Snapshot

_SCHEDULE = "notices.snapshot.hourly"


def _fire_the_schedule(engine) -> None:
    """One tick, exactly as `terp jobs scheduler` fires it: enqueue the schedule's job."""
    schedule = active_schedule_catalog().get(_SCHEDULE)
    assert schedule is not None, "the composed app did not install the schedule catalog"
    with Session(engine) as session:
        trigger_schedule(session, schedule)


def test_a_tick_is_fetched_by_the_worker_and_kept_in_file_storage(
    application, fake_upstream, storage, drain, db_engine, client_as
) -> None:
    _fire_the_schedule(db_engine)
    assert fake_upstream.targets == []  # enqueuing calls nothing; the worker does

    result = drain()
    assert result.dispatched == 1

    # One egress call, to the declared host, pinned to the address that passed the check.
    [target] = fake_upstream.targets
    assert (target.url, target.host) == (upstream.UPSTREAM_URL, "example.com")
    with Session(db_engine) as session:
        [snapshot] = session.exec(select(Snapshot)).all()
        assert (snapshot.status_code, snapshot.size) == (200, len(fake_upstream.content))
        # The bytes are in the storage backend, reached through the declared reference.
        stored, content = FileService().load_for(session, snapshot, "file_id")
    assert content == fake_upstream.content
    assert stored.content_type == "text/html"
    assert any(storage.rglob("*")), "nothing reached the storage backend"

    listed = client_as(Roles.VIEWER).get("/api/v1/notices/snapshots/").json()
    assert [item["id"] for item in listed["items"]] == [str(snapshot.id)]


@pytest.mark.parametrize(
    ("headers", "expected"),
    [({"Content-Type": "TEXT/HTML; charset=UTF-8"}, "text/html"), ({}, "application/octet-stream")],
    ids=["the-upstreams-own", "none-named"],
)
def test_a_snapshot_is_stored_as_the_media_type_the_upstream_named(
    application, fake_upstream, storage, drain, db_engine, headers, expected
) -> None:
    fake_upstream.headers = headers
    _fire_the_schedule(db_engine)
    assert drain().dispatched == 1
    with Session(db_engine) as session:
        [snapshot] = session.exec(select(Snapshot)).all()
        stored, _content = FileService().load_for(session, snapshot, "file_id")
    assert stored.content_type == expected


def test_an_editor_asks_for_one_now_and_the_worker_takes_it(
    client_as, fake_upstream, storage, drain
) -> None:
    editor = client_as(Roles.EDITOR)
    accepted = editor.post("/api/v1/notices/snapshots/")
    assert accepted.status_code == 202, accepted.text
    assert editor.get("/api/v1/notices/snapshots/").json()["total"] == 0  # accepted, not done

    assert drain().dispatched == 1
    [snapshot] = editor.get("/api/v1/notices/snapshots/").json()["items"]
    assert (snapshot["status_code"], snapshot["url"]) == (200, upstream.UPSTREAM_URL)
    assert len(fake_upstream.targets) == 1


def test_a_viewer_cannot_ask_for_a_snapshot(client_as) -> None:
    assert client_as(Roles.VIEWER).post("/api/v1/notices/snapshots/").status_code == 403


def test_a_failed_fetch_is_retried_and_records_nothing(
    application, fake_upstream, storage, drain, db_engine
) -> None:
    fake_upstream.error = EgressFailedError("The upstream did not answer.")
    _fire_the_schedule(db_engine)

    result = drain()
    assert (result.dispatched, result.retried) == (0, 1)
    with Session(db_engine) as session:
        assert session.exec(select(Snapshot)).all() == []


@pytest.mark.parametrize(
    "url",
    ["https://example.org/", "https://api.example.com/", "http://example.com/"],
    ids=["another-host", "a-subdomain", "plain-http"],
)
def test_the_policy_permits_one_host_over_https_and_nothing_else(url: str) -> None:
    # Refused on the declaration, before any lookup: a name nobody declared is never
    # resolved, so a refusal cannot be used to probe what resolves.
    looked_up: list[str] = []
    client = EgressClient(upstream.UPSTREAM_POLICY, resolve=looked_up.append)
    with pytest.raises(EgressRefusedError):
        client.get(url)
    assert looked_up == []


def test_the_scheduler_registers_the_declared_cron(application, db_engine) -> None:
    # `terp jobs scheduler` wraps a blocking APScheduler; a background one that is never
    # started shows the same registration without a thread.
    engine = BackgroundScheduler()
    ApschedulerScheduler(lambda: Session(db_engine), scheduler=engine).register_all(
        active_schedule_catalog()
    )
    job = engine.get_job(_SCHEDULE)
    assert job is not None
    fields = {field.name: str(field) for field in job.trigger.fields}
    assert (fields["minute"], fields["hour"]) == ("0", "*")


def test_the_hour_a_deploy_stopped_the_scheduler_across_is_taken_once_late(
    application, fake_upstream, storage, drain, db_engine
) -> None:
    # ADR 0191: the app's ledger is the database's, so the only thing a restarted scheduler
    # carries over is what this test carries over: the database.
    assert active_schedule_catalog().get(_SCHEDULE).misfire is Misfire.RUN_ONCE
    assert is_durable_schedule_ledger(active_schedule_ledger())

    def scheduler(at: datetime) -> ApschedulerScheduler:
        started = ApschedulerScheduler(
            lambda: Session(db_engine),
            scheduler=BackgroundScheduler(),
            timezone=UTC,
            clock=lambda: at,
        )
        started.register_all(active_schedule_catalog())
        return started

    [first] = scheduler(datetime(2026, 10, 22, 9, 0, 20, tzinfo=UTC)).catch_up()
    assert first.outcome == "fired"  # nine o'clock, on time
    # Down across ten and eleven; back at twenty past eleven.
    [late] = scheduler(datetime(2026, 10, 22, 11, 20, tzinfo=UTC)).catch_up()
    assert (late.outcome, late.slot) == ("late", datetime(2026, 10, 22, 11, 0, tzinfo=UTC))
    [again] = scheduler(datetime(2026, 10, 22, 11, 25, tzinfo=UTC)).catch_up()
    assert again.outcome is None, "a second restart owes nothing"
    assert drain().dispatched == 2  # nine o'clock, and one run for the gap
