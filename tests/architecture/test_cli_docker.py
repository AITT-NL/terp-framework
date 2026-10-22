"""``terp docker dev`` — the Compose workbench launcher (orchestration only; Docker not required).

Proves the pure planner (:func:`docker_dev_argv`) and the executor (:func:`run_docker_dev_command`)
with the process runner injected — a missing compose file fails closed, and the real ``_run``
helper is exercised with a trivial process — so the command is verified without launching Docker.
"""

from __future__ import annotations

import pathlib
import signal
import subprocess
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import main, run_docker_dev_command  # noqa: E402
from terp.cli.docker import (  # noqa: E402
    _KILL,
    _capture,
    _fingerprint,
    _Finished,
    _run,
    _spawn,
    _stop,
    _watch_session,
    compose_logs_argv,
    compose_ps_argv,
    docker_dev_argv,
    diagnose_failure,
    failed_services,
    model_inputs,
)


@pytest.fixture(autouse=True)
def _no_docker_unless_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    """The start's stale-mask check asks Docker before `watch` (terp.cli.docker_masks).

    A test that injects only a runner must not reach a real daemon through the default
    capture, so the module's default answers "not available" unless a test injects one.
    The real helper stays imported above for the test that exercises it directly.
    """
    monkeypatch.setattr("terp.cli.docker._capture", lambda argv: (1, "no docker in a unit test"))

    def _no_real_watch(argv):
        raise AssertionError(f"a unit test reached the real spawn: {list(argv)}")

    monkeypatch.setattr("terp.cli.docker._spawn", _no_real_watch)


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


def test_run_docker_dev_assigns_host_ports_before_starting(
    tmp_path: pathlib.Path, capsys
) -> None:
    """The compose file requires its host ports, and this is what makes that
    requirement invisible to somebody who has never heard of `terp ports`.

    One command from a checkout to a running app is the promise this command
    already makes, and ADR 0134 decision 1 refuses to spend it in order to
    enforce decision 3 — so the assignment happens here rather than being a step
    the reader has to know about.
    """
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    order: list[str] = []

    def _runner(argv):
        order.append("compose")
        return 0

    run_docker_dev_command(
        compose_file="docker-compose.yml", root=tmp_path, runner=_runner
    )
    published = (tmp_path / ".env").read_text(encoding="utf-8")

    assert "WEB_PORT=" in published
    assert "API_PORT=" in published
    assert order == ["compose"]
    # And it said so, because a file it wrote into the checkout is not a thing to
    # do silently.
    assert "terp ports" in capsys.readouterr().out


def test_run_docker_dev_assigns_beside_the_compose_file_not_beside_root(
    tmp_path: pathlib.Path, capsys
) -> None:
    """Compose's project directory is the directory of the first ``-f``, and that
    is the only ``.env`` it reads.

    Publishing into ``--root`` instead would write the assignment into a file this
    very command then ignores, and the start would fail on a required variable
    that had just been set — the silent half of the defect, one level up.
    Verified against Compose: with a ``.env`` in the working directory and another
    beside the compose file, ``docker compose config`` resolves the one beside the
    file.
    """
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    run_docker_dev_command(
        compose_file=str(nested / "docker-compose.yml"),
        root=elsewhere,
        runner=lambda argv: 0,
    )
    capsys.readouterr()

    assert (nested / ".env").is_file()
    assert not (elsewhere / ".env").exists()


def test_run_docker_dev_leaves_an_unmanaged_app_alone(
    tmp_path: pathlib.Path, capsys
) -> None:
    """An app that drives its own loop names its own ports, so nothing is written
    and nothing is said."""
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "workbench.json").write_text(
        '{"unmanaged": true, "reason": "a Makefile"}', encoding="utf-8"
    )
    run_docker_dev_command(
        compose_file="docker-compose.yml", root=tmp_path, runner=lambda argv: 0
    )
    assert not (tmp_path / ".env").exists()
    assert "terp ports" not in capsys.readouterr().out


def test_run_docker_dev_starts_the_stack_even_when_assignment_fails(
    tmp_path: pathlib.Path, capsys
) -> None:
    """A start that dies over a ledger is worse than one that lets compose speak.

    The compose file's own required-variable error names the command to run; a
    traceback out of the assigner names nothing the reader can act on.
    """
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "workbench.json").write_text("{not json", encoding="utf-8")
    calls: list = []

    run_docker_dev_command(
        compose_file="docker-compose.yml",
        root=tmp_path,
        runner=lambda argv: calls.append(argv) or 0,
    )
    assert len(calls) == 1
    assert "workbench.json" in capsys.readouterr().out


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
    # The start's own stale-mask check asks for the config first; no logs are read.
    assert [argv for argv in calls if "logs" in argv] == []
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
    monkeypatch.setattr("terp.cli.docker._spawn", lambda argv: _Finished(0))
    main(["docker", "dev", "--root", str(tmp_path)])
    assert "exited with status 0" in capsys.readouterr().out


def test_failed_services_skips_blank_lines_between_objects() -> None:
    """Compose's NDJSON output has arrived with trailing and interleaved blank lines.
    A blank line is not a parse failure to swallow silently — it is simply not a record."""
    # Two objects, so the whole-document parse fails and the NDJSON fallback runs;
    # the blank line between them is what this pins. A single object would parse as
    # JSON and never reach the fallback at all.
    ps = '{"Service": "publish", "ExitCode": 1}' \
         '\n\n' \
         '{"Service": "api", "ExitCode": 0}'
    assert failed_services(ps) == ("publish",)


def test_failed_services_ignores_a_non_object_entry() -> None:
    """A well-formed array whose members are not all objects still yields the ones that
    are. Indexing blindly would raise here, inside the diagnostic that runs *after* a
    failure — turning a reported error into a traceback about reporting it."""
    ps = '[1, "two", null, {"Service": "publish", "ExitCode": 1}]'
    assert failed_services(ps) == ("publish",)


def test_diagnose_returns_nothing_when_every_service_exited_clean(
    tmp_path: pathlib.Path,
) -> None:
    """`ps` succeeded and named no failure: the caller's own error is the whole story,
    so the diagnosis must add nothing rather than an empty-looking section header."""
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    report = diagnose_failure(
        tmp_path / "docker-compose.yml",
        capture=lambda argv: (0, '[{"Service": "api", "ExitCode": 0}]'),
    )
    assert report == ""


def test_capture_runs_a_real_process_and_returns_its_combined_output() -> None:
    """The real capture helper, exercised with a trivial process: everything above
    injects it, so without this the one function that actually shells out is unproven."""
    status, output = _capture(
        (sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)")
    )
    assert status == 0
    assert "out" in output
    assert "err" in output


def test_capture_returns_a_non_zero_status_with_its_output() -> None:
    status, output = _capture((sys.executable, "-c", "import sys; sys.exit(3)"))
    assert status == 3
    assert output == ""


# --------------------------------------------------------------------------- #
# Keep `watch` on the configuration the containers run
# --------------------------------------------------------------------------- #
# `watch` loads the project once. A rebuild after a settings change converged the whole
# project against that stale copy: measured on the reference app (Compose v2.40.3), a
# frontend dependency change after `.app.env` had been changed and applied with
# `docker compose up -d` recreated every backend service with the OLD settings and left
# all of them stopped. So the command restarts `watch` when a file it loaded changes.

_ANCHORED = """\
x-backend: &backend
  image: app-backend
  env_file:
    - path: .app.env
      required: false
services:
  migrate:
    <<: *backend
  worker:
    <<: *backend
    env_file:
      - path: .app.env
        required: false
      - .app.worker.env
  web:
    image: app-frontend
    env_file: frontend/.env.dev
  proxy:
    image: proxy
    env_file: ${CONFIG_DIR}/proxy.env
  odd: just-a-string
"""


class _Watch:
    """A `watch` that runs until the test says it has exited."""

    def __init__(self, argv) -> None:
        self.argv = tuple(argv)
        self.pid = 4242
        self.status: int | None = None

    def poll(self) -> int | None:
        return self.status

    def wait(self, timeout: float | None = None) -> int:
        return self.status or 0

    def kill(self) -> None:
        self.status = -9


def _session(tmp_path: pathlib.Path, steps: list):
    """Run a session in which every poll interval is one step of *steps*.

    A step receives the running watch and may edit files or end it. Returns the
    session's status and what it did, in order.
    """
    compose = tmp_path / "docker-compose.yml"
    if not compose.exists():
        compose.write_text(_ANCHORED, encoding="utf-8")
    events: list[tuple] = []
    running: list[_Watch] = []

    def spawn(argv):
        process = _Watch(argv)
        running.append(process)
        events.append(("spawn", process.argv[4:]))
        return process

    def stop(process):
        events.append(("stop", process.argv[4:]))
        if process.status is None:
            process.status = 0

    def sleep(seconds):
        assert seconds == 1.0
        steps.pop(0)(running[-1])

    status = _watch_session(compose, project_name=None, spawn=spawn, stop=stop, sleep=sleep)
    return status, events


def test_model_inputs_are_the_compose_file_its_dotenv_and_every_forwarded_env_file(
    tmp_path: pathlib.Path,
) -> None:
    """The anchor every backend service merges is resolved; a service's own list replaces
    it; an interpolated path is compose's to resolve, not this command's."""
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(_ANCHORED, encoding="utf-8")

    assert model_inputs(compose) == tuple(
        sorted(
            {
                compose,
                tmp_path / ".env",
                tmp_path / ".app.env",
                tmp_path / ".app.worker.env",
                tmp_path / "frontend" / ".env.dev",
            }
        )
    )


@pytest.mark.parametrize(
    "content",
    [b"services: [unclosed\n", b"just a string\n", b"services: [1, 2]\n", b"\xff\xfe\x00"],
)
def test_a_compose_file_that_cannot_be_read_still_has_its_dotenv_watched(
    tmp_path: pathlib.Path, content: bytes
) -> None:
    """`watch` says what is wrong with the file in its own words; meanwhile the file itself
    and the `.env` it interpolates from are still what a fix would change."""
    compose = tmp_path / "docker-compose.yml"
    compose.write_bytes(content)
    assert model_inputs(compose) == tuple(sorted({compose, tmp_path / ".env"}))


def test_a_fingerprint_is_by_content_and_knows_a_missing_file(tmp_path: pathlib.Path) -> None:
    present = tmp_path / ".app.env"
    present.write_text("A=1\n", encoding="utf-8")
    before = _fingerprint([present, tmp_path / ".env"])
    present.write_text("A=1\n", encoding="utf-8")  # saved again, unchanged

    assert before[tmp_path / ".env"] is None
    assert _fingerprint([present, tmp_path / ".env"]) == before


def test_a_settings_change_starts_watch_again(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one sequence that keeps the stack and `watch` on the same configuration: stop
    the stale watch and start the whole of it again, so its own `up` applies the change.

    Never `up -d` and then `watch --no-up`: Compose v2's `watch` hashes a service with an
    `env_file` differently from `up` (measured, v2.40.3), so a `watch` that did not bring
    the stack up itself treats every such service as diverged, and its next frontend
    rebuild stops all of them.
    """
    (tmp_path / ".app.env").write_text("MAIL_FROM=old@example.test\n", encoding="utf-8")

    def change(watch):
        (tmp_path / ".app.env").write_text("MAIL_FROM=new@example.test\n", encoding="utf-8")

    def exit_watch(watch):
        watch.status = 3

    status, events = _session(tmp_path, [change, exit_watch])

    assert status == 3
    assert events == [
        ("spawn", ("watch",)),
        ("stop", ("watch",)),
        ("spawn", ("watch",)),
        ("stop", ("watch",)),
    ]
    assert ".app.env changed" in capsys.readouterr().out


def test_a_save_that_changes_nothing_restarts_nothing(tmp_path: pathlib.Path) -> None:
    (tmp_path / ".app.env").write_text("A=1\n", encoding="utf-8")

    def save_unchanged(watch):
        (tmp_path / ".app.env").write_text("A=1\n", encoding="utf-8")

    def exit_watch(watch):
        watch.status = 0

    status, events = _session(tmp_path, [save_unchanged, exit_watch])

    assert status == 0
    assert events == [("spawn", ("watch",)), ("stop", ("watch",))]


def test_a_file_the_changed_compose_file_names_is_watched_from_then_on(
    tmp_path: pathlib.Path,
) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services:\n  api:\n    image: a\n", encoding="utf-8")

    def name_an_env_file(watch):
        compose.write_text(
            "services:\n  api:\n    image: a\n    env_file: .app.api.env\n", encoding="utf-8"
        )

    def change_it(watch):
        (tmp_path / ".app.api.env").write_text("A=1\n", encoding="utf-8")

    def exit_watch(watch):
        watch.status = 0

    _, events = _session(tmp_path, [name_an_env_file, change_it, exit_watch])

    assert [event for event in events if event[0] == "spawn"] == [("spawn", ("watch",))] * 3


def test_ctrl_c_stops_watch_and_goes_on(tmp_path: pathlib.Path) -> None:
    def interrupt(watch):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _session(tmp_path, [interrupt])


def test_the_command_supervises_watch_when_a_spawn_is_given(tmp_path: pathlib.Path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    started: list = []

    def spawn(argv):
        started.append(tuple(argv))
        process = _Watch(argv)
        process.status = 0
        return process

    message = run_docker_dev_command(
        root=tmp_path, spawn=spawn, stop=lambda process: None, sleep=lambda seconds: None
    )

    assert message == "docker compose watch exited with status 0"
    assert started[0][-1] == "watch"


def test_spawn_gives_watch_its_own_process_group_outside_windows() -> None:
    """The docker CLI does not pass a signal on to the compose plugin while a terminal is
    attached, so `_stop` signals the group, and the group has to exist first."""
    seen: list = []

    def popen(argv, **options):
        seen.append((argv, options))
        return _Watch(argv)

    _spawn(["docker", "compose", "watch"], platform="linux", popen=popen)
    _spawn(["docker", "compose", "watch"], platform="win32", popen=popen)

    assert seen[0][1] == {"process_group": 0}
    assert seen[1][1] == {}
    assert seen[0][0][1:] == ["compose", "watch"]


def test_stop_leaves_an_exited_watch_alone() -> None:
    process = _Watch(["watch"])
    process.status = 0
    sent: list = []
    _stop(process, platform="linux", signal_group=lambda pid, sig: sent.append(sig))
    assert sent == []


def test_stop_interrupts_the_whole_group_outside_windows() -> None:
    process = _Watch(["watch"])
    sent: list = []
    _stop(process, platform="linux", signal_group=lambda pid, sig: sent.append((pid, sig)))
    assert sent == [(4242, signal.SIGINT)]


def test_stop_ends_the_tree_on_windows() -> None:
    process = _Watch(["watch"])
    ran: list = []
    _stop(process, platform="win32", run=lambda argv, **kwargs: ran.append(argv))
    assert ran[0][0].lower().endswith("taskkill.exe")
    assert ran[0][1:] == ["/PID", "4242", "/T", "/F"]


class _Stubborn(_Watch):
    """A watch that outlives the signal it was sent."""

    def wait(self, timeout: float | None = None) -> int:
        if timeout is not None:
            raise subprocess.TimeoutExpired("watch", timeout)
        return 0


def test_stop_kills_a_watch_that_outlives_the_interrupt() -> None:
    process = _Stubborn(["watch"])
    sent: list = []
    _stop(process, platform="linux", signal_group=lambda pid, sig: sent.append(sig), wait_seconds=0)
    assert sent == [signal.SIGINT, _KILL]

    windows = _Stubborn(["watch"])
    _stop(windows, platform="win32", run=lambda argv, **kwargs: None, wait_seconds=0)
    assert windows.status == -9


def test_a_runner_alone_runs_watch_to_completion() -> None:
    """What an injected blocking runner becomes: a watch that has already exited."""
    finished = _Finished(5)
    assert (finished.poll(), finished.wait(), finished.kill()) == (5, 5, None)
