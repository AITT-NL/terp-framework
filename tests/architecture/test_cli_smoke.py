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

import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli.smoke import (  # noqa: E402
    _interpolate,
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
