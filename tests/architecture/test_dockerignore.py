"""``.dockerignore`` is read the way Docker reads it (ADR 0187 decision 1).

The generated state's check asks whether an environment file stays out of a build context,
so its matcher is held to Docker's semantics case by case, and then to Docker itself: a build
that copies the whole context into an empty image and exports it shows exactly what the
builder let in, which the matcher must predict file for file.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

from terp.arch.deployment import dockerignore

_REPO = pathlib.Path(__file__).resolve().parents[2]


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


def _docker_build_output() -> list[str] | None:
    docker = shutil.which("docker")
    if docker is None:
        return None
    probe = subprocess.run([docker, "buildx", "version"], capture_output=True, check=False)  # noqa: S603
    return [docker] if probe.returncode == 0 else None


def test_the_matcher_predicts_what_docker_s_builder_lets_into_a_context(tmp_path) -> None:
    docker = _docker_build_output()
    if docker is None:
        pytest.skip("no docker buildx here; CI's runners carry it")
    context = tmp_path / "context"
    for name in _CONTEXT:
        (context / name).parent.mkdir(parents=True, exist_ok=True)
        (context / name).write_text(name, encoding="utf-8")
    (context / ".dockerignore").write_text(_PATTERNS, encoding="utf-8")
    (context / "Dockerfile").write_text("FROM scratch\nCOPY . /\n", encoding="utf-8")
    out = tmp_path / "out"
    run = subprocess.run(  # noqa: S603
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
