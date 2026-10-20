"""The ``notices`` manifest: who may reach the module, and which jobs it causes."""

from __future__ import annotations

from terp.capabilities.mail import MAIL_SEND

from app.modules.notices.jobs import SNAPSHOT_TAKE
from app.modules.notices.module import module
from app.modules.notices.service import NoticeService, SnapshotService
from control_plane import control_plane


def test_the_manifest_declares_the_module_and_its_data_layer() -> None:
    assert module.name == "notices"
    assert {NoticeService, SnapshotService} <= set(module.services)


def test_writing_requires_more_authority_than_reading() -> None:
    # If a later edit ever levels these two, everyone who can see a notice can post one,
    # and nothing else in the gate would say so.
    policy = module.policy
    assert policy.authenticated
    assert policy.write_requirement.min_rank > policy.read_requirement.min_rank


def test_every_job_the_module_causes_is_in_the_catalog() -> None:
    # Boot checks this too; asserting it names the two jobs the reference app exists to
    # carry, so dropping either from the catalog is a red here and not only a boot error.
    assert set(module.jobs) == {MAIL_SEND, SNAPSHOT_TAKE}
    assert all(control_plane.jobs.has_job(job) for job in module.jobs)


def test_the_snapshot_runs_on_a_declared_schedule() -> None:
    schedule = control_plane.schedules.get("notices.snapshot.hourly")
    assert schedule is not None
    assert schedule.job is SNAPSHOT_TAKE
    assert schedule.cron == "0 * * * *"
