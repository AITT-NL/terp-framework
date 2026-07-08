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
from terp.cli.docker import _run, docker_dev_argv  # noqa: E402


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


def test_cli_docker_dev_dispatch(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr("terp.cli.docker._run", lambda argv: 0)
    main(["docker", "dev", "--root", str(tmp_path)])
    assert "exited with status 0" in capsys.readouterr().out
