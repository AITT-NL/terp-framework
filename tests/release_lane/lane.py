"""The release lane's machinery: a job-local registry and index, two framework versions, the app.

ADR 0187 decision 8's sixth pull request proves ``terp release`` and ``terp promote`` on a real
Docker engine. Everything the lane gives the engine is named with :func:`prefix`, so a lane run
on a shared engine never touches what else runs there and leaves nothing it cannot find again:
its containers, its volumes, its builders, its registry paths, the app's project name (which
names the images a promotion tags) and the compose project it deploys into.

Where the job-local services listen, measured on Docker Desktop and true on Linux: a container
published on an explicitly chosen loopback port (``-p 127.0.0.1:<port>:<port>``) is reachable
from this process, from BuildKit's build steps on the engine's host network (where ``terp
release build --registry-http`` puts its builder) and from the engine itself, at one and the
same address. An ephemeral port (``-p 127.0.0.1::5000``) is reachable from this process only on
Linux: on Docker Desktop the engine's host network is the VM's, where an ephemeral mapping is not
bound. One address matters, because ``uv.lock`` and ``frontend/package-lock.json`` record the
index's URLs and the build reads them back.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import time
import tomllib
import urllib.request
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "packages" / "backend"

#: Turns the lane's skip into a failure: the CI job that runs the lane sets it, so an engine
#: that is not there fails the job instead of passing it green (the PostgreSQL lane's pattern,
#: ``TERP_REQUIRE_POSTGRES_LANE``).
REQUIRE_ENV = "TERP_REQUIRE_RELEASE_LANE"

#: What every name the lane gives the engine starts with; a run on a shared engine can set its
#: own. Lower case, digits and '-', because it starts a compose project and an image name.
PREFIX_ENV = "TERP_RELEASE_LANE_PREFIX"
DEFAULT_PREFIX = "release-lane-"

#: The job-local registry: registry:2, by the image index digest
#: ``docker buildx imagetools inspect registry:2`` named on 2026-10-29.
REGISTRY_IMAGE = "registry@sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373"

#: The frontend packages the reference app's web image installs, packed from this tree.
NPM_WORKSPACES = ("@terpjs/contract", "@terpjs/react-core", "@terpjs/eslint-boundaries")


def prefix() -> str:
    """The lane's name prefix, refused when it could not start a compose project or an image."""
    value = os.environ.get(PREFIX_ENV, DEFAULT_PREFIX)
    if re.fullmatch(r"[a-z][a-z0-9-]{0,30}-", value) is None:
        raise ValueError(f"{PREFIX_ENV}={value!r}: lower case letters, digits and '-', ending in '-'")
    return value


def unavailable(reason: str) -> None:
    """Skip the lane for *reason*, or fail it where the lane was required to run."""
    if os.environ.get(REQUIRE_ENV):
        pytest.fail(
            f"{reason}. {REQUIRE_ENV} is set, so this is a failure rather than a skip: the job "
            "declared that it runs the release lane and cannot"
        )
    pytest.skip(reason)


def missing_tools() -> list[str]:
    """What the lane needs and this host lacks: an engine with buildx and compose, uv, npm, git."""
    missing = [tool for tool in ("docker", "uv", "npm", "git") if shutil.which(tool) is None]
    if "docker" not in missing:
        for argv, what in (
            (["docker", "info", "--format", "{{.ServerVersion}}"], "a running Docker engine"),
            (["docker", "buildx", "version"], "docker buildx"),
            (["docker", "compose", "version"], "docker compose"),
        ):
            if subprocess.run(argv, capture_output=True, check=False).returncode != 0:  # noqa: S603
                missing.append(what)
    return missing


def run(
    argv: Sequence[str],
    *,
    cwd: pathlib.Path | None = None,
    env: dict[str, str] | None = None,
    stdin: bytes | None = None,
    check: bool = True,
    timeout: float = 1800,
) -> subprocess.CompletedProcess[str]:
    """Run *argv* (no shell); a failure raises with what the program said."""
    executable = shutil.which(argv[0]) or argv[0]
    done = subprocess.run(  # noqa: S603 - a fixed argument list
        [executable, *argv[1:]], cwd=cwd, env=env, input=stdin.decode() if stdin else None,
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        timeout=timeout,
    )
    if check and done.returncode != 0:
        raise AssertionError(
            f"{' '.join(argv)} exited {done.returncode}\n{done.stdout[-6000:]}\n{done.stderr[-6000:]}"
        )
    return done


# --------------------------------------------------------------------------- #
# two framework versions                                                      #
# --------------------------------------------------------------------------- #
def lockstep_version() -> str:
    """The version every backend distribution of this tree carries."""
    return tomllib.loads((BACKEND / "core" / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def backend_packages() -> list[pathlib.Path]:
    """Every backend distribution of this tree, the way template acceptance builds them."""
    fixed = [BACKEND / name for name in ("core", "arch", "migrations", "cli")]
    return [*fixed, *sorted(path for path in (BACKEND / "capabilities").iterdir() if (path / "pyproject.toml").is_file())]


def _copy_package(source: pathlib.Path, destination: pathlib.Path) -> None:
    shutil.copytree(
        source, destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "tests", "dist", "build"),
    )


def framework_wheels(version: str, out: pathlib.Path, scratch: pathlib.Path) -> dict[str, pathlib.Path]:
    """Every backend wheel of this tree, rebuilt as release *version*: ``{distribution: wheel}``.

    The lane needs two framework releases from the floor ``sign`` reads up (0.35.0), one minor
    apart, and they are not on an index yet: so the tree is built twice, each time with every
    lockstep pin (``version = "<v>"`` and ``==<v>``) rewritten. Nothing else differs, which is
    what a framework minor that ships no migration looks like to a deployed app.
    """
    current = lockstep_version()
    out.mkdir(parents=True, exist_ok=True)
    built: dict[str, pathlib.Path] = {}
    for package in backend_packages():
        copy = scratch / f"{package.name}-{version}"
        if copy.exists():
            shutil.rmtree(copy)
        _copy_package(package, copy)
        manifest = copy / "pyproject.toml"
        text = manifest.read_text(encoding="utf-8")
        rewritten = text.replace(f'version = "{current}"', f'version = "{version}"').replace(f"=={current}", f"=={version}")
        assert rewritten != text, f"{package} carries no lockstep version {current}"
        manifest.write_text(rewritten, encoding="utf-8")
        name = tomllib.loads(rewritten)["project"]["name"]
        before = set(out.glob("*.whl"))
        run(["uv", "build", "--wheel", "--quiet", "--out-dir", str(out), str(copy)])
        (wheel,) = set(out.glob("*.whl")) - before
        built[name] = wheel
    return built


def npm_tarballs(out: pathlib.Path) -> dict[str, pathlib.Path]:
    """The frontend packages packed from this tree: ``{package name: tarball}``."""
    out.mkdir(parents=True, exist_ok=True)
    packed: dict[str, pathlib.Path] = {}
    for workspace in NPM_WORKSPACES:
        before = set(out.glob("*.tgz"))
        run(["npm", "pack", "-w", workspace, "--pack-destination", str(out), "--silent"], cwd=REPO_ROOT)
        (tarball,) = set(out.glob("*.tgz")) - before
        packed[workspace] = tarball
    return packed


# --------------------------------------------------------------------------- #
# the job-local index and registry                                            #
# --------------------------------------------------------------------------- #
def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def write_index(root: pathlib.Path, wheels: Sequence[pathlib.Path], tarballs: Sequence[pathlib.Path]) -> None:
    """A PEP 503 simple index of *wheels* under ``simple/``, the files under ``files/`` and the
    npm tarballs under ``npm/``, every link carrying its SHA-256 so ``uv lock`` records it."""
    files, npm = root / "files", root / "npm"
    files.mkdir(parents=True, exist_ok=True)
    npm.mkdir(parents=True, exist_ok=True)
    by_project: dict[str, list[pathlib.Path]] = {}
    for wheel in wheels:
        shutil.copyfile(wheel, files / wheel.name)
        by_project.setdefault(normalise(wheel.name.split("-", 1)[0]), []).append(files / wheel.name)
    for tarball in tarballs:
        shutil.copyfile(tarball, npm / tarball.name)
    simple = root / "simple"
    simple.mkdir(exist_ok=True)
    listing = "".join(f'<a href="{name}/">{name}</a>\n' for name in sorted(by_project))
    (simple / "index.html").write_text(f"<!DOCTYPE html><html><body>\n{listing}</body></html>\n", encoding="utf-8")
    for name, found in sorted(by_project.items()):
        (simple / name).mkdir(exist_ok=True)
        links = "".join(
            f'<a href="../../files/{path.name}#sha256={hashlib.sha256(path.read_bytes()).hexdigest()}">{path.name}</a>\n'
            for path in sorted(found)
        )
        (simple / name / "index.html").write_text(f"<!DOCTYPE html><html><body>\n{links}</body></html>\n", encoding="utf-8")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _answers(url: str, deadline: float) -> bool:
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError):
            with urllib.request.urlopen(url, timeout=5):  # noqa: S310 - the lane's own loopback service
                return True
        time.sleep(0.5)
    return False


def publish(name: str, inside: int, argv: Sequence[str], probe: str) -> int:
    """Start container *name* published on a loopback port chosen here; the port, once it answers.

    Chosen explicitly, never ephemeral (see the module's docstring). A port the engine finds
    taken on its side is chosen again.
    """
    for _attempt in range(10):
        port = free_port()
        started = run(
            ["docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:{inside}", *argv], check=False
        )
        if started.returncode == 0:
            if _answers(f"http://127.0.0.1:{port}{probe}", time.monotonic() + 60):
                return port
            raise AssertionError(f"{name} never answered on 127.0.0.1:{port}:\n" + run(["docker", "logs", name], check=False).stderr)
        run(["docker", "rm", "-f", "-v", name], check=False)
        if "already" not in started.stderr and "in use" not in started.stderr:
            raise AssertionError(f"{name} did not start:\n{started.stderr}")
    raise AssertionError(f"no free loopback port for {name}")


def python_image() -> str:
    """The base-image table's Python, by digest: the interpreter every backend image runs."""
    table = json.loads((BACKEND / "arch" / "src" / "terp" / "arch" / "deployment" / "base-images.json").read_text(encoding="utf-8"))
    return str(table["images"]["python"]["image"])


@dataclass(frozen=True)
class Services:
    """The job-local index and registry, and where they answer."""

    index_port: int
    registry_port: int

    @property
    def index(self) -> str:
        return f"http://127.0.0.1:{self.index_port}"

    @property
    def registry(self) -> str:
        return f"127.0.0.1:{self.registry_port}"


SERVICE_NAMES = ("index", "registry")


def stop_services() -> None:
    """Remove the index and the registry, and the registry's storage."""
    for name in SERVICE_NAMES:
        run(["docker", "rm", "-f", "-v", f"{prefix()}{name}"], check=False)
    run(["docker", "volume", "rm", "-f", f"{prefix()}registry"], check=False)


def start_services(index_root: pathlib.Path) -> Services:
    """The index (the table's Python serving *index_root*, read-only) and ``registry:2``."""
    stop_services()
    index_port = publish(
        f"{prefix()}index", 8000,
        ["-v", f"{index_root.resolve()}:/srv:ro", python_image(), "python", "-m", "http.server", "8000", "-d", "/srv"],
        "/simple/",
    )
    registry_port = publish(
        f"{prefix()}registry", 5000,
        ["--mount", f"type=volume,src={prefix()}registry,dst=/var/lib/registry", REGISTRY_IMAGE],
        "/v2/",
    )
    return Services(index_port, registry_port)


@contextlib.contextmanager
def services(index_root: pathlib.Path) -> Iterator[Services]:
    """:func:`start_services`, removed after."""
    try:
        yield start_services(index_root)
    finally:
        stop_services()


# --------------------------------------------------------------------------- #
# the app                                                                      #
# --------------------------------------------------------------------------- #
#: The reference app's own name, which the lane replaces with one under its prefix.
REFERENCE_NAME = "reference-app"

#: What the lane's commits are made as: no one's identity, and never signed.
_GIT = ("git", "-c", "user.name=release lane", "-c", "user.email=lane@example.invalid", "-c", "commit.gpgsign=false")


def git(app: pathlib.Path, *argv: str) -> str:
    return run([*_GIT, "-C", str(app), *argv]).stdout.strip()


def commit(app: pathlib.Path, message: str) -> str:
    """Commit everything in *app*; the commit's full object name."""
    git(app, "add", "-A")
    git(app, "commit", "-q", "--allow-empty", "-m", message)
    return git(app, "rev-parse", "HEAD")


def _lock_environment() -> dict[str, str]:
    """This process's environment without anything that would point uv or npm elsewhere."""
    return {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(("UV_", "PIP_", "NPM_CONFIG_", "VIRTUAL_ENV"))
    }


def pin_framework(app: pathlib.Path, version: str) -> None:
    """Every terp-* pin of *app*'s manifest at *version*, and both locks brought to it."""
    manifest = app / "pyproject.toml"
    text = manifest.read_text(encoding="utf-8")
    pinned = re.sub(r'("terp-[a-z0-9-]+(?:\[[a-z,]+\])?==)[0-9][0-9.]*"', rf'\g<1>{version}"', text)
    assert pinned != text or f"=={version}" in text, "the app pins no terp-* distribution"
    manifest.write_text(pinned, encoding="utf-8")
    run(["uv", "lock", "--quiet"], cwd=app, env=_lock_environment())


def make_app(
    app: pathlib.Path, *, name: str, version: str, index: str, tarballs: dict[str, pathlib.Path]
) -> str:
    """The generated reference app at *app*, named *name*, on framework *version*; its commit.

    Rendered the way every lane renders it (``tools/render_reference_app.py``), then made what a
    released app is: its terp-* distributions from the job-local index (``[[tool.uv.index]]``,
    first, so uv takes every terp-* from it and everything else from PyPI) and locked there,
    its ``@terpjs/*`` packages from the same index by URL, both locks committed, and the
    generated state adopted with ``terp deployment adopt --build generated``. No ``.terp-dist/``
    and no path source: ``terp release`` refuses both.
    """
    run([sys.executable, str(REPO_ROOT / "tools" / "render_reference_app.py"), str(app)])
    manifest = app / "pyproject.toml"
    text = manifest.read_text(encoding="utf-8")
    assert f'name = "{REFERENCE_NAME}"' in text
    text = text.replace(f'name = "{REFERENCE_NAME}"', f'name = "{name}"', 1)
    text += (
        "\n# The release lane's job-local index: the framework's wheels, which no public index\n"
        "# carries yet. Listed first, so uv takes every terp-* from it and the rest from PyPI.\n"
        f'[[tool.uv.index]]\nname = "terp-lane"\nurl = "{index}/simple"\n'
    )
    manifest.write_text(text, encoding="utf-8")
    answers = app / ".copier-answers.yml"
    answers.write_text(
        answers.read_text(encoding="utf-8").replace(f"project_slug: {REFERENCE_NAME}", f"project_slug: {name}"),
        encoding="utf-8",
    )
    frontend = app / "frontend" / "package.json"
    declared = json.loads(frontend.read_text(encoding="utf-8"))
    for key in ("dependencies", "devDependencies"):
        for package in list(declared.get(key, {})):
            if package in tarballs:
                declared[key][package] = f"{index}/npm/{tarballs[package].name}"
    frontend.write_text(json.dumps(declared, indent=2) + "\n", encoding="utf-8")
    run(
        ["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"],
        cwd=app / "frontend", env=_lock_environment(),
    )
    pin_framework(app, version)
    git(app, "init", "-q", "-b", "main")
    commit(app, "the reference app, rendered")
    run(
        [sys.executable, "-c", "from terp.cli import main; main()", "deployment", "adopt", "--build", "generated"],
        cwd=app,
    )
    return commit(app, "adopt the generated state")


#: A revision that fails part-way through its upgrade: PostgreSQL rolls the whole step back, so
#: the version tables are what they were and the deploy that ran it is restore-free to undo.
FAILING_REVISION = '''"""the release lane: a revision whose upgrade fails

Revision ID: 1a2e0f0000c1
Revises: 3efab17d59e8
"""
from __future__ import annotations

from alembic import op

revision = "1a2e0f0000c1"
down_revision = "3efab17d59e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TABLE lane_partial (id integer)")
    op.execute("SELECT 1 / 0")


def downgrade() -> None:
    op.execute("DROP TABLE lane_partial")
'''


def move_up(app: pathlib.Path, version: str) -> str:
    """*app* moved to framework *version*, the way a generated app takes a framework update
    (the pins, the lock, the render); its commit."""
    pin_framework(app, version)
    run([sys.executable, "-c", "from terp.cli import main; main()", "deployment", "render"], cwd=app)
    return commit(app, f"move up to the framework's {version}")


def break_migration(app: pathlib.Path) -> str:
    """*app* with :data:`FAILING_REVISION` in its module's history; its commit."""
    versions = app / "app" / "modules" / "notices" / "migrations" / "versions"
    (versions / "1a2e0f0000c1_lane_fails.py").write_text(FAILING_REVISION, encoding="utf-8")
    return commit(app, "a migration that fails")


# --------------------------------------------------------------------------- #
# the registry, by its own API                                                 #
# --------------------------------------------------------------------------- #
_MANIFEST = "application/vnd.oci.image.manifest.v1+json"


def _request(url: str, *, method: str = "GET", data: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})  # noqa: S310 - the lane's own registry
    with urllib.request.urlopen(request, timeout=300) as answer:  # noqa: S310
        return answer.status, dict(answer.headers), answer.read()


def _push_blob(base: str, path: str, data: bytes) -> str:
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    _status, headers, _body = _request(f"{base}/v2/{path}/blobs/uploads/", method="POST")
    location = headers["Location"]
    location = location if location.startswith("http") else base + location
    joiner = "&" if "?" in location else "?"
    _request(f"{location}{joiner}digest={digest}", method="PUT", data=data,
             headers={"Content-Type": "application/octet-stream"})
    return digest


def retag(registry: str, repository: str, digest: str, tag: str) -> None:
    """Point *tag* of *repository* (a path under *registry*) at the manifest *digest*."""
    base = f"http://{registry}"
    _status, _headers, body = _request(f"{base}/v2/{repository}/manifests/{digest}", headers={"Accept": _MANIFEST})
    _request(f"{base}/v2/{repository}/manifests/{tag}", method="PUT", data=body, headers={"Content-Type": _MANIFEST})


def tamper(registry: str, repository: str, digest: str, tag: str, path: str, data: bytes) -> tuple[str, str]:
    """The image *digest* with one more layer that writes *data* at *path*, pushed as *tag*:
    ``(manifest digest, config digest)``. What an attacker with push access to the release
    repository, but no part in the build, can make of a release."""
    import gzip
    import io
    import tarfile

    base = f"http://{registry}"
    _status, _headers, body = _request(f"{base}/v2/{repository}/manifests/{digest}", headers={"Accept": _MANIFEST})
    manifest = json.loads(body)
    config = json.loads(_request(f"{base}/v2/{repository}/blobs/{manifest['config']['digest']}")[2])
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        member = tarfile.TarInfo(path)
        member.size, member.mode, member.mtime = len(data), 0o644, 0
        archive.addfile(member, io.BytesIO(data))
    layer = gzip.compress(raw.getvalue(), mtime=0)
    config["rootfs"]["diff_ids"].append("sha256:" + hashlib.sha256(raw.getvalue()).hexdigest())
    config.setdefault("history", []).append({"created_by": "the release lane's tampering"})
    layer_digest = _push_blob(base, repository, layer)
    config_bytes = json.dumps(config).encode()
    config_digest = _push_blob(base, repository, config_bytes)
    manifest["layers"].append({"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip", "digest": layer_digest, "size": len(layer)})
    manifest["config"] = {**manifest["config"], "digest": config_digest, "size": len(config_bytes)}
    manifest_bytes = json.dumps(manifest).encode()
    _request(f"{base}/v2/{repository}/manifests/{tag}", method="PUT", data=manifest_bytes, headers={"Content-Type": _MANIFEST})
    return "sha256:" + hashlib.sha256(manifest_bytes).hexdigest(), config_digest


def layer_sizes(registry: str, repository: str, digest: str) -> list[int]:
    """The size of every layer of the image *digest*, as its manifest records it."""
    manifest = json.loads(_request(f"http://{registry}/v2/{repository}/manifests/{digest}", headers={"Accept": _MANIFEST})[2])
    return [int(layer["size"]) for layer in manifest["layers"]]


def layer_times(registry: str, repository: str, digest: str) -> list[list[int]]:
    """The modification time of every entry of every layer of the image *digest*, layer by layer."""
    import gzip
    import io
    import tarfile

    base = f"http://{registry}"
    manifest = json.loads(_request(f"{base}/v2/{repository}/manifests/{digest}", headers={"Accept": _MANIFEST})[2])
    times: list[list[int]] = []
    for layer in manifest["layers"]:
        blob = _request(f"{base}/v2/{repository}/blobs/{layer['digest']}")[2]
        with tarfile.open(fileobj=io.BytesIO(gzip.decompress(blob))) as archive:
            times.append([int(member.mtime) for member in archive.getmembers()] or [0])
    return times


#: Run by the backend image's own interpreter: what it finds installed, and the PEP 508
#: environment a lock's markers are evaluated in for it.
INSTALLED = """import importlib.metadata as m, json, os, platform, sys
version = platform.python_version()
print(json.dumps({
    "installed": sorted([d.metadata["Name"], d.version] for d in m.distributions()),
    "environment": {
        "implementation_name": sys.implementation.name, "implementation_version": version,
        "os_name": os.name, "platform_machine": platform.machine(),
        "platform_python_implementation": platform.python_implementation(),
        "platform_release": platform.release(), "platform_system": platform.system(),
        "platform_version": platform.version(), "python_full_version": version,
        "python_version": ".".join(platform.python_version_tuple()[:2]), "sys_platform": sys.platform,
        "extra": "",
    },
}))
"""


def locked_runtime_set(app: pathlib.Path, environment: dict[str, str]) -> dict[str, str]:
    """What the lock installs without its development group, as uv itself resolves it
    (``uv export``), each marker evaluated in *environment*: ``{name: version}``."""
    from packaging.markers import Marker

    exported = run(
        ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes", "--no-header",
         "--no-annotate", "--format", "requirements-txt"],
        cwd=app, env=_lock_environment(),
    ).stdout
    found: dict[str, str] = {}
    for line in exported.splitlines():
        requirement, _, marker = line.partition(";")
        if not requirement.strip() or requirement.lstrip().startswith("#"):
            continue
        if marker.strip() and not Marker(marker.strip()).evaluate(environment):
            continue
        name, _, version = requirement.strip().partition("==")
        found[normalise(name)] = version
    return found


#: The service principal the deployed app stamps a scheduled job's writes with (production
#: refuses to boot without one); a fixed value, the lane's own.
ACTOR_ID = "6c1a0e5e-9a7d-4d1b-8f3e-1a2b3c4d5e6f"


# --------------------------------------------------------------------------- #
# the signer image, run as an operator runs it                                 #
# --------------------------------------------------------------------------- #
def signer_image(scratch: pathlib.Path) -> str:
    """The signer image, built cold from this tree exactly as CI's signer job builds it."""
    context = scratch / "signer-context"
    if context.exists():
        shutil.rmtree(context)
    run([sys.executable, str(REPO_ROOT / "tools" / "signer_context.py"), str(context)])
    tag = f"{prefix()}signer:lane"
    run(["docker", "build", "--pull", "--no-cache", "-q", "-t", tag, str(context)])
    return tag


def keys(directory: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """A throwaway Ed25519 key pair: ``(private PEM, public PEM)``."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    key = ed25519.Ed25519PrivateKey.generate()
    private, public = directory / "lane-key.pem", directory / "lane-key.pub.pem"
    private.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public.write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    return private, public


def release_table(path: pathlib.Path, wheels: Sequence[pathlib.Path]) -> None:
    """The signer's terp-arch release table, carrying each terp-arch wheel of *wheels*."""
    releases = {
        wheel.name.split("-")[1]: {"wheel": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}
        for wheel in wheels if wheel.name.startswith("terp_arch-")
    }
    path.write_text(json.dumps({"terpArchReleases": 1, "releases": releases}), encoding="utf-8")


def _socket_group(image: str) -> str:
    return run([
        "docker", "run", "--rm", "--entrypoint", "stat", "-v", "/var/run/docker.sock:/var/run/docker.sock",
        image, "-c", "%g", "/var/run/docker.sock",
    ]).stdout.strip()


def sign_in_image(
    image: str, *, repo: pathlib.Path, sha: str, tag: str, registry: str, build: pathlib.Path,
    gate: pathlib.Path, key: pathlib.Path, table: pathlib.Path, wheels: pathlib.Path, out: pathlib.Path,
) -> subprocess.CompletedProcess[str]:
    """``terp release sign`` from the signer image, the way an operator runs it: the checkout
    read-only, the engine's socket and its group, the loopback registry over the host network,
    a throwaway key with ``--test-key``. Not checked: a refusal is an answer the lane reads."""
    out.mkdir(parents=True, exist_ok=True)
    out.chmod(0o777)  # the image's own user writes the envelope here
    inputs = out.parent / f"{out.name}-inputs"
    inputs.mkdir(exist_ok=True)
    for source in (build, gate, key, table):
        shutil.copyfile(source, inputs / source.name)
    return run([
        "docker", "run", "--rm", "--name", f"{prefix()}sign", "--network", "host",
        "--group-add", _socket_group(image), "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", f"{repo.resolve()}:/repo:ro", "-v", f"{inputs.resolve()}:/lane:ro",
        "-v", f"{wheels.resolve()}:/lane-wheels:ro", "-v", f"{out.resolve()}:/out",
        image, "sign", "--repo", "/repo", "--sha", sha, "--tag", tag, "--registry", registry,
        "--registry-http", "--build", f"/lane/{build.name}", "--gate", f"/lane/{gate.name}",
        "--hosts", "shared", "--sign-key", f"/lane/{key.name}", "--test-key",
        "--terp-arch-releases", f"/lane/{table.name}", "--terp-index", "/lane-wheels", "--out-dir", "/out",
    ], check=False)


# --------------------------------------------------------------------------- #
# what runs on the engine                                                      #
# --------------------------------------------------------------------------- #
def project_containers(project: str, service: str | None = None) -> list[dict[str, str]]:
    """Every container of compose project *project* (of one *service*): name, image, state."""
    argv = ["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={project}"]
    if service is not None:
        argv += ["--filter", f"label=com.docker.compose.service={service}"]
    listed = run([*argv, "--format", "{{json .}}"]).stdout
    return [json.loads(line) for line in listed.splitlines() if line.strip()]


def remove_everything(app_name: str) -> None:
    """Every container, volume, network, builder and image the lane named, and the services."""
    run(["docker", "compose", "-p", f"{app_name}-prod", "down", "-v", "--remove-orphans"], check=False)
    run(["docker", "rm", "-f", f"{prefix()}sign"], check=False)
    for line in run(["docker", "buildx", "ls", "--format", "{{.Name}}"], check=False).stdout.splitlines():
        if line.strip().startswith(prefix()):
            run(["docker", "buildx", "rm", "--force", line.strip()], check=False)
    # Listed again after each pass: an engine lists an image's by-digest name only once the
    # tagged name of the same content is gone.
    for _pass in range(4):
        listed = run(["docker", "images", "--digests", "--format", "{{.Repository}}|{{.Tag}}|{{.Digest}}"], check=False)
        ours = [
            (repository, tag, digest)
            for repository, tag, digest in ((line.split("|") + ["", "", ""])[:3] for line in listed.stdout.splitlines())
            if repository.startswith(prefix()) or f"/{prefix()}" in repository
        ]
        if not ours:
            break
        for repository, tag, digest in ours:
            reference = f"{repository}:{tag}" if tag and tag != "<none>" else f"{repository}@{digest}"
            run(["docker", "image", "rm", "-f", reference], check=False)
    stop_services()


__all__ = [
    "ACTOR_ID",
    "DEFAULT_PREFIX",
    "INSTALLED",
    "free_port",
    "layer_sizes",
    "layer_times",
    "locked_runtime_set",
    "normalise",
    "keys",
    "project_containers",
    "release_table",
    "remove_everything",
    "sign_in_image",
    "signer_image",
    "FAILING_REVISION",
    "break_migration",
    "move_up",
    "retag",
    "tamper",
    "REFERENCE_NAME",
    "commit",
    "git",
    "make_app",
    "pin_framework",
    "start_services",
    "stop_services",
    "PREFIX_ENV",
    "REGISTRY_IMAGE",
    "REQUIRE_ENV",
    "Services",
    "framework_wheels",
    "lockstep_version",
    "missing_tools",
    "npm_tarballs",
    "prefix",
    "publish",
    "python_image",
    "run",
    "services",
    "unavailable",
    "write_index",
]
