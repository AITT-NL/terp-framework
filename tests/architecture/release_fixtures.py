"""Shared fixtures for the release jobs' tests (ADR 0187 decision 6).

A small generated-state app, committed in a git repository of its own: its declaration (a
database, the migration step and an api), its generator-rendered build files, a uv lock that
pins the toolchain, the template's ignore files and two source roots. Every test starts from
:func:`committed_app` and changes one thing. :class:`Runs` stands in for every program a job
runs, answering by the argument list and recording each call, so a test can say what was run
and, as much to the point, what never was.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from terp.arch.deployment import reader
from terp.arch.deployment.generator import generate
from terp.arch.deployment.tables import published_tables

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "template" / "project"
GOLDEN = pathlib.Path(__file__).with_name("generator_goldens") / "no-frontend" / "deployment.json"
PROJECT = "relapp"
TOOLCHAIN = "0.34.0"

PYPROJECT = f"""\
[project]
name = "{PROJECT}"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = ["terp-cli=={TOOLCHAIN}"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app", "control_plane"]
"""

UV_LOCK = f"""\
version = 1
revision = 3
requires-python = ">=3.13"

[[package]]
name = "{PROJECT}"
version = "0.1.0"
source = {{ editable = "." }}
dependencies = [
    {{ name = "terp-cli" }},
]

[[package]]
name = "terp-cli"
version = "{TOOLCHAIN}"
source = {{ registry = "https://pypi.org/simple" }}
dependencies = [
    {{ name = "terp-arch" }},
    {{ name = "colorama", marker = "sys_platform == 'win32'" }},
]

[[package]]
name = "terp-arch"
version = "{TOOLCHAIN}"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "colorama"
version = "0.4.6"
source = {{ registry = "https://pypi.org/simple" }}
"""


def git(root: pathlib.Path, *args: str) -> str:
    """Run git in *root* as a test commits: a fixed identity, no hooks, the bytes as written."""
    completed = subprocess.run(  # noqa: S603 - fixed argv
        ["git", "-c", "user.email=release@example.invalid", "-c", "user.name=release",
         "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", "-C", str(root), *args],
        capture_output=True, text=True, check=True,
    )
    return completed.stdout.strip()


#: The frontend lock of the app with a web tier: one package, from the public registry.
NPM_LOCK = {"lockfileVersion": 3, "packages": {"": {"name": "frontend"}, "node_modules/react": {
    "version": "19.0.0", "resolved": "https://registry.npmjs.org/react/-/react-19.0.0.tgz"}}}


def app_files(*, web: bool = False) -> dict[str, bytes]:
    """The app's files, path to bytes, its build files the generator's render.

    With *web*, the template's own seed (a web tier beside the api) and a frontend lock.
    """
    if web:
        from tests.architecture.deployment_fixtures import seed

        raw = seed("generated")
    else:
        raw = json.loads(GOLDEN.read_text(encoding="utf-8"))
    tables = published_tables()
    declared, findings = reader.read(raw, tables.datastores, tables.system_packages)
    assert findings == [] and declared is not None
    rendered, refused = generate(declared, PROJECT, tables=tables, frontend_lock=web)
    assert refused == []
    files: dict[str, bytes] = {
        "deployment.json": json.dumps(raw, indent=2).encode() if web else GOLDEN.read_bytes(),
        "pyproject.toml": PYPROJECT.encode(),
        "uv.lock": UV_LOCK.encode(),
        ".gitignore": (TEMPLATE / ".gitignore").read_bytes(),
        ".dockerignore": (TEMPLATE / ".dockerignore").read_bytes(),
        "app/__init__.py": b"",
        "app/main.py": b'raise RuntimeError("the app was imported")\n',
        "app/modules/__init__.py": b"",
        "control_plane/__init__.py": b"control_plane = None\n",
        "tests/test_app.py": b"def test_nothing():\n    pass\n",
    }
    if web:
        files["frontend/package.json"] = b'{"name": "frontend", "private": true}\n'
        files["frontend/package-lock.json"] = json.dumps(NPM_LOCK, indent=2).encode()
    files.update(rendered)
    return files


def committed_app(root: pathlib.Path, files: dict[str, bytes] | None = None) -> str:
    """Write *files* (the app's by default) into a fresh repository at *root*; the commit."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    for path, data in (files if files is not None else app_files()).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "release fixture")
    return git(root, "rev-parse", "HEAD")


@dataclass
class Runs:
    """A stand-in for :func:`terp.cli.release._common.run`, answering by argument prefix."""

    answers: list[tuple[tuple[str, ...], Callable[[list[str], bytes | None], tuple[int, bytes, bytes]]]] = field(default_factory=list)
    calls: list[list[str]] = field(default_factory=list)
    #: The environment each answered call was given (``None``: the caller's own).
    envs: list[dict[str, str] | None] = field(default_factory=list)
    real: Callable[..., Any] | None = None

    def on(self, *prefix: str, code: int = 0, out: bytes = b"", err: bytes = b"",
           then: Callable[[list[str], bytes | None], tuple[int, bytes, bytes]] | None = None) -> Runs:
        self.answers.insert(0, (prefix, then or (lambda argv, stdin: (code, out, err))))
        return self

    def __call__(self, argv, *, cwd=None, env=None, stdin=None):  # type: ignore[no-untyped-def]
        argv = list(argv)
        for prefix, answer in self.answers:
            if tuple(argv[: len(prefix)]) == prefix:
                self.calls.append(argv)
                self.envs.append(None if env is None else dict(env))
                code, out, err = answer(argv, stdin)
                return subprocess.CompletedProcess(argv, code, out, err)
        if self.real is not None:
            return self.real(argv, cwd=cwd, env=env, stdin=stdin)
        raise AssertionError(f"no answer for {argv}")

    def ran(self, *prefix: str) -> list[list[str]]:
        return [call for call in self.calls if tuple(call[: len(prefix)]) == prefix]


__all__ = ["PROJECT", "Runs", "TOOLCHAIN", "app_files", "committed_app", "git"]
