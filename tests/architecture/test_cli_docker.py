"""``terp docker dev`` — the Compose workbench launcher (orchestration only; Docker not required).

Proves the pure planner (:func:`docker_dev_argv`) and the executor (:func:`run_docker_dev_command`)
with the process runner injected — a missing compose file fails closed, and the real ``_run``
helper is exercised with a trivial process — so the command is verified without launching Docker.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import main, run_docker_dev_command  # noqa: E402
from terp.cli.docker import (  # noqa: E402
    _run,
    compose_logs_argv,
    compose_ps_argv,
    docker_dev_argv,
    failed_services,
)


def test_docker_dev_argv_is_a_compose_watch() -> None:
    assert docker_dev_argv("/x/docker-compose.yml") == (
        "docker",
        "compose",
        "-f",
        "/x/docker-compose.yml",
        "watch",
    )


def test_docker_dev_argv_includes_a_project_name() -> None:
    assert docker_dev_argv("c.yml", project_name="terp") == (
        "docker",
        "compose",
        "-f",
        "c.yml",
        "-p",
        "terp",
        "watch",
    )


def test_run_docker_dev_invokes_the_runner(tmp_path: pathlib.Path) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    calls: list[tuple[str, ...]] = []
    message = run_docker_dev_command(
        compose_file="docker-compose.yml",
        root=tmp_path,
        runner=lambda argv: calls.append(tuple(argv)) or 0,
    )
    assert "exited with status 0" in message
    assert calls == [("docker", "compose", "-f", str(compose.resolve()), "watch")]


def test_run_docker_dev_accepts_an_absolute_compose_path(tmp_path: pathlib.Path) -> None:
    compose = tmp_path / "compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    seen: list = []
    run_docker_dev_command(compose_file=str(compose), runner=lambda argv: seen.append(argv) or 0)
    assert str(compose) in seen[0]


def test_run_docker_dev_rejects_a_missing_compose_file(tmp_path: pathlib.Path) -> None:
    with pytest.raises(SystemExit, match="compose file not found"):
        run_docker_dev_command(compose_file="nope.yml", root=tmp_path, runner=lambda argv: 0)


def test_run_helper_runs_a_real_process() -> None:
    # `_run` resolves the executable and returns its exit status (proven with a trivial process).
    assert _run([sys.executable, "-c", "raise SystemExit(0)"]) == 0


# --------------------------------------------------------------------------- #
# On failure, say what actually happened
# --------------------------------------------------------------------------- #
# Compose reports a failed dependency as `service "x" didn't complete successfully:
# exit 1` — and that is the entire user-visible symptom, while the cause sits in a
# container log nobody was told to read. This command owns the topology, so it can
# name the failing service and print what it said.


def test_failed_services_reads_non_zero_exits() -> None:
    ps = """[{"Service": "api", "ExitCode": 0}, {"Service": "publish", "ExitCode": 1}]"""
    assert failed_services(ps) == ("publish",)


def test_failed_services_accepts_newline_delimited_objects() -> None:
    """Compose has emitted both an array and NDJSON across versions."""
    ps = '{"Service": "a", "ExitCode": 1}\n{"Service": "b", "ExitCode": 0}\n'
    assert failed_services(ps) == ("a",)


def test_failed_services_reports_one_failure_once() -> None:
    """Compose reports a failed one-shot once per waiter that observed it (the reported
    symptom arrived twice for one failure). Repeating its log per waiter would reproduce
    exactly the noise this replaces."""
    ps = '[{"Service": "publish", "ExitCode": 1}, {"Service": "publish", "ExitCode": 1}]'
    assert failed_services(ps) == ("publish",)


def test_failed_services_tolerates_junk() -> None:
    assert failed_services("") == ()
    assert failed_services("not json at all") == ()


def test_ps_and_logs_argv_target_the_same_project() -> None:
    assert compose_ps_argv("c.yml", project_name="p")[:6] == (
        "docker",
        "compose",
        "-f",
        "c.yml",
        "-p",
        "p",
    )
    assert "--tail=50" in compose_logs_argv("c.yml", "api")
    assert compose_logs_argv("c.yml", "api")[-1] == "api"


def test_a_failing_workbench_prints_the_failing_service_log(tmp_path: pathlib.Path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

    def capture(argv):
        if "ps" in argv:
            return 0, '[{"Service": "publish-operations", "ExitCode": 1}]'
        return 0, "Operation registry publish login failed: [Errno 111] Connection refused."

    message = run_docker_dev_command(root=tmp_path, runner=lambda argv: 1, capture=capture)
    assert "exited with status 1" in message
    assert "publish-operations" in message
    assert "Connection refused" in message


def test_a_successful_workbench_runs_no_diagnostics(tmp_path: pathlib.Path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    calls: list = []
    message = run_docker_dev_command(
        root=tmp_path,
        runner=lambda argv: 0,
        capture=lambda argv: calls.append(argv) or (0, ""),
    )
    assert calls == []
    assert message == "docker compose watch exited with status 0"


def test_diagnosis_never_replaces_the_real_error(tmp_path: pathlib.Path) -> None:
    """This runs *after* a failure the caller is already reporting. A daemon that has
    gone away must not turn into an error about diagnosing the error."""
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    message = run_docker_dev_command(
        root=tmp_path, runner=lambda argv: 1, capture=lambda argv: (1, "daemon gone")
    )
    assert message == "docker compose watch exited with status 1"


def test_cli_docker_dev_dispatch(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr("terp.cli.docker._run", lambda argv: 0)
    main(["docker", "dev", "--root", str(tmp_path)])
    assert "exited with status 0" in capsys.readouterr().out
