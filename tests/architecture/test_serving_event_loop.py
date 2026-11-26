"""Every way Terp serves an app runs on asyncio's own event loop, never uvloop (ADR 0177).

The egress guard holds Python's socket module through audit events. uvloop resolves names and
connects inside libuv, which raises none, so the guard refuses to install beside it and refuses
an ``import uvloop`` after it. uvicorn's default loop, ``auto``, makes exactly that import once it
has imported the app, and ``uvicorn[standard]`` brings uvloop wherever it builds. The guard
refuses the attempt itself, before Python looks for the module, so an app that installs the guard
and is served under ``auto`` starts on no OS at all: not on Linux, where uvloop is installed, and
not on Windows, where it does not exist.

So every uvicorn command the template and the example ship names ``--loop asyncio``, and so does
``terp dev``. The control has two halves, as the shutdown bound has (``test_serving_shutdown.py``):
the commands read as data, with a grep that catches a new one this file never named, and the
template's production command, taken from its image, run with the guard installed. The same
command without the flag runs as well, so the test shows that the flag is what lets the app start.
"""

from __future__ import annotations

import json
import os
import pathlib
import signal
import socket
import subprocess
import sys
import time

import httpx
import pytest

from terp.cli.dev import dev_plan
from tests.architecture.test_serving_shutdown import (
    _INVOCATION,
    _RELOAD_COMPOSE,
    _SEARCH_ROOTS,
    _SEARCH_SUFFIXES,
    _SERVED_IMAGES,
    _api_command,
    _cmd_argv,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_TEMPLATE_PROD_DOCKERFILE = _REPO_ROOT / "template" / "project" / "Dockerfile.prod"

_LOOP = ("--loop", "asyncio")

#: The reference app's workbench compose serves the same way, and the generator writes the
#: template's production image, so both are read here beside the files the shutdown test reads.
_COMPOSES = (*_RELOAD_COMPOSE, _REPO_ROOT / "apps" / "reference" / "overlay" / "docker-compose.yml")
_GREP_ROOTS = (*_SEARCH_ROOTS, _REPO_ROOT / "packages" / "backend" / "arch" / "src")

#: An app that installs the guard in its composition root, as `terp guide capability` says to.
#: On Windows asyncio's own socketpair connects to loopback, so the guard needs loopback declared
#: there before any event loop can be made (the guide says so too); on Linux it needs nothing.
_GUARDED_APP = """\
import sys

from fastapi import FastAPI
from terp.capabilities.egress import EgressGuard, install_egress_guard

install_egress_guard(
    EgressGuard(infrastructure=("127.0.0.1",) if sys.platform == "win32" else ())
)
app = FastAPI()


@app.get("/health/live")
def live() -> dict:
    return {}
"""


def _names_the_loop(argv: list[str] | tuple[str, ...]) -> bool:
    return any(tuple(argv[i : i + 2]) == _LOOP for i in range(len(argv) - 1))


@pytest.mark.parametrize("dockerfile", _SERVED_IMAGES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_served_image_runs_on_asyncio(dockerfile: pathlib.Path) -> None:
    argv = json.loads(_cmd_argv(dockerfile).removeprefix("CMD "))
    assert _names_the_loop(argv), f"{dockerfile}: no --loop asyncio in {argv}"


@pytest.mark.parametrize("compose_path", _COMPOSES, ids=lambda p: p.parent.name)
def test_every_workbench_api_runs_on_asyncio(compose_path: pathlib.Path) -> None:
    command = _api_command(compose_path)
    assert _names_the_loop(command), f"{compose_path}: no --loop asyncio in {command}"


def test_terp_dev_runs_on_asyncio() -> None:
    backend, _ = dev_plan(root=".")
    assert _names_the_loop(backend.argv), backend.argv


def test_no_uvicorn_invocation_anywhere_leaves_the_loop_to_uvicorn() -> None:
    """A new way to serve is caught here, without this file having to name it first."""
    unnamed: list[str] = []
    for search_root in _GREP_ROOTS:
        for path in search_root.rglob("*"):
            if not path.is_file() or path.suffix not in _SEARCH_SUFFIXES:
                continue
            if "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
            ):
                if _INVOCATION.search(line) and '"--loop", "asyncio"' not in line:
                    unnamed.append(f"{path.relative_to(_REPO_ROOT).as_posix()}:{number}")
    assert not unnamed, (
        "these start uvicorn without --loop asyncio, so it tries uvloop and an app that "
        f"installs the egress guard does not start (ADR 0177): {unnamed}"
    )


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _template_production_argv(port: int) -> list[str]:
    """The template image's own CMD, pointed at the guarded app on a local port."""
    argv = json.loads(_cmd_argv(_TEMPLATE_PROD_DOCKERFILE).removeprefix("CMD "))
    assert argv[:2] == ["uvicorn", "app.main:app"], argv
    host, bound = argv.index("--host"), argv.index("--port")
    argv[host + 1], argv[bound + 1] = "127.0.0.1", str(port)
    return [sys.executable, "-m", "uvicorn", "guarded:app", *argv[2:]]


def _start(argv: list[str], cwd: pathlib.Path) -> tuple[subprocess.Popen[bytes], pathlib.Path]:
    (cwd / "guarded.py").write_text(_GUARDED_APP, encoding="utf-8")
    stderr = cwd / "stderr.log"
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    with stderr.open("wb") as err:  # the child keeps its own copy of the handle
        process = subprocess.Popen(  # the template's own command, as data
            argv,
            cwd=cwd,
            env={**os.environ, "PYTHONPATH": str(cwd)},
            stdout=subprocess.DEVNULL,
            stderr=err,
            creationflags=flags,
        )
    return process, stderr


def _stop(process: subprocess.Popen[bytes]) -> None:
    if sys.platform == "win32":
        os.kill(process.pid, signal.CTRL_BREAK_EVENT)
    else:
        process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:  # only a hung server lands here
        process.kill()
        raise


def _serves(argv: list[str], cwd: pathlib.Path, port: int) -> None:
    process, stderr = _start(argv, cwd)
    try:
        deadline = time.monotonic() + 60
        while True:
            assert process.poll() is None, stderr.read_text(encoding="utf-8")
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health/live", timeout=5).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            assert time.monotonic() < deadline, "the guarded app never became live"
            time.sleep(0.2)
    finally:
        if process.poll() is None:
            _stop(process)


def test_the_template_s_production_command_serves_an_app_that_installs_the_guard(
    tmp_path: pathlib.Path,
) -> None:
    port = _free_port()
    _serves(_template_production_argv(port), tmp_path, port)


def test_the_same_command_without_the_flag_is_refused_by_the_guard(tmp_path: pathlib.Path) -> None:
    """The counter-case: with the loop left to uvicorn, the guard refuses the start."""
    argv = _template_production_argv(_free_port())
    at = argv.index("--loop")
    del argv[at : at + 2]
    process, stderr = _start(argv, tmp_path)
    try:
        returncode = process.wait(timeout=60)
    finally:
        if process.poll() is None:
            _stop(process)
    output = stderr.read_text(encoding="utf-8")
    assert returncode != 0, output
    assert "EgressGuardUnsupportedError" in output
    assert "uvloop is being imported" in output


def test_terp_dev_serves_an_app_that_installs_the_guard(tmp_path: pathlib.Path) -> None:
    port = _free_port()
    backend, _ = dev_plan(root=tmp_path, app_ref="guarded:app", port=port)
    _serves(list(backend.argv), tmp_path, port)
