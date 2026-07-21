"""``terp jobs`` CLI: the external-scheduler trigger + the generated catalog listing (ADR 0043).

Proves ``terp jobs run`` builds the app, resolves a job by name, validates its JSON payload,
and runs it through the typed ``enqueue`` chokepoint (fail closed on an unknown job or bad
JSON), and that ``terp jobs list`` / ``terp inspect jobs`` render the live control-plane
catalog — generated, so the listing cannot drift from what the app actually runs.
"""

from __future__ import annotations

import importlib
import pathlib
import sys
import tomllib
import uuid
from collections.abc import Iterator

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import (  # noqa: E402
    main,
    render_jobs,
    run_job_command,
    run_scheduler_command,
    run_worker_command,
)

_APP_MODULE = """\
from sqlmodel import Field

from terp.core import (
    BaseSchema,
    ControlPlane,
    JobCatalog,
    JobContext,
    JobDefinition,
    create_app,
)

executed: list[str] = []


class Payload(BaseSchema):
    label: str = Field(max_length=50)


def _handler(ctx: JobContext, payload: Payload) -> None:
    executed.append(payload.label)


JOB = JobDefinition(name="docs.create", payload_schema=Payload, handler=_handler)


def build():
    return create_app([], control_plane=ControlPlane(jobs=JobCatalog([JOB])))


app = build()
"""

_PLANE_MODULE = """\
import uuid

from sqlmodel import Field

from terp.core import (
    BaseSchema,
    ControlPlane,
    JobCatalog,
    JobContext,
    JobDefinition,
    JobVisibility,
)


class Payload(BaseSchema):
    label: str = Field(max_length=50)


def _handler(ctx: JobContext, payload: Payload) -> None:
    return None


JOB = JobDefinition(
    name="sync.customers.pull",
    payload_schema=Payload,
    handler=_handler,
    queue="sync",
    visibility=JobVisibility.INTERNAL,
)
control_plane = ControlPlane(
    jobs=JobCatalog([JOB]),
    job_system_actor_id=uuid.UUID("00000000-0000-0000-0000-0000000000aa"),
)
EMPTY = ControlPlane()
"""


_WORKER_APP_MODULE = """\
from sqlmodel import Field, SQLModel

from terp.core import (
    BaseSchema,
    ControlPlane,
    JobCatalog,
    JobContext,
    JobDefinition,
    create_app,
    enqueue,
)
from terp.core._internal.engine import get_engine
from terp.core._internal.session_guard import WriteGuardedSession

from terp.capabilities.outbox import OutboxJobQueue

drained: list[str] = []


class Payload(BaseSchema):
    label: str = Field(max_length=50)


def _handler(ctx: JobContext, payload: Payload) -> None:
    drained.append(payload.label)


JOB = JobDefinition(name="docs.create", payload_schema=Payload, handler=_handler)


def build():
    app = create_app(
        [], control_plane=ControlPlane(jobs=JobCatalog([JOB])), job_queue=OutboxJobQueue()
    )
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    with WriteGuardedSession(engine) as session:
        enqueue(session, job=JOB, payload=Payload(label="cli"))
    return app
"""


def _write_module(tmp_path: pathlib.Path, name: str, source: str) -> str:
    """Write *source* as an importable module under *tmp_path* and return its name."""
    (tmp_path / f"{name}.py").write_text(source, encoding="utf-8")
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))
    sys.modules.pop(name, None)
    return name


# --------------------------------------------------------------------------- #
# terp jobs run — the external-scheduler trigger
# --------------------------------------------------------------------------- #
def test_run_job_command_enqueues_and_runs_the_handler(tmp_path: pathlib.Path) -> None:
    name = _write_module(tmp_path, "jobs_app_run", _APP_MODULE)
    message = run_job_command(
        "docs.create", payload='{"label": "x"}', app_ref=f"{name}:build", app_root=tmp_path
    )
    assert "enqueued 'docs.create'" in message
    assert importlib.import_module(name).executed == ["x"]


def test_run_job_command_accepts_an_app_instance(tmp_path: pathlib.Path) -> None:
    # The ``app`` attribute is a built FastAPI instance, not a factory.
    name = _write_module(tmp_path, "jobs_app_inst", _APP_MODULE)
    run_job_command(
        "docs.create", payload='{"label": "y"}', app_ref=f"{name}:app", app_root=tmp_path
    )
    assert importlib.import_module(name).executed == ["y"]


def test_run_job_command_rejects_an_unknown_job(tmp_path: pathlib.Path) -> None:
    name = _write_module(tmp_path, "jobs_app_unknown", _APP_MODULE)
    with pytest.raises(SystemExit, match="not registered"):
        run_job_command("nope.missing", app_ref=f"{name}:build", app_root=tmp_path)


def test_run_job_command_rejects_bad_json(tmp_path: pathlib.Path) -> None:
    name = _write_module(tmp_path, "jobs_app_badjson", _APP_MODULE)
    with pytest.raises(SystemExit, match="not valid JSON"):
        run_job_command(
            "docs.create", payload="{not json", app_ref=f"{name}:build", app_root=tmp_path
        )


def test_run_job_command_rejects_a_non_app(tmp_path: pathlib.Path) -> None:
    # JOB is a JobDefinition: present but neither a FastAPI app nor a factory for one.
    name = _write_module(tmp_path, "jobs_app_notapp", _APP_MODULE)
    with pytest.raises(SystemExit, match="did not resolve to a FastAPI"):
        run_job_command("docs.create", app_ref=f"{name}:JOB", app_root=tmp_path)


def test_run_job_command_rejects_an_empty_reference(tmp_path: pathlib.Path) -> None:
    with pytest.raises(SystemExit, match="not a valid"):
        run_job_command("docs.create", app_ref=":build", app_root=tmp_path)


# --------------------------------------------------------------------------- #
# terp jobs list / terp inspect jobs — the generated catalog listing
# --------------------------------------------------------------------------- #
def test_render_jobs_lists_the_catalog(tmp_path: pathlib.Path) -> None:
    name = _write_module(tmp_path, "jobs_plane", _PLANE_MODULE)
    out = render_jobs(f"{name}:control_plane")
    assert "sync.customers.pull" in out
    assert "queue=sync" in out
    assert "visibility=internal" in out
    assert "System actor: 00000000-0000-0000-0000-0000000000aa" in out


def test_render_jobs_reports_an_empty_catalog(tmp_path: pathlib.Path) -> None:
    name = _write_module(tmp_path, "jobs_plane_empty", _PLANE_MODULE)
    out = render_jobs(f"{name}:EMPTY")
    assert "<none declared>" in out
    assert "System actor" not in out  # no system actor configured


def test_render_jobs_rejects_a_non_control_plane(tmp_path: pathlib.Path) -> None:
    name = _write_module(tmp_path, "jobs_plane_bad", _PLANE_MODULE)
    with pytest.raises(SystemExit, match="did not resolve to a terp.core.ControlPlane"):
        render_jobs(f"{name}:JOB")


def test_render_jobs_rejects_an_empty_reference() -> None:
    with pytest.raises(SystemExit, match="not a valid"):
        render_jobs(":control_plane")


# --------------------------------------------------------------------------- #
# main() dispatch
# --------------------------------------------------------------------------- #
def test_cli_jobs_run_dispatch(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    name = _write_module(tmp_path, "jobs_app_cli", _APP_MODULE)
    main(["jobs", "run", "docs.create", "--payload", '{"label": "z"}', "--app", f"{name}:build", "--app-root", str(tmp_path)])
    assert "enqueued 'docs.create'" in capsys.readouterr().out
    assert importlib.import_module(name).executed == ["z"]


def test_cli_jobs_list_dispatch(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    name = _write_module(tmp_path, "jobs_plane_cli", _PLANE_MODULE)
    main(["jobs", "list", "--object", f"{name}:control_plane"])
    assert "sync.customers.pull" in capsys.readouterr().out


def test_cli_inspect_jobs_dispatch(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    name = _write_module(tmp_path, "jobs_plane_inspect", _PLANE_MODULE)
    main(["inspect", "jobs", "--object", f"{name}:control_plane"])
    assert "sync.customers.pull" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# terp jobs worker — drain the durable outbox (ADR 0045)
# --------------------------------------------------------------------------- #
@pytest.fixture
def worker_db(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the process engine at a temp file DB (independent connections) and reset it."""
    from terp.core._internal.engine import reset_engine
    from terp.core.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{tmp_path / 'cli_worker.db'}")
    reset_engine()
    yield
    reset_engine()


def test_run_worker_command_drains_the_outbox(tmp_path: pathlib.Path, worker_db: None) -> None:
    # Write the app module but do NOT pre-add tmp_path to sys.path, so run_worker_command
    # itself inserts the app root (the external-scheduler / container entrypoint path).
    (tmp_path / "jobs_worker_cmd.py").write_text(_WORKER_APP_MODULE, encoding="utf-8")
    sys.modules.pop("jobs_worker_cmd", None)
    message = run_worker_command(app_ref="jobs_worker_cmd:build", app_root=tmp_path, max_cycles=5)
    assert "outbox worker drained" in message
    assert "dispatched=1" in message
    assert importlib.import_module("jobs_worker_cmd").drained == ["cli"]


def test_cli_jobs_worker_dispatch(
    tmp_path: pathlib.Path, worker_db: None, capsys: pytest.CaptureFixture[str]
) -> None:
    name = _write_module(tmp_path, "jobs_worker_cli", _WORKER_APP_MODULE)
    main(
        ["jobs", "worker", "--app", f"{name}:build", "--app-root", str(tmp_path), "--max-cycles", "5"]
    )
    out = capsys.readouterr().out
    assert "outbox worker drained" in out and "dispatched=1" in out
    assert importlib.import_module(name).drained == ["cli"]


def test_run_worker_command_without_the_outbox_capability_is_directive(
    tmp_path: pathlib.Path, worker_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # terp-cap-outbox is an OPTIONAL extra of terp-cli (`terp-cli[worker]`): the base CLI
    # never installs a table-owning capability, so a worker started without it must fail
    # with the fix, not a raw ImportError.
    (tmp_path / "jobs_worker_noext.py").write_text(
        "from terp.core import create_app\n\n\ndef build():\n    return create_app([])\n",
        encoding="utf-8",
    )
    sys.modules.pop("jobs_worker_noext", None)
    monkeypatch.setitem(sys.modules, "terp.capabilities.outbox", None)
    with pytest.raises(SystemExit, match=r"terp-cli\[worker\]"):
        run_worker_command(app_ref="jobs_worker_noext:build", app_root=tmp_path, max_cycles=1)


# --------------------------------------------------------------------------- #
# terp jobs scheduler — run the in-process scheduler (ADR 0047/0048 CLI)
# --------------------------------------------------------------------------- #
_SCHEDULER_APP_MODULE = """\
from sqlmodel import Field

from terp.core import (
    BaseSchema,
    ControlPlane,
    JobCatalog,
    JobContext,
    JobDefinition,
    ScheduleCatalog,
    ScheduleDefinition,
    create_app,
)


class Payload(BaseSchema):
    label: str | None = Field(default=None, max_length=50)


def _handler(ctx: JobContext, payload: Payload) -> None:
    return None


JOB = JobDefinition(name="sync.customers.pull", payload_schema=Payload, handler=_handler)
SCHEDULE = ScheduleDefinition(name="sync.customers.nightly", job=JOB, cron="0 2 * * *")


def build():
    return create_app(
        [],
        control_plane=ControlPlane(jobs=JobCatalog([JOB]), schedules=ScheduleCatalog([SCHEDULE])),
    )
"""


class _FakeScheduler:
    """Records register_all + start without a real (blocking) scheduler engine."""

    def __init__(self) -> None:
        self.registered: object = None
        self.started = False

    def register_all(self, catalog: object) -> None:
        self.registered = catalog

    def start(self) -> None:
        self.started = True


def test_run_scheduler_command_registers_and_starts(tmp_path: pathlib.Path) -> None:
    # Write the module but do NOT pre-add tmp_path to sys.path, so run_scheduler_command
    # inserts the app root itself (the scheduler-process entrypoint path).
    (tmp_path / "jobs_sched_cmd.py").write_text(_SCHEDULER_APP_MODULE, encoding="utf-8")
    sys.modules.pop("jobs_sched_cmd", None)
    fake = _FakeScheduler()
    message = run_scheduler_command(
        app_ref="jobs_sched_cmd:build", app_root=tmp_path, scheduler=fake
    )
    assert fake.started
    assert fake.registered.names() == ("sync.customers.nightly",)  # type: ignore[attr-defined]
    assert "1 schedule(s) registered: sync.customers.nightly" in message


def test_default_scheduler_builds_an_apscheduler_scheduler() -> None:
    from terp.capabilities.scheduler_apscheduler import ApschedulerScheduler
    from terp.cli.jobs import _default_scheduler

    assert isinstance(_default_scheduler(), ApschedulerScheduler)


def test_default_scheduler_without_the_adapter_capability_is_directive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # terp-cli keeps no hard dependency on the APScheduler adapter (ADR 0049): a
    # scheduler started without it must fail with the fix, not a raw ImportError.
    from terp.cli.jobs import _default_scheduler

    monkeypatch.setitem(sys.modules, "terp.capabilities.scheduler_apscheduler", None)
    with pytest.raises(SystemExit, match=r"terp-cli\[scheduler\]"):
        _default_scheduler()


def test_cli_job_process_extras_are_selective_and_composable() -> None:
    project = tomllib.loads(
        (_REPO_ROOT / "packages" / "backend" / "cli" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )["project"]
    extras = project["optional-dependencies"]
    outbox = "terp-cap-outbox==0.1.0"
    scheduler = "terp-cap-scheduler-apscheduler==0.1.0"
    assert extras["worker"] == [outbox]
    assert extras["scheduler"] == [scheduler]
    assert set(extras["jobs"]) == {outbox, scheduler}
    assert outbox not in project["dependencies"]
    assert scheduler not in project["dependencies"]


def test_cli_jobs_scheduler_dispatch(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_run(**kwargs: object) -> str:
        captured.update(kwargs)
        return "scheduler stopped; 0 schedule(s) registered: <none>"

    monkeypatch.setattr("terp.cli.run_scheduler_command", _fake_run)
    main(["jobs", "scheduler", "--app", "x:app", "--app-root", str(tmp_path)])
    assert "scheduler stopped" in capsys.readouterr().out
    assert captured["app_ref"] == "x:app"
