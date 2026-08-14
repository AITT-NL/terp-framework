"""``terp routes`` — the route-types generate-and-gate command (ADR 0092).

The command itself is thin: it runs the frontend's ``routes`` script, which is where the
extraction lives (``@terpjs/contract``'s ``terp-routes``, unit-tested in that package).
What is worth pinning here is the orchestration — the argv it advertises, that it fails
closed rather than reporting a success it did not get, and that the dev preflight
regenerates only when there is a frontend to generate into.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import main, run_routes_command  # noqa: E402
from terp.cli.dev import run_dev_command  # noqa: E402
from terp.cli.routes import routes_argv  # noqa: E402


def _frontend(root: pathlib.Path, *, wired: bool = True) -> pathlib.Path:
    """A frontend directory, with or without the ``routes`` script that opts in."""
    frontend = root / "frontend"
    frontend.mkdir(parents=True, exist_ok=True)
    scripts = {"routes": "terp-routes"} if wired else {"build": "vite build"}
    (frontend / "package.json").write_text(
        json.dumps({"scripts": scripts}), encoding="utf-8"
    )
    return frontend


def _never_run(argv: list[str], cwd: pathlib.Path) -> tuple[int, str]:
    raise AssertionError(f"npm must not be spawned for an unadopted app (tried {argv})")


class _DoneProc:
    """A process that has already exited (the dev supervisor's happy path)."""

    def poll(self) -> int:
        return 0

    def terminate(self) -> None:  # pragma: no cover - never reached
        raise AssertionError("a finished process is not terminated")


def test_the_advertised_argv_is_the_npm_script_and_forwards_check() -> None:
    # The verify check advertises this exact command, so the two cannot drift: an
    # author who reads the manifest and runs it by hand must get the same behaviour.
    assert routes_argv() == ["npm", "--prefix", "frontend", "run", "routes"]
    assert routes_argv("web", check=True) == [
        "npm",
        "--prefix",
        "web",
        "run",
        "routes",
        "--",
        "--check",
    ]


def test_routes_runs_the_frontend_script_and_returns_its_output(
    tmp_path: pathlib.Path,
) -> None:
    _frontend(tmp_path)
    seen: list[object] = []

    def fake_run(argv: list[str], cwd: pathlib.Path) -> tuple[int, str]:
        seen.append((argv, cwd))
        return 0, "terp routes: wrote src/routes.gen.d.ts\n"

    output = run_routes_command(root=tmp_path, run=fake_run)
    assert output == "terp routes: wrote src/routes.gen.d.ts"
    assert seen == [
        (["npm", "--prefix", "frontend", "run", "routes"], tmp_path.resolve())
    ]


def test_routes_fails_closed_when_the_generator_refuses(tmp_path: pathlib.Path) -> None:
    # A manifest the generator cannot read statically, or a stale table under --check:
    # either way the command must carry the failure out, not swallow it into a success.
    _frontend(tmp_path)

    def refusing_run(argv: list[str], cwd: pathlib.Path) -> tuple[int, str]:
        return (
            1,
            "src/routes.gen.d.ts is stale - the module manifests declare different routes",
        )

    with pytest.raises(SystemExit, match="stale"):
        run_routes_command(root=tmp_path, check=True, run=refusing_run)


def test_routes_refuses_a_project_with_no_frontend(tmp_path: pathlib.Path) -> None:
    # Backend-only repo: say so, instead of handing npm a directory that is not there.
    with pytest.raises(SystemExit, match="no frontend"):
        run_routes_command(root=tmp_path, run=_never_run)
    assert run_routes_command(root=tmp_path, optional=True, run=_never_run).startswith(
        "skipped"
    )


def test_the_drift_check_is_a_noop_until_an_app_adopts_route_types(
    tmp_path: pathlib.Path,
) -> None:
    # The gate half of the same upgrade path, mirroring api-docs-drift's "no-op until the
    # project commits docs/": a green verdict with the hint, never a red gate for a
    # feature the app has not wired. No npm is spawned in either skip.
    from terp.cli.verify import _run_routes_drift

    exit_code, output = _run_routes_drift(tmp_path)
    assert exit_code == 0 and "not applicable" in output

    _frontend(tmp_path, wired=False)
    exit_code, output = _run_routes_drift(tmp_path)
    assert exit_code == 0
    assert "drift check skipped" in output and "terp-routes" in output


def test_cli_routes_dispatch(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(**kwargs: object) -> str:
        captured.update(kwargs)
        return "terp routes: src/routes.gen.d.ts is current"

    monkeypatch.setattr("terp.cli.run_routes_command", fake_run)
    main(["routes", "--root", str(tmp_path), "--frontend-dir", "web", "--check"])

    assert captured == {"root": str(tmp_path), "frontend_dir": "web", "check": True}


def test_an_unadopted_app_is_skipped_with_the_hint_not_failed(
    tmp_path: pathlib.Path,
) -> None:
    # The upgrade path (ADR 0092): route types are opt-in, so an app that merely upgraded
    # the framework must not have `terp dev` or its gate break. The offer is skipped with
    # the two steps that turn it on.
    _frontend(tmp_path, wired=False)
    summary = run_routes_command(root=tmp_path, optional=True, run=_never_run)
    assert "skipped" in summary
    assert '"routes": "terp-routes"' in summary
    assert "routes.gen.d.ts" in summary

    # Asked for explicitly, the same state is an error with the same directive fix.
    with pytest.raises(SystemExit, match="terp-routes"):
        run_routes_command(root=tmp_path, run=_never_run)


def test_dev_preflight_regenerates_the_route_types_beside_the_openapi_document(
    tmp_path: pathlib.Path,
) -> None:
    # Both derived artifacts, one preflight: a route added a minute ago is navigable
    # *and* checked when the dev servers come up.
    _frontend(tmp_path)
    regenerated: list[dict[str, object]] = []

    run_dev_command(
        app_ref="app.main:app",
        root=tmp_path,
        export=lambda *args, **kwargs: tmp_path / "openapi.json",
        regenerate_routes=lambda **kwargs: regenerated.append(kwargs) or "wrote it",
        spawn=lambda command: _DoneProc(),
        supervise=lambda processes: None,
    )

    assert regenerated == [
        {"root": tmp_path.resolve(), "frontend_dir": "frontend", "optional": True}
    ]


def test_dev_preflight_offers_route_types_optionally_so_a_backend_only_repo_is_fine(
    tmp_path: pathlib.Path,
) -> None:
    # No frontend at all: the real command returns a skip rather than raising, which is
    # what `optional=True` buys — exercised here through the real implementation.
    run_dev_command(
        app_ref="app.main:app",
        root=tmp_path,
        export=lambda *args, **kwargs: tmp_path / "openapi.json",
        spawn=lambda command: _DoneProc(),
        supervise=lambda processes: None,
    )


def test_no_preflight_skips_the_route_types_too(tmp_path: pathlib.Path) -> None:
    _frontend(tmp_path)
    regenerated: list[object] = []

    run_dev_command(
        app_ref="app.main:app",
        root=tmp_path,
        preflight=False,
        export=lambda *args, **kwargs: tmp_path / "openapi.json",
        regenerate_routes=lambda **kwargs: regenerated.append(kwargs) or "unreachable",
        spawn=lambda command: _DoneProc(),
        supervise=lambda processes: None,
    )

    assert regenerated == []


def test_an_unreadable_manifest_reads_as_unadopted(tmp_path: pathlib.Path) -> None:
    # A package.json that will not parse cannot be *proof* the app opted in, so the
    # offer is skipped rather than spawning npm against a manifest nobody can read.
    from terp.cli.routes import routes_script_wired

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("{ not json", encoding="utf-8")
    assert routes_script_wired(frontend) is False


def test_the_runner_reports_the_exit_code_and_the_combined_output(
    tmp_path: pathlib.Path,
) -> None:
    # The one place the CLI actually spawns a process. Both streams have to reach the
    # caller: the generator prints its refusal on stderr and its fix hint on stdout,
    # and a message split across two channels would arrive half-missing.
    from terp.cli.routes import _run_npm

    exit_code, output = _run_npm(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
        tmp_path,
    )
    assert exit_code == 0
    assert "out" in output and "err" in output


def test_the_drift_check_needs_an_installed_frontend_before_it_spawns_anything(
    tmp_path: pathlib.Path,
) -> None:
    # Without node_modules the generator dies in a raw Node stack that names neither
    # cause nor fix, so the check names both itself instead of shelling out.
    from terp.cli.verify import _run_routes_drift

    _frontend(tmp_path)
    exit_code, output = _run_routes_drift(tmp_path)
    assert exit_code == 1
    assert "node_modules is missing" in output


def test_the_drift_check_carries_the_generators_verdict_out(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The adopted, installed path: whatever the generator says under --check is the
    # check's verdict, both streams included.
    import subprocess

    from terp.cli.verify import _run_routes_drift

    frontend = _frontend(tmp_path)
    (frontend / "node_modules").mkdir()

    class _Completed:
        returncode = 1
        stdout = "src/routes.gen.d.ts is stale"
        stderr = " - regenerate it"

    seen: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> _Completed:
        seen["argv"] = argv
        seen["cwd"] = kwargs.get("cwd")
        return _Completed()

    monkeypatch.setattr(subprocess, "run", fake_run)
    exit_code, output = _run_routes_drift(tmp_path)
    assert exit_code == 1
    assert output == "src/routes.gen.d.ts is stale - regenerate it"
    assert seen["argv"][1:] == ["--prefix", "frontend", "run", "routes", "--", "--check"]
    assert seen["cwd"] == tmp_path


def test_the_profile_dispatches_the_routes_drift_runner(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The check reaches its own runner rather than being shelled out like an ordinary
    # command -- that dispatch is what makes the no-op-until-adopted verdict possible.
    from terp.cli.verify import _ROUTES_DRIFT, PROFILES

    monkeypatch.setitem(PROFILES, "quick", (_ROUTES_DRIFT,))
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--profile", "quick", "--root", str(tmp_path), "--format", "json"])
    assert excinfo.value.code == 0
    envelope = json.loads(capsys.readouterr().out)
    (check,) = envelope["checks"]
    assert check["ok"] is True
    assert "not applicable" in check["output_tail"]
