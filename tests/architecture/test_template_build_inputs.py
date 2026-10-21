"""What the template's images are built from: the committed locks, in layers, and no secret.

Three properties of every generated app's production build, held here because each one
fails silently where it matters. No Docker is needed: the files are read as text, the way
``test_prod_profile.py`` reads them.

**The locks are the install.** The backend image installed the app wheel with ``uv pip
install``, which ignores ``uv.lock`` and resolves every terp-* and third-party package from
the index at build time, and the frontend image ran ``npm install``, which rewrites a lock
that disagrees with ``package.json`` where ``npm ci`` refuses. So an image could ship
versions the gate never ran and the dependency audit never read. Both images now install
exactly the committed lock (``uv sync --locked --no-dev``, ``npm ci``), the ASGI server and
the database driver are runtime dependencies so the lock pins them too, and the template's
CI installs the same way.

**Layers in the order their inputs change.** Both images copied the whole checkout before
installing anything, so every edit to the app re-ran every install. The manifests and locks
come first now, the install from them is a layer of its own, and the source comes last; the
web image copies nothing from outside ``frontend/`` but the vendored tarballs. Release
builds carry no BuildKit cache mount, so a release never reads a cache a development build
wrote.

**Nothing a commit may not hold reaches an image.** The template's ``.dockerignore`` named
``.env`` and ``.app.env`` at the root only. ``.gitignore`` excludes ``.app.<service>.env``,
``.env.local`` and every one of them at any depth, so a ``COPY . .`` could bake in exactly
the per-service credentials file the gitignore line exists for. The two files are held to
each other by what they match, path by path.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PROJECT = _REPO_ROOT / "template" / "project"
_BACKEND = _PROJECT / "Dockerfile.prod"
_WEB = _PROJECT / "frontend" / "Dockerfile.prod"
_PYPROJECT = _PROJECT / "pyproject.toml.jinja"
_CI = _PROJECT / ".github" / "workflows" / "ci.yml.jinja"
_GITIGNORE = _PROJECT / ".gitignore"
_DOCKERIGNORE = _PROJECT / ".dockerignore"

#: .gitignore patterns an image may hold: generated from the app's own source, they carry
#: nothing the source does not, and a build may one day want them. Every other pattern in
#: .gitignore must exclude the same paths from the build context.
_GENERATED_NOT_SECRET = frozenset({"/openapi.json", "frontend/src/api/"})


def _instructions(dockerfile: pathlib.Path) -> list[str]:
    """The Dockerfile's instructions, one string each, continuation lines joined."""
    joined = re.sub(r"\\\n\s*", " ", dockerfile.read_text(encoding="utf-8"))
    return [
        line.strip()
        for line in joined.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _index(instructions: list[str], needle: str) -> int:
    matches = [i for i, line in enumerate(instructions) if needle in line]
    assert len(matches) == 1, f"expected one instruction with {needle!r}, found {len(matches)}"
    return matches[0]


def _stages(instructions: list[str]) -> dict[str, list[str]]:
    """Each stage's instructions, by its ``AS`` name (the unnamed last one is ``runtime``)."""
    stages: dict[str, list[str]] = {}
    current: list[str] = []
    for line in instructions:
        if line.startswith("FROM "):
            name = line.split(" AS ")[1] if " AS " in line else "runtime"
            current = stages.setdefault(name, [])
        current.append(line)
    return stages


# --------------------------------------------------------------------------- #
# the locks are the install
# --------------------------------------------------------------------------- #
def test_the_backend_image_installs_exactly_the_lock_and_refuses_a_stale_one() -> None:
    instructions = _instructions(_BACKEND)
    sync = _index(instructions, "uv sync")
    assert "--locked" in instructions[sync], "a lock that disagrees must refuse, not re-resolve"
    assert "--no-dev" in instructions[sync], "the dev group never reaches the production image"
    installs = [line for line in instructions if "uv pip install" in line]
    assert installs and all("--no-deps" in line for line in installs), (
        "after the locked sync, a `uv pip install` may only add the app's own wheel: one that "
        "resolves dependencies installs versions the lock did not choose"
    )
    assert not any("--find-links" in line or "--index" in line for line in instructions), (
        "the lock names where each package comes from; a build-time index or find-links "
        "is a second answer"
    )


def test_the_backend_image_ships_its_bytecode_compiled_and_deterministic() -> None:
    # ADR 0187, from a measurement: the image held no .pyc at all, its user cannot write
    # the environment, and so every process start compiled the platform again - importing
    # the app took 11.5 s against 2 s with bytecode. Both parts are compiled where they are
    # installed, each in its own layer, with checked-hash bytecode (PEP 552), which records
    # a hash of the source rather than an mtime, so the same lock compiles to the same bytes.
    stages = _stages(_instructions(_BACKEND))
    deps, runtime = stages["deps"], stages["runtime"]
    compile_deps = _index(deps, "compileall")
    assert _index(deps, "uv sync") < compile_deps
    assert deps[compile_deps] == (
        "RUN /srv/.venv/bin/python -m compileall -q -j 0 --invalidation-mode checked-hash "
        "/srv/.venv/lib"
    )
    compile_app = _index(runtime, "compileall")
    assert runtime[compile_app] == (
        "RUN python -m compileall -q -j 0 --invalidation-mode checked-hash app control_plane"
    )
    assert _index(runtime, "COPY control_plane") < compile_app < _index(runtime, "USER appuser")
    assert "PYTHONDONTWRITEBYTECODE=1" in runtime[_index(runtime, "PYTHONDONTWRITEBYTECODE")], (
        "nothing is written at run time: what is not compiled at build is compiled in memory"
    )


def test_the_backend_image_carries_no_healthcheck_a_worker_could_inherit() -> None:
    # Every backend unit runs this image and only an api serves HTTP. With a probe baked in,
    # a worker turned unhealthy and `docker compose up --wait` failed every deploy of a
    # profile that ran one (ADR 0187); the profile probes each api unit instead.
    assert not any(line.startswith("HEALTHCHECK") for line in _instructions(_BACKEND))


def test_the_web_image_installs_exactly_the_lock() -> None:
    instructions = _instructions(_WEB)
    assert any(line.startswith("RUN npm ci") for line in instructions)
    assert not any("npm install" in line or "npm i " in line for line in instructions), (
        "`npm install` rewrites a lock that disagrees with package.json; `npm ci` refuses it"
    )


def _requirements(block: str) -> list[str]:
    return re.findall(r'^\s*"([^"]+)",?\s*$', block, re.MULTILINE)


def test_the_server_and_the_driver_are_locked_runtime_dependencies() -> None:
    text = _PYPROJECT.read_text(encoding="utf-8")
    runtime = text[text.index("\ndependencies = [\n") :]
    runtime = runtime[: runtime.index("\n]\n")]
    # Outside every {% if %} block, so every rendered app's lock pins them.
    unconditional = re.sub(r"\{%-? if .*?\{%-? endif %\}", "", runtime, flags=re.DOTALL)
    declared = _requirements(unconditional)
    assert "uvicorn[standard]>=0.30" in declared, "the image serves with the locked server"
    assert "psycopg[binary]>=3.2" in declared, "the image connects with the locked driver"
    dev = re.search(r"^dev = \[(.*)\]$", text, re.MULTILINE)
    assert dev is not None
    assert "uvicorn" not in dev.group(1) and "psycopg" not in dev.group(1), (
        "a second, dev-group requirement on the server or the driver is a second answer "
        "to which version the app runs"
    )
    assert "install their own pinned server" not in text, (
        "the images install the lock; nothing of their own"
    )


def test_deptry_is_told_why_the_server_and_the_driver_are_never_imported() -> None:
    text = _PYPROJECT.read_text(encoding="utf-8")
    exempt = re.search(r"^DEP002 = (\[.*\])$", text, re.MULTILINE)
    assert exempt is not None, (
        "uvicorn and psycopg are declared and never imported, so a generated app's deptry "
        "(blocking in the full profile) reports DEP002 for both unless the template says why"
    )
    assert set(yaml.safe_load(exempt.group(1))) == {"uvicorn", "psycopg"}


def _jobs() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))["jobs"]


def test_the_template_ci_installs_the_same_locks() -> None:
    runs = {
        name: [str(step.get("run", "")).strip() for step in job["steps"]]
        for name, job in _jobs().items()
    }
    for name, commands in runs.items():
        syncs = [command for command in commands if command.startswith("uv sync")]
        assert syncs, f"job {name} installs the backend"
        assert all(command == "uv sync --locked" for command in syncs), (
            f"job {name} runs {syncs}: an unlocked sync re-resolves a stale lock into a set "
            "nobody committed, and the gate then proves a different set than the image ships"
        )
    gate = runs["gate"]
    assert "npm --prefix frontend ci" in gate
    assert "npm --prefix frontend install" not in gate


# --------------------------------------------------------------------------- #
# layers in the order their inputs change
# --------------------------------------------------------------------------- #
def test_the_backend_image_installs_its_dependencies_before_it_copies_the_app() -> None:
    stages = _stages(_instructions(_BACKEND))
    deps = stages["deps"]
    assert "COPY pyproject.toml uv.lock ./" in deps, "the manifest and the lock, and nothing else"
    assert not any(line.startswith("COPY . ") for line in deps), (
        "the dependency stage copies only what decides the dependencies, so an edit to the "
        "app never re-runs the install"
    )
    assert deps.index("COPY pyproject.toml uv.lock ./") < _index(deps, "uv sync")
    assert "--no-install-project" in deps[_index(deps, "uv sync")]

    runtime = stages["runtime"]
    venv = _index(runtime, "COPY --from=deps /srv/.venv")
    app = _index(runtime, "uv pip install")
    assert venv < app < _index(runtime, "COPY app app") < _index(runtime, "COPY control_plane"), (
        "the runtime image is the base, then the locked dependencies, then the app"
    )
    assert _index(runtime, "useradd") < venv, (
        "a layer that does not depend on the app sits below the ones that do"
    )


def test_the_web_image_installs_from_its_lock_before_it_copies_its_source() -> None:
    build = _stages(_instructions(_WEB))["build"]
    manifests = _index(build, "COPY frontend/package.json frontend/package-lock.json ./")
    install = _index(build, "RUN npm ci")
    source = _index(build, "COPY frontend/ ./")
    assert manifests < install < source < _index(build, "npm run build")


def test_no_package_s_lifecycle_script_runs_in_the_web_image() -> None:
    # ADR 0187, measured on a template render and the reference app before it was made: of
    # the 251 packages their locks hold, only fsevents declares an install script, and it is
    # macOS-only and never installed on Linux; the app declares no pre- or post-script; the
    # bundle built with scripts off and without the network is byte for byte the one built
    # with them. So the install runs no hook, and the build reads nothing but what `npm ci`
    # installed and the source.
    build = _stages(_instructions(_WEB))["build"]
    assert build[_index(build, "RUN npm ci")] == "RUN npm ci --ignore-scripts --no-audit --no-fund"
    assert build[_index(build, "npm run build")] == (
        "RUN --network=none npm run build --ignore-scripts"
    )


def test_the_web_image_copies_nothing_from_outside_the_frontend() -> None:
    copies = [
        line.split()[1:-1]
        for line in _instructions(_WEB)
        if line.startswith("COPY ") and "--from=" not in line
    ]
    sources = [source for sources in copies for source in sources]
    assert sources, "the web image copies its inputs"
    outside = [s for s in sources if not s.startswith("frontend/") and s != ".terp-dis[t]/np[m]"]
    assert not outside, f"the web image copies {outside}: a backend edit would rebuild it"


@pytest.mark.parametrize("dockerfile", [_BACKEND, _WEB], ids=["backend", "web"])
def test_a_production_image_mounts_no_build_cache(dockerfile: pathlib.Path) -> None:
    # A cache mount outlives the build that wrote it and is shared by every build on the
    # builder, so a development build could leave in it what a release build then installs.
    assert "type=cache" not in dockerfile.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("dockerfile", "pattern", "target"),
    [
        (_BACKEND, ".terp-dis[t]/wheel[s]", ".terp-dist/wheels/"),
        (_WEB, ".terp-dis[t]/np[m]", "/app/.terp-dist/npm/"),
    ],
    ids=["backend", "web"],
)
def test_vendored_packages_are_copied_only_when_a_checkout_has_them(
    dockerfile: pathlib.Path, pattern: str, target: str
) -> None:
    # A plain COPY of .terp-dist/ fails the build of every checkout without one, which is
    # every checkout once the packages are published; the bracket makes it a pattern that
    # may match nothing. Each image copies only its own half.
    assert f"COPY {pattern} {target}" in _instructions(dockerfile)


# --------------------------------------------------------------------------- #
# nothing a commit may not hold reaches an image
# --------------------------------------------------------------------------- #
def _glob(pattern: str) -> str:
    """A glob as a regex over ``/``-separated paths, the way git and Docker both read it."""
    out = ""
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out += "(?:.*/)?"
            index += 3
        elif pattern.startswith("**", index):
            out += ".*"
            index += 2
        elif pattern[index] == "*":
            out += "[^/]*"
            index += 1
        elif pattern[index] == "?":
            out += "[^/]"
            index += 1
        elif pattern[index] == "[":
            end = pattern.index("]", index)
            out += pattern[index : end + 1]
            index = end + 1
        else:
            out += re.escape(pattern[index])
            index += 1
    return out


def _prefixes(path: str) -> list[str]:
    """*path* and every directory above it: excluding a directory excludes what it holds."""
    parts = path.split("/")
    return ["/".join(parts[: count + 1]) for count in range(len(parts))]


def _patterns(path: pathlib.Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _git_ignores(path: str, patterns: list[str]) -> bool:
    """Whether git ignores *path* (a file) under *patterns*: the last match decides."""
    ignored = False
    for raw in patterns:
        negated = raw.startswith("!")
        pattern = raw.removeprefix("!")
        directory_only = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        anchored = "/" in pattern
        regex = re.compile(_glob(pattern.lstrip("/")))
        candidates = _prefixes(path)[:-1] if directory_only else _prefixes(path)
        if anchored:
            hit = any(regex.fullmatch(candidate) for candidate in candidates)
        else:
            hit = any(regex.fullmatch(candidate.rsplit("/", 1)[-1]) for candidate in candidates)
        if hit:
            ignored = not negated
    return ignored


def _docker_ignores(path: str, patterns: list[str]) -> bool:
    """Whether Docker leaves *path* out of the context: matched from the root, last wins."""
    ignored = False
    for raw in patterns:
        negated = raw.startswith("!")
        regex = re.compile(_glob(raw.removeprefix("!").lstrip("/")))
        if any(regex.fullmatch(candidate) for candidate in _prefixes(path)):
            ignored = not negated
    return ignored


def _concrete(pattern: str) -> str:
    """One path *pattern* matches: each wildcard replaced by a character it accepts."""
    return re.sub(r"\[(.)[^\]]*\]", r"\1", pattern).replace("*", "x").replace("?", "x")


def _samples(pattern: str) -> list[str]:
    """Files that *pattern* ignores: at the root and, for an unanchored one, deeper."""
    body = _concrete(pattern.rstrip("/"))
    leaf = f"{body.lstrip('/')}/held" if pattern.endswith("/") else body.lstrip("/")
    if "/" in pattern.rstrip("/"):
        return [leaf]
    return [leaf, f"frontend/{leaf}", f"app/modules/notes/{leaf}"]


def _secret_bearing() -> list[str]:
    return [
        pattern
        for pattern in _patterns(_GITIGNORE)
        if not pattern.startswith("!") and pattern not in _GENERATED_NOT_SECRET
    ]


def test_every_path_the_gitignore_keeps_out_of_a_commit_stays_out_of_an_image() -> None:
    git = _patterns(_GITIGNORE)
    docker = _patterns(_DOCKERIGNORE)
    assert set(_GENERATED_NOT_SECRET) <= set(git), (
        "an exemption names a pattern .gitignore no longer has; drop it"
    )
    leaks: list[str] = []
    for pattern in _secret_bearing():
        for sample in _samples(pattern):
            assert _git_ignores(sample, git), f"{sample!r} should be a path {pattern!r} ignores"
            if not _docker_ignores(sample, docker):
                leaks.append(f"{sample} (.gitignore {pattern})")
    assert not leaks, (
        "template/project/.dockerignore lets into the build context what .gitignore keeps out "
        f"of a commit: {leaks}. A `COPY . .` bakes it into a layer. Add the pattern to "
        ".dockerignore, written `**/<pattern>` where git's is unanchored."
    )


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "frontend/.env.production",
        ".app.env",
        ".app.worker.env",
        "dev.db",
        "dev.db-wal",
        "var/files/2026/upload.pdf",
        "frontend/node_modules/react/index.js",
        "conformance/playwright-report/index.html",
    ],
)
def test_the_files_that_have_leaked_before_are_out_of_the_context(path: str) -> None:
    # The cases by name, beside the derived check above: the per-service render the old
    # file missed, a Vite env file below the root, a local database's write-ahead log, and
    # an upload stored outside Docker.
    assert _docker_ignores(path, _patterns(_DOCKERIGNORE)), path


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "uv.lock",
        "app/main.py",
        "control_plane/__init__.py",
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/src/main.tsx",
        "frontend/nginx.conf",
        ".terp-dist/wheels/terp_core-1.0.0-py3-none-any.whl",
        ".terp-dist/npm/terpjs-contract-1.0.0.tgz",
        ".env.example",
        ".app.env.example",
    ],
)
def test_what_the_images_are_built_from_stays_in_the_context(path: str) -> None:
    assert not _docker_ignores(path, _patterns(_DOCKERIGNORE)), (
        f"{path} is an input of an image, and .dockerignore leaves it out"
    )


@pytest.mark.parametrize(
    ("path", "git", "docker"),
    [
        ("frontend/.env.local", True, True),
        ("deep/dir/.env", True, True),
        (".env.example", False, False),
        ("frontend/dist/index.js", True, True),
        ("app/frontend/dist/index.js", False, True),
        ("var/files/a", True, True),
        ("app/var/files/a", False, False),
        ("node_modules/a", True, True),
        ("frontend/coverage/index.html", True, True),
        ("openapi.json", True, False),
    ],
)
def test_the_two_readers_read_the_files_the_way_git_and_docker_do(
    path: str, git: bool, docker: bool
) -> None:
    # The matchers above decide the drift check, so they are held to known answers: git's
    # unanchored patterns match at any depth and its anchored ones from the root; Docker
    # matches every pattern from the root, `**/` at any depth, and a directory's match
    # takes what is inside it.
    assert _git_ignores(path, _patterns(_GITIGNORE)) is git
    assert _docker_ignores(path, _patterns(_DOCKERIGNORE)) is docker


def test_the_framework_context_keeps_rendered_env_files_out_too() -> None:
    # The example app's images build from this repository's root, so the root ignore file
    # carries the same secret-bearing names at any depth.
    root = _patterns(_REPO_ROOT / ".dockerignore")
    for path in (".env", "apps/example/.env", "apps/example/.app.env", "apps/example/.app.worker.env"):
        assert _docker_ignores(path, root), path
    assert not _docker_ignores("apps/example/.env.example", root)
