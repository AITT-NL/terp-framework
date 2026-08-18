"""``terp smoke`` — the workbench's boot chain, in-process, with no Docker daemon.

Answers "is this my app or is this my environment?". The topology, the commands and the
ordering are all declared in ``docker-compose.yml``, so the translation to something
runnable on the host is mechanical — and these tests pin the two translations that are
easy to get silently wrong: a container PATH (``/app/app``, meaningless here) and a
container ADDRESS (``http://api:8000``, a DNS name that does not resolve off the compose
network, and the exact shape whose absence produced "Connection refused" with no
explanation).

Nothing here runs a process: the planner is pure, which is what makes the plan assertable.
"""

from __future__ import annotations

import http.server
import pathlib
import socket
import sys
import threading

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import main  # noqa: E402
from terp.cli.smoke import (  # noqa: E402
    SmokeStep,
    _await_health,
    _backend_services,
    _default_runner,
    _depends_on,
    _host_path,
    _interpolate,
    _mounts,
    _ordered,
    _read_env_file,
    _service_environment,
    _spawn_server,
    _rewrite_addresses,
    _strip_flags,
    render_smoke_plan,
    run_smoke_command,
    smoke_plan,
)

_COMPOSE = """\
name: app
x-backend: &backend
  image: app-backend
  env_file:
    - path: .app.env
      required: false
  environment: &backend-env
    DATABASE_URL: postgresql+psycopg://app:app@db:5432/app
    ENVIRONMENT: local
    MY_API: http://api:8000
  volumes:
    - ${TERP_DEV_HOST_ROOT:-.}/app:/app/app
services:
  db:
    image: postgres:17-alpine
  migrate:
    <<: *backend
    command: ["terp", "migrate", "upgrade", "--app-root", "/app/app"]
    depends_on:
      db:
        condition: service_healthy
  api:
    <<: *backend
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
    healthcheck:
      test: ["CMD", "true"]
    depends_on:
      migrate:
        condition: service_completed_successfully
  publish:
    <<: *backend
    command: ["python", "-m", "engine.publish"]
    depends_on:
      api:
        condition: service_healthy
  web:
    image: app-frontend
    command: ["npm", "run", "dev"]
"""


@pytest.fixture
def project(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "docker-compose.yml").write_text(_COMPOSE, encoding="utf-8")
    return tmp_path


def _step(plan, service: str):
    return next(step for step in plan.steps if step.service == service)


# --------------------------------------------------------------------------- #
# what the chain is
# --------------------------------------------------------------------------- #
def test_the_chain_is_the_backend_image_in_dependency_order(
    project: pathlib.Path,
) -> None:
    plan = smoke_plan(project, api_port=9999)
    assert [step.service for step in plan.steps] == ["migrate", "api", "publish"]


def test_postgres_and_the_frontend_are_skipped(project: pathlib.Path) -> None:
    """Not the backend image: the database is replaced by SQLite and the Vite dev server
    says nothing about whether the backend boots. Skipping both is what removes the
    daemon requirement."""
    plan = smoke_plan(project, api_port=9999)
    assert set(plan.skipped) == {"db", "web"}


def test_the_healthchecked_service_is_the_server_and_the_rest_are_one_shots(
    project: pathlib.Path,
) -> None:
    plan = smoke_plan(project, api_port=9999)
    assert _step(plan, "api").kind == "server"
    assert _step(plan, "migrate").kind == "one-shot"
    assert _step(plan, "publish").kind == "one-shot"


def test_an_app_added_one_shot_is_included(project: pathlib.Path) -> None:
    """Discovered by image, never a migrate/seed/api name list: an app's own publisher
    is exactly the step this command exists to exercise, and naming the ones we shipped
    would skip it."""
    assert "publish" in {step.service for step in smoke_plan(project, api_port=1).steps}


# --------------------------------------------------------------------------- #
# the two translations
# --------------------------------------------------------------------------- #
def test_a_container_path_is_translated_through_the_bind_mount(
    project: pathlib.Path,
) -> None:
    argv = _step(smoke_plan(project, api_port=9999), "migrate").argv
    assert "/app/app" not in argv
    assert str(project / "app") in argv


def test_a_container_address_is_pointed_at_the_host_api(project: pathlib.Path) -> None:
    """`http://api:8000` resolves only on the compose network. Left alone, every one-shot
    after the API dies with "Connection refused" and an exit code."""
    environment = _step(smoke_plan(project, api_port=9999), "publish").environment
    assert environment["MY_API"] == "http://127.0.0.1:9999"


def test_address_rewriting_keeps_the_path_and_leaves_others_alone() -> None:
    assert (
        _rewrite_addresses("http://api:8000/v1/x", ["api"], 5)
        == "http://127.0.0.1:5/v1/x"
    )
    assert (
        _rewrite_addresses("http://elsewhere:8000", ["api"], 5)
        == "http://elsewhere:8000"
    )


def test_the_database_is_a_throwaway_sqlite_not_the_compose_postgres(
    project: pathlib.Path,
) -> None:
    plan = smoke_plan(project, api_port=9999)
    assert plan.database_url.startswith("sqlite")
    for step in plan.steps:
        assert step.environment["DATABASE_URL"] == plan.database_url


def test_the_server_binds_the_probed_port_and_drops_the_reloader(
    project: pathlib.Path,
) -> None:
    """A reloader forks a child the executor cannot wait on or terminate cleanly, and the
    compose file's port is the container's, not the one we probe."""
    argv = _step(smoke_plan(project, api_port=9999), "api").argv
    assert "--reload" not in argv
    assert argv[-4:] == ("--host", "127.0.0.1", "--port", "9999")
    assert argv.count("--port") == 1
    assert "0.0.0.0" not in argv  # noqa: S104 - asserting the bind is GONE


def test_the_project_root_is_importable(project: pathlib.Path) -> None:
    """The image installs the app editable under WORKDIR=/app; on the host that holds
    only after `uv sync`, which a checkout being diagnosed may not have done. Failing
    with an ImportError from this translation would answer the wrong question."""
    plan = smoke_plan(project, api_port=9999)
    for step in plan.steps:
        assert str(project) in step.environment["PYTHONPATH"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def test_interpolation_matches_compose_semantics() -> None:
    assert _interpolate("${A:-fallback}", {}) == "fallback"
    assert _interpolate("${A:-fallback}", {"A": "set"}) == "set"
    assert _interpolate("x${A}y", {"A": "-"}) == "x-y"
    assert _interpolate("plain", {}) == "plain"


def test_strip_flags_removes_a_flag_with_its_value() -> None:
    argv = ("a", "--host", "0.0.0.0", "--reload", "b")  # noqa: S104 - test input
    assert _strip_flags(argv, {"--host"}, {"--reload"}) == (
        "a",
        "b",
    )


# --------------------------------------------------------------------------- #
# the executor
# --------------------------------------------------------------------------- #
def test_a_failing_one_shot_reports_its_own_output_not_just_a_status(
    project: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole point: compose's `exit 1` withholds the cause, and the cause is the
    only thing that separates an app defect from an environment defect."""

    def runner(argv, environment, cwd):
        return (
            1,
            "Operation registry publish login failed: [Errno 111] Connection refused.",
        )

    assert run_smoke_command(root=project, runner=runner) == 1
    output = capsys.readouterr().out
    assert "FAILED" in output and "migrate" in output
    assert "Connection refused" in output


def test_a_missing_compose_file_fails_closed(tmp_path: pathlib.Path) -> None:
    with pytest.raises(SystemExit, match="compose file not found"):
        smoke_plan(tmp_path)


def test_the_plan_renders_without_running_anything(project: pathlib.Path) -> None:
    text = render_smoke_plan(root=project)
    assert "[one-shot] migrate" in text
    assert "[server] api" in text
    assert "skipped:  db, web" in text


# The helpers below are unit-tested directly. Each is a tolerance the command depends on:
# `terp smoke` reads an app's own compose file, so every shape a real compose file can
# legally take has to resolve to *something* rather than raise inside a diagnostic.


def test_depends_on_accepts_both_compose_forms_and_anything_else() -> None:
    assert _depends_on({"depends_on": ["db", "redis"]}) == {"db": None, "redis": None}
    assert _depends_on({"depends_on": {"db": {"condition": "service_healthy"}}}) == {
        "db": "service_healthy"
    }
    assert _depends_on({"depends_on": {"db": None}}) == {"db": None}
    assert _depends_on({}) == {}
    assert _depends_on("not a service") == {}


def test_backend_services_falls_back_to_api_when_it_declares_no_image() -> None:
    """The image tag is what identifies the backend's siblings. Without one there is
    nothing to match on, so the chain is api alone rather than every service in the file."""
    assert _backend_services({"api": {"command": ["x"]}, "db": {"image": "postgres"}}) == ["api"]
    assert _backend_services({"db": {"image": "postgres"}}) == []


def test_ordering_keeps_the_declared_order_when_dependencies_cannot_be_satisfied() -> None:
    """A cycle, or a dependency on a service outside the selection. This command
    diagnoses a boot chain; refusing to order one would withhold the diagnosis."""
    services = {
        "a": {"depends_on": ["b"]},
        "b": {"depends_on": ["a"]},
    }
    assert _ordered(services, ["a", "b"]) == ["a", "b"]


def test_mounts_ignore_shapes_that_are_not_host_to_container_binds() -> None:
    """A named volume, a long-form mapping, and a bare path are all legal compose and
    none of them translates a container path back to this checkout."""
    service = {"volumes": ["pgdata:/var/lib/postgresql", {"type": "volume"}, "/just-a-path"]}
    assert _mounts(service, {}) == [("pgdata", "/var/lib/postgresql")]
    assert _mounts({"volumes": None}, {}) == []


def test_a_container_path_with_no_matching_mount_is_left_alone() -> None:
    """Rewriting a path we have no bind for would invent a host location that does not
    exist; passing it through leaves the failure legible."""
    assert (
        _host_path({"volumes": ["./app:/app/app"]}, "/opt/elsewhere", pathlib.Path("/r"), {})
        == "/opt/elsewhere"
    )


def test_interpolation_leaves_an_unterminated_expansion_verbatim() -> None:
    """`${` with no closing brace is not something to guess at — compose would error, and
    this command must not silently produce a different string than the one written."""
    assert _interpolate("prefix-${UNCLOSED", {}) == "prefix-${UNCLOSED"


def test_env_file_reading_skips_comments_and_blanks_and_unquotes(tmp_path: pathlib.Path) -> None:
    path = tmp_path / ".app.env"
    path.write_text(
        "# a comment\n\n  \nQUOTED='single'\nDQUOTED=\"double\"\nPLAIN=value\nNOEQUALS\n",
        encoding="utf-8",
    )
    assert _read_env_file(path) == {
        "QUOTED": "single",
        "DQUOTED": "double",
        "PLAIN": "value",
    }


def test_env_file_reading_treats_an_absent_file_as_empty(tmp_path: pathlib.Path) -> None:
    assert _read_env_file(tmp_path / "nope.env") == {}


def test_service_environment_accepts_both_compose_forms() -> None:
    assert _service_environment({"environment": ["A=1", "B="]}) == {"A": "1", "B": ""}
    assert _service_environment({"environment": {"A": None}}) == {"A": ""}
    assert _service_environment({}) == {}


def test_a_compose_file_with_no_services_fails_closed(tmp_path: pathlib.Path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="declares no services"):
        smoke_plan(tmp_path)


def test_a_compose_file_with_no_backend_image_fails_closed(tmp_path: pathlib.Path) -> None:
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  db:\n    image: postgres:16\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="nothing to smoke"):
        smoke_plan(tmp_path)


def test_a_backend_service_without_a_command_is_not_a_step(tmp_path: pathlib.Path) -> None:
    """Only a service that declares a command has a boot step to run. One that inherits
    the image's entrypoint has nothing this command could translate and execute."""
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n"
        "  api:\n    image: app\n    command: [python, -m, http.server]\n"
        "  worker:\n    image: app\n",
        encoding="utf-8",
    )
    plan = smoke_plan(tmp_path)
    assert [step.service for step in plan.steps] == ["api"]


# The three functions below are the ones that actually touch the OS. Everything above
# injects a runner, so without these the real process launch, the health poll and the
# server teardown would be the only unproven parts of the command.


def test_the_default_runner_runs_a_real_process_with_its_environment(
    tmp_path: pathlib.Path,
) -> None:
    status, output = _default_runner(
        (sys.executable, "-c", "import os; print(os.environ['SMOKE_PROBE'])"),
        {"SMOKE_PROBE": "from-the-plan"},
        tmp_path,
    )
    assert status == 0
    assert "from-the-plan" in output


def test_the_default_runner_reports_a_failure_with_its_output(tmp_path: pathlib.Path) -> None:
    status, output = _default_runner(
        (sys.executable, "-c", "import sys; print('boom', file=sys.stderr); sys.exit(2)"),
        {},
        tmp_path,
    )
    assert status == 2
    assert "boom" in output


def test_the_health_poll_gives_up_rather_than_hanging() -> None:
    """A port nothing is listening on. The timeout is the whole point: a server that
    never comes up must end the command, not the developer's patience."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
    assert _await_health(dead_port, timeout=0.2) is False


def test_the_health_poll_returns_true_once_the_endpoint_answers() -> None:
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's interface
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            """Silence the default stderr access log."""

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert _await_health(server.server_port, timeout=5) is True
    finally:
        server.shutdown()
        server.server_close()


def test_a_server_that_never_answers_fails_the_run(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one-shots pass, the server starts, and health never comes up. That is a boot
    failure and must exit non-zero — the command exists to tell an app which half broke."""
    spawned: list[SmokeStep] = []

    class _FakeProcess:
        def __init__(self) -> None:
            self.terminated = False

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float | None = None) -> int:
            return 0

    process = _FakeProcess()
    monkeypatch.setattr(
        "terp.cli.smoke._spawn_server", lambda step, cwd: spawned.append(step) or process
    )
    monkeypatch.setattr("terp.cli.smoke._await_health", lambda port, *a, **k: False)
    status = run_smoke_command(root=project, runner=lambda argv, env, cwd: (0, ""))
    assert status == 1
    out = capsys.readouterr().out
    assert "never answered" in out
    assert [step.service for step in spawned] == ["api"]
    # Started by this command, so torn down by it even on the failure path.
    assert process.terminated is True


def test_a_healthy_chain_reports_success_and_stops_the_server(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class _FakeProcess:
        def __init__(self) -> None:
            self.terminated = False

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float | None = None) -> int:
            return 0

    process = _FakeProcess()
    monkeypatch.setattr("terp.cli.smoke._spawn_server", lambda step, cwd: process)
    monkeypatch.setattr("terp.cli.smoke._await_health", lambda port, *a, **k: True)
    status = run_smoke_command(root=project, runner=lambda argv, env, cwd: (0, ""))
    assert status == 0
    out = capsys.readouterr().out
    assert "is live on port" in out
    assert "the whole boot chain completed" in out
    assert process.terminated is True


def test_a_server_that_already_exited_is_not_terminated_again(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`poll()` returning a status means the process is already gone; calling terminate on
    it would be the teardown raising over a run that otherwise succeeded."""

    class _ExitedProcess:
        def poll(self) -> int:
            return 0

        def terminate(self) -> None:  # pragma: no cover - proving this is NOT reached
            raise AssertionError("terminate called on an already-exited process")

    monkeypatch.setattr("terp.cli.smoke._spawn_server", lambda step, cwd: _ExitedProcess())
    monkeypatch.setattr("terp.cli.smoke._await_health", lambda port, *a, **k: True)
    assert run_smoke_command(root=project, runner=lambda argv, env, cwd: (0, "")) == 0


def test_spawn_server_launches_the_step_and_is_cleaned_up(tmp_path: pathlib.Path) -> None:
    """The real Popen path, with a process that simply waits to be told to stop."""
    step = SmokeStep(
        service="api",
        kind="server",
        argv=(sys.executable, "-c", "import time; time.sleep(30)"),
        environment={},
    )
    process = _spawn_server(step, tmp_path)
    try:
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_cli_smoke_dispatch_runs_the_chain(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`terp smoke` reaches run_smoke_command and propagates its status as the exit code."""
    monkeypatch.setattr("terp.cli.smoke.run_smoke_command", lambda **kwargs: 0)
    with pytest.raises(SystemExit) as excinfo:
        main(["smoke", "--root", str(project)])
    assert excinfo.value.code == 0


def test_cli_smoke_plan_dispatch_prints_without_running(
    project: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--plan` is the no-daemon, no-side-effect read of the same chain."""
    main(["smoke", "--root", str(project), "--plan"])
    out = capsys.readouterr().out
    assert "[server] api" in out
