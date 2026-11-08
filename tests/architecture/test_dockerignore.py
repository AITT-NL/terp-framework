"""``.dockerignore`` is read the way Docker reads it (ADR 0187 decision 1).

The generated state's check asks whether an environment file stays out of a build context,
so its matcher is held to Docker's semantics case by case, and then to Docker itself: a build
that copies the whole context into an empty image and exports it shows exactly what the
builder let in, which the matcher must predict file for file. That build needs a running
engine, not only a client: without one the test skips, and where ``TERP_REQUIRE_DOCKER_ENGINE``
is set, as the jobs that run this suite in CI set it, the skip is a failure.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

import pytest
import yaml

from terp.arch.deployment import dockerignore

_REPO = pathlib.Path(__file__).resolve().parents[2]

#: Turns this module's skip into a failure, the pattern of ``TERP_REQUIRE_POSTGRES_LANE`` and
#: ``TERP_REQUIRE_RELEASE_LANE``: the CI jobs that run the suite on a runner with an engine set
#: it, so an engine missing there fails the job instead of passing it green.
REQUIRE_ENV = "TERP_REQUIRE_DOCKER_ENGINE"

#: Every CI step that runs this suite, by workflow file and step name.
_SUITE_STEPS = (
    ("ci.yml", "Run the gate (tests + arch rules + 100% coverage)"),
    ("ci.yml", "Run the suite on the oldest supported interpreter"),
    ("release.yml", "Run the gate"),
)


def _excluded(path: str, text: str) -> bool:
    patterns, unreadable = dockerignore.parse(text)
    assert unreadable == []
    return dockerignore.excluded(path, patterns)


@pytest.mark.parametrize(
    ("patterns", "path", "left_out"),
    [
        (".env", ".env", True),
        (".env", "frontend/.env", False),  # unlike git: rooted at the context
        ("**/.env", "frontend/.env", True),
        ("**/.env", ".env", True),  # `**/` also matches no directory at all
        ("/.env", ".env", True),  # a leading slash is the context root
        ("./.env", ".env", True),
        (".app.*.env", ".app.worker.env", True),
        (".app.*.env", ".app.env", False),
        ("*.env", "app/.app.env", False),  # `*` never crosses a `/`
        ("app/**", "app/deep/x.py", True),
        ("app/", "app/main.py", True),  # a directory takes what it holds
        ("node_modules", "frontend/node_modules/x", False),
        ("**/node_modules", "frontend/node_modules/x/y.js", True),
        ("?.env", "a.env", True),
        ("?.env", "ab.env", False),
        ("[ab].env", "b.env", True),
        ("[^ab].env", "b.env", False),
        ("[^ab].env", "c.env", True),
        ("[a-c].env", "b.env", True),
        ("[]].env", "].env", True),
        (r"\*.env", "*.env", True),
        (r"\*.env", "a.env", False),
        (r"[\]].env", "].env", True),
        ("# .env", ".env", False),  # a comment
        ("  .env  ", ".env", True),  # trimmed
        ("*\n!.env.example", ".env.example", False),  # the last match decides
        (".env*\n!.env.example\n.env.example", ".env.example", True),
        ("**/.env*\n!**/.env.example", "frontend/.env.example", False),
        ("var\n!var/keep", "var/keep", False),
        ("a//b/", "a/b/c", True),
        ("", ".env", False),
        ("[^]a].env", "b.env", True),
        ("a^b", "a^b", True),
    ],
)
def test_a_pattern_means_what_it_means_to_docker(patterns: str, path: str, left_out: bool) -> None:
    assert _excluded(path, patterns) is left_out


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("[unclosed", "a character class that never closes"),
        ("[a\\", "a character class that never closes"),
        ("trailing\\", "a trailing backslash escapes nothing"),
    ],
)
def test_a_pattern_docker_cannot_read_is_reported_never_guessed(text: str, reason: str) -> None:
    patterns, unreadable = dockerignore.parse(f"# first\n{text}\n.env\n")
    assert [(bad.line, bad.text, bad.reason) for bad in unreadable] == [(2, text, reason)]
    assert len(patterns) == 1, "the readable lines still apply"


def test_the_template_s_file_leaves_every_environment_file_out() -> None:
    text = (_REPO / "template" / "project" / ".dockerignore").read_text(encoding="utf-8")
    for path in (".env", ".app.env", ".app.api.env", ".app.migrate.env", "frontend/.env.local"):
        assert _excluded(path, text), path
    for path in ("pyproject.toml", "uv.lock", "app/main.py", ".app.env.example", ".env.example"):
        assert not _excluded(path, text), path


#: A context that exercises every rule above at once, with a pattern set to match it.
_CONTEXT = [
    ".env", ".env.example", ".app.env", ".app.api.env", "frontend/.env", "frontend/.env.example",
    "frontend/node_modules/a/index.js", "node_modules/b.js", "app/main.py", "app/var/files/x",
    "var/files/x", "var/keep", "a.env", "ab.env", "b.env", "c.env", "].env", "docs/a/b/c.md",
    "Dockerfile", "src/one.py", "src/two.txt",
]
_PATTERNS = """
# environment files, at any depth, but the examples
**/.env
**/.env.*
!**/.env.example
**/.app.env
**/.app.*.env
**/node_modules
var
!var/keep
?.env
[^c].env
docs/**/*.md
src/*.txt
"""


def _docker_build_output() -> tuple[list[str] | None, str]:
    """The docker client that can build here, or ``None`` and what is missing.

    The engine is asked, not the client: ``docker buildx version`` answers without one.
    """
    docker = shutil.which("docker")
    if docker is None:
        return None, "no docker client"
    for argv, what in (
        (["info", "--format", "{{.ServerVersion}}"], "no running Docker engine"),
        (["buildx", "version"], "no docker buildx"),
    ):
        if subprocess.run([docker, *argv], capture_output=True, check=False).returncode != 0:
            return None, what
    return [docker], ""


def _docker_or_skip() -> list[str]:
    docker, missing = _docker_build_output()
    if docker is None:
        if os.environ.get(REQUIRE_ENV):
            pytest.fail(f"{missing} here, and {REQUIRE_ENV} is set: this job declared that it builds with Docker")
        pytest.skip(f"{missing} here; CI's runners carry an engine and set {REQUIRE_ENV}")
    return docker


def test_the_matcher_predicts_what_docker_s_builder_lets_into_a_context(tmp_path) -> None:
    docker = _docker_or_skip()
    context = tmp_path / "context"
    for name in _CONTEXT:
        (context / name).parent.mkdir(parents=True, exist_ok=True)
        (context / name).write_text(name, encoding="utf-8")
    (context / ".dockerignore").write_text(_PATTERNS, encoding="utf-8")
    (context / "Dockerfile").write_text("FROM scratch\nCOPY . /\n", encoding="utf-8")
    out = tmp_path / "out"
    run = subprocess.run(
        [*docker, "build", "-q", "-o", f"type=local,dest={out}", str(context)],
        capture_output=True, text=True, check=False,
    )
    assert run.returncode == 0, run.stderr
    let_in = sorted(path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file())
    patterns, unreadable = dockerignore.parse(_PATTERNS)
    assert unreadable == []
    predicted = sorted(
        name for name in [*_CONTEXT, ".dockerignore"] if not dockerignore.excluded(name, patterns)
    )
    assert let_in == predicted


def _fake_docker(directory: pathlib.Path, engine: bool, buildx: bool) -> None:
    """A docker client on PATH whose ``info`` and ``buildx`` answer as told."""
    script = directory / "docker"
    script.write_text(
        "#!/bin/sh\n"
        f'[ "$1" = info ] && exit {0 if engine else 1}\n'
        f'[ "$1" = buildx ] && exit {0 if buildx else 1}\n'
        "exit 2\n",
        encoding="utf-8",
    )
    script.chmod(0o755)


@pytest.mark.skipif(os.name != "posix", reason="the stand-in client is a shell script")
def test_a_client_without_an_engine_skips_and_fails_where_an_engine_is_required(tmp_path, monkeypatch) -> None:
    _fake_docker(tmp_path, engine=False, buildx=True)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv(REQUIRE_ENV, raising=False)
    assert _docker_build_output() == (None, "no running Docker engine"), "buildx answers without an engine"
    with pytest.raises(pytest.skip.Exception, match="no running Docker engine here"):
        _docker_or_skip()
    monkeypatch.setenv(REQUIRE_ENV, "1")
    with pytest.raises(pytest.fail.Exception, match=f"{REQUIRE_ENV} is set"):
        _docker_or_skip()
    _fake_docker(tmp_path, engine=True, buildx=False)
    assert _docker_build_output() == (None, "no docker buildx")
    _fake_docker(tmp_path, engine=True, buildx=True)
    assert _docker_or_skip() == [str(tmp_path / "docker")]
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    assert _docker_build_output() == (None, "no docker client")


def test_every_ci_step_that_runs_the_suite_requires_the_engine() -> None:
    for workflow, name in _SUITE_STEPS:
        jobs = yaml.safe_load((_REPO / ".github" / "workflows" / workflow).read_text(encoding="utf-8"))["jobs"]
        steps = [step for job in jobs.values() for step in job.get("steps", ()) if step.get("name") == name]
        assert len(steps) == 1, f"{workflow} has no single step named {name!r}"
        assert steps[0].get("env", {}).get(REQUIRE_ENV) == "1", f"{workflow}: {name!r} must set {REQUIRE_ENV}"
        assert "pytest" in steps[0]["run"]
