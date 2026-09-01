"""Every way Terp starts an ASGI server bounds its shutdown (ADR 0108).

An app serving a realtime channel has tasks that never end on their own: an SSE or WebSocket
stream closes when its client goes away and not otherwise. uvicorn's ``timeout_graceful_shutdown``
defaults to ``None``, which means *wait for them*, so an unbounded invocation turns one open
browser tab into a reload loop that never restarts and a container that never stops until the
orchestrator kills it.

The bound is a per-invocation argument rather than anything the framework can apply centrally --
uvicorn is started by the app's own compose file, its own image, or ``terp dev``, and none of
those routes through ``create_app``. So the control is this test: enumerate every invocation in
the repository, parsed as data, and require each one to carry the flag. A new way to serve is
caught by :func:`test_no_unbounded_uvicorn_invocation_anywhere`, which greps rather than reads a
list, so adding a site without a bound fails even though this file never named it.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

from terp.cli.dev import SHUTDOWN_TIMEOUT_SECONDS, dev_plan

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

_FLAG = "--timeout-graceful-shutdown"

#: The reload loop pays the wait on every backend edit, so it is bounded tighter than a served
#: process. Both numbers are ADR 0108's; this test pins them so a change is a deliberate one.
_RELOAD_SECONDS = "3"
_SERVED_SECONDS = "8"

_RELOAD_COMPOSE = (
    _REPO_ROOT / "apps" / "example" / "docker-compose.yml",
    _REPO_ROOT / "template" / "project" / "docker-compose.yml.jinja",
)

_SERVED_IMAGES = (
    _REPO_ROOT / "apps" / "example" / "Dockerfile",
    _REPO_ROOT / "apps" / "example" / "Dockerfile.prod",
    _REPO_ROOT / "template" / "project" / "Dockerfile",
    _REPO_ROOT / "template" / "project" / "Dockerfile.prod",
)

#: Where a uvicorn invocation may appear at all. Anything outside this set is either prose or a
#: dependency pin, both of which the grep below tolerates by requiring an actual argv.
_SEARCH_ROOTS = (
    _REPO_ROOT / "apps",
    _REPO_ROOT / "template",
    _REPO_ROOT / "packages" / "backend" / "cli" / "src",
)

_SEARCH_SUFFIXES = {".yml", ".yaml", ".jinja", ".py", ""}

#: An argv that actually starts a server: the module name followed by an app reference, in either
#: the exec-form list of a compose ``command:`` / Dockerfile ``CMD`` or a Python argv tuple.
_INVOCATION = re.compile(r"""["']uvicorn["']\s*,\s*["'][\w.]+:\w+["']""")

#: The template compose is Jinja. Substituting the one interpolation and stripping the wizard's
#: conditional blocks (their default render) lets it parse as YAML without a Jinja engine --
#: the same no-render treatment ``test_compose_workbench.py`` gives it.
_JINJA_IF_BLOCK = re.compile(r"\{%-?\s*if\b.*?%\}.*?\{%-?\s*endif\s*-?%\}", re.DOTALL)


def _api_command(compose_path: pathlib.Path) -> list[str]:
    text = compose_path.read_text(encoding="utf-8").replace("{{ project_slug }}", "app")
    text = _JINJA_IF_BLOCK.sub("", text)
    assert "{%" not in text, f"{compose_path.name}: unstripped Jinja block"
    data = yaml.safe_load(text)
    command = data["services"]["api"]["command"]
    assert isinstance(command, list), (
        f"{compose_path.name}: exec form, not a shell string"
    )
    return command


def _cmd_argv(dockerfile: pathlib.Path) -> str:
    lines = [
        line
        for line in dockerfile.read_text(encoding="utf-8").splitlines()
        if line.startswith("CMD ")
    ]
    assert len(lines) == 1, (
        f"{dockerfile}: expected exactly one CMD, found {len(lines)}"
    )
    return lines[0]


def _bound_seconds(argv: list[str]) -> str:
    assert _FLAG in argv, f"unbounded shutdown: {argv}"
    return argv[argv.index(_FLAG) + 1]


@pytest.mark.parametrize("compose_path", _RELOAD_COMPOSE, ids=lambda p: p.parent.name)
def test_reload_compose_bounds_its_shutdown(compose_path: pathlib.Path) -> None:
    """The workbench ``api`` service reloads, so it bounds the wait tightly."""
    command = _api_command(compose_path)
    assert "--reload" in command, (
        f"{compose_path.name}: the workbench api still reloads"
    )
    assert _bound_seconds(command) == _RELOAD_SECONDS


@pytest.mark.parametrize(
    "dockerfile", _SERVED_IMAGES, ids=lambda p: f"{p.parent.name}/{p.name}"
)
def test_served_image_bounds_its_shutdown(dockerfile: pathlib.Path) -> None:
    """Both images, dev and production, bound the wait under Compose's stop grace."""
    line = _cmd_argv(dockerfile)
    assert _FLAG in line, f"{dockerfile}: unbounded shutdown in {line}"
    seconds = line.split(_FLAG, 1)[1]
    assert f'"{_SERVED_SECONDS}"' in seconds, (
        f"{dockerfile}: expected {_SERVED_SECONDS}s"
    )


def test_terp_dev_bounds_its_shutdown() -> None:
    """``terp dev`` is the one invocation an app cannot edit, so the default carries the bound."""
    backend, _ = dev_plan(root=".")
    assert _FLAG in backend.argv
    assert backend.argv[backend.argv.index(_FLAG) + 1] == str(SHUTDOWN_TIMEOUT_SECONDS)
    assert SHUTDOWN_TIMEOUT_SECONDS == int(_RELOAD_SECONDS)


def test_terp_dev_shutdown_timeout_is_overridable() -> None:
    """The escape is an argument, because the platform's number is not every app's number."""
    backend, _ = dev_plan(root=".", shutdown_timeout=30)
    assert backend.argv[backend.argv.index(_FLAG) + 1] == "30"


@pytest.mark.parametrize("bad", [0, -1])
def test_terp_dev_refuses_a_non_positive_shutdown_timeout(bad: int) -> None:
    """``0`` means "cancel immediately" to uvicorn -- a different decision, so it is not silent."""
    with pytest.raises(ValueError, match="positive number of seconds"):
        dev_plan(root=".", shutdown_timeout=bad)


def test_no_unbounded_uvicorn_invocation_anywhere() -> None:
    """A new way to serve is caught here, without this file having to name it first."""
    unbounded: list[str] = []
    for search_root in _SEARCH_ROOTS:
        for path in search_root.rglob("*"):
            if not path.is_file() or path.suffix not in _SEARCH_SUFFIXES:
                continue
            if "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
            ):
                if _INVOCATION.search(line) and _FLAG not in line:
                    unbounded.append(
                        f"{path.relative_to(_REPO_ROOT).as_posix()}:{number}"
                    )
    assert not unbounded, (
        "these start a server without bounding its shutdown, so a realtime stream holds it "
        f"open forever (ADR 0108): {unbounded}"
    )
