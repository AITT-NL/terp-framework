"""The release lane: ``terp release`` and ``terp promote`` on a real Docker engine (ADR 0187).

Decision 8's sixth pull request. Everything decision 6 promised that only an engine can show,
on the generated reference app (``tools/render_reference_app.py``, then ``terp deployment adopt
--build generated``), its terp-* distributions from a job-local index and its images in a
job-local ``registry:2`` pinned by digest, both on the loopback:

* real BuildKit builds from the pristine tree, in a builder made for the job, pushed by digest,
  BuildKit's own metadata carrying the digests, ``rewrite-timestamp`` clamping what it wrote;
* two cold builds of one commit and tag, signed apart: byte-identical ``inputs`` and installed
  lists, the image digests measured and printed, never asserted (decision 6);
* the gate's schedule catalog read from the pushed image, pulled by digest and run sealed;
* ``sign`` from the signer image built as CI builds it, against the real images: the app layer
  and its bytecode held to the tree, the installed set to the lock, and an image whose app
  layer was changed after the build refused;
* ``terp promote`` of exactly the signed digests: the app moved up one minor (two framework
  releases built from this tree, 0.35.0 and 0.36.0, because none is published yet) and rolled
  back by promoting the previous release; a deploy whose migration fails on unchanged version
  tables undone without a restore; an envelope changed under its signature and an image changed
  under a valid one refused.

The gate's ``terp verify --profile release`` runs the app's own suite, conformance and audits,
which are the app's subject and not this lane's: the lane gives the gate a passing claim and
runs the half of it that needs an engine. Selected with ``-m release_lane`` (the gate
deselects it: it builds four releases cold from PyPI and npm, about fifteen minutes); skipped
without an engine, failed instead where ``TERP_REQUIRE_RELEASE_LANE`` is set, as CI's job sets it.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import re
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from tests.release_lane import lane as rl

pytestmark = pytest.mark.release_lane

#: Two framework releases one minor apart, from the first ``sign`` reads.
FIRST, SECOND = "0.35.0", "0.36.0"

#: Where the lane keeps the release a promotion deploys from, and where it measures the second
#: cold build of the first commit.
RELEASE_PATH, SECOND_COLD_PATH = "rel", "cold"


@dataclass
class Release:
    """One release the lane cut: its commit, tag, documents and what ``sign`` answered."""

    label: str
    sha: str
    tag: str
    path: str
    build: dict[str, Any]
    build_file: pathlib.Path
    gate_file: pathlib.Path
    out: pathlib.Path
    signed: subprocess.CompletedProcess[str] | None = None

    @property
    def envelope(self) -> pathlib.Path:
        return self.out / "release.dsse.json"

    def manifest(self) -> dict[str, Any]:
        return json.loads((self.out / "release.manifest.json").read_text(encoding="utf-8"))

    def image(self, web: bool) -> dict[str, Any]:
        return next(image for image in self.build["images"] if image["web"] is web)


@dataclass
class Lane:
    work: pathlib.Path
    app: pathlib.Path
    name: str
    services: rl.Services
    signer: str
    private: pathlib.Path
    public: pathlib.Path
    table: pathlib.Path
    wheels: pathlib.Path
    deploy: pathlib.Path
    env: dict[str, str]
    releases: dict[str, Release] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def project(self) -> str:
        return f"{self.name}-prod"


def _timed(lane_: Lane, what: str, start: float) -> None:
    taken = sum(1 for key in lane_.timings if key == what or key.startswith(f"{what} #"))
    lane_.timings[f"{what} #{taken + 1}" if taken else what] = round(time.monotonic() - start, 1)


def _cut(lane_: Lane, label: str, tag: str, path: str) -> Release:
    """Build the app's HEAD (in-process, as ``terp release build`` does) and gate it."""
    from terp.cli.release import build as build_module
    from terp.cli.release import gate as gate_module
    from terp.cli.release._common import write_document

    sha = rl.git(lane_.app, "rev-parse", "HEAD")
    start = time.monotonic()
    document = build_module.build(lane_.app, sha, tag, f"{lane_.services.registry}/{rl.prefix()}{path}", registry_http=True)
    _timed(lane_, f"build {label}", start)
    build_file = lane_.work / f"build-{label}.json"
    write_document(build_file, document)
    start = time.monotonic()
    gated = gate_module.gate(lane_.app, sha, build_file)
    _timed(lane_, f"gate {label}", start)
    gate_file = lane_.work / f"gate-{label}.json"
    write_document(gate_file, gated)
    release = Release(label, sha, tag, f"{rl.prefix()}{path}", document, build_file, gate_file, lane_.work / f"out-{label}")
    lane_.releases[label] = release
    return release


def _sign(lane_: Lane, release: Release, *, build_file: pathlib.Path | None = None, tag: str | None = None,
          out: pathlib.Path | None = None) -> subprocess.CompletedProcess[str]:
    start = time.monotonic()
    done = rl.sign_in_image(
        lane_.signer, repo=lane_.app, sha=release.sha, tag=tag or release.tag,
        registry=f"{lane_.services.registry}/{release.path}", build=build_file or release.build_file,
        gate=release.gate_file, key=lane_.private, table=lane_.table, wheels=lane_.wheels,
        out=out or release.out,
    )
    _timed(lane_, f"sign {release.label if out is None else out.name}", start)
    return done


@pytest.fixture(scope="module")
def lane(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Lane]:
    """Four releases of the generated reference app, built cold, gated and signed.

    ``a`` and ``a2``: the first commit on framework 0.35.0, built twice cold under one tag into
    two registry paths. ``b``: the same app moved up to 0.36.0. ``c``: ``b`` with a migration
    that fails part-way. Everything named under the lane's prefix and removed after.
    """
    missing = rl.missing_tools()
    if missing:
        rl.unavailable(f"the release lane needs {', '.join(missing)}")
    from terp.cli.release import build as build_module
    from terp.cli.release import gate as gate_module

    patch = pytest.MonkeyPatch()
    patch.setattr(build_module, "BUILDER_PREFIX", f"{rl.prefix()}builder-")
    patch.setattr(gate_module, "_verify", lambda checkout: {
        "ok": True, "profile": "release",
        "note": "the release lane's stand-in: the app's suite is the app's subject, not the lane's",
    })
    name = f"{rl.prefix()}app"
    work = tmp_path_factory.mktemp("lane")
    rl.remove_everything(name)
    try:
        start = time.monotonic()
        wheels = {version: rl.framework_wheels(version, work / "wheels" / version, work / "src") for version in (FIRST, SECOND)}
        tarballs = rl.npm_tarballs(work / "npm")
        all_wheels = [wheel for built in wheels.values() for wheel in built.values()]
        rl.write_index(work / "index", all_wheels, list(tarballs.values()))
        services = rl.start_services(work / "index")
        signer = rl.signer_image(work)
        (work / "keys").mkdir()
        private, public = rl.keys(work / "keys")
        table = work / "keys" / "terp-arch-releases.json"
        rl.release_table(table, all_wheels)
        environment = {
            key: value for key, value in os.environ.items()
            if key.upper() not in ("DATABASE_URL", "BACKEND_CORS_ORIGINS", "WEB_PORT", "SECRET_KEY",
                                   "POSTGRES_PASSWORD", "TERP_RELEASE_TAG", "COMPOSE_PROJECT_NAME", "COMPOSE_FILE")
        }
        environment |= {"SECRET_KEY": os.urandom(32).hex(), "POSTGRES_PASSWORD": os.urandom(16).hex(),
                        "WEB_PORT": str(rl.free_port())}
        lane_ = Lane(work, work / "app", name, services, signer, private, public, table,
                     work / "index" / "files", work / "deploy", environment)
        _timed(lane_, "set up (wheels, tarballs, index, registry, signer)", start)

        rl.make_app(lane_.app, name=name, version=FIRST, index=services.index, tarballs=tarballs)
        _cut(lane_, "a", "lane-a", RELEASE_PATH)
        _cut(lane_, "a2", "lane-a", SECOND_COLD_PATH)
        rl.move_up(lane_.app, SECOND)
        _cut(lane_, "b", "lane-b", RELEASE_PATH)
        rl.break_migration(lane_.app)
        _cut(lane_, "c", "lane-c", RELEASE_PATH)
        for release in lane_.releases.values():
            release.signed = _sign(lane_, release)
        yield lane_
        print(f"\nrelease lane timings (s): {json.dumps(lane_.timings)}")
    finally:
        rl.remove_everything(name)
        patch.undo()


# --------------------------------------------------------------------------- #
# build                                                                        #
# --------------------------------------------------------------------------- #
def test_buildkit_pushes_each_image_by_digest_and_clamps_what_it_wrote(lane: Lane) -> None:
    """BuildKit's own metadata names each pushed image and its configuration (the two keys
    ``build`` reads), the builder is the pinned one, and ``rewrite-timestamp`` clamped every
    file the build wrote to the commit's time, so a cold build reads no clock."""
    from terp.cli.release.build import BUILDKIT_IMAGE

    for release in lane.releases.values():
        document = release.build
        assert document["builder"]["image"] == BUILDKIT_IMAGE
        assert document["builder"]["buildkit"] == "v0.34.1", document["builder"]
        assert {image["name"] for image in document["images"]} == {f"{lane.name}-backend-prod", f"{lane.name}-frontend-prod"}
        for image in document["images"]:
            assert re.fullmatch(r"sha256:[0-9a-f]{64}", image["digest"]) and re.fullmatch(r"sha256:[0-9a-f]{64}", image["configDigest"])
            times = rl.layer_times(lane.services.registry, image["repository"].split("/", 1)[1], image["digest"])
            assert max(times[-1]) == document["sourceDateEpoch"], (image["name"], "the last layer is the build's")
            assert max(max(layer) for layer in times) <= document["sourceDateEpoch"], image["name"]
    assert not [line for line in rl.run(["docker", "buildx", "ls"]).stdout.splitlines() if f"{rl.prefix()}builder-" in line], (
        "each job's builder is removed after it")


def test_two_cold_builds_of_one_commit_read_alike(lane: Lane) -> None:
    """Decision 6: byte-identical ``inputs`` and installed lists; the digests are measured."""
    first, second = lane.releases["a"], lane.releases["a2"]
    assert first.signed is not None and first.signed.returncode == 0, first.signed and first.signed.stdout + first.signed.stderr
    assert second.signed is not None and second.signed.returncode == 0, second.signed and second.signed.stdout + second.signed.stderr
    from terp.cli.release._common import canonical

    assert canonical(first.manifest()["inputs"]) == canonical(second.manifest()["inputs"])
    lists = sorted(path.name for path in first.out.glob("packages-*.json"))
    assert len(lists) == 2
    for listed in lists:
        assert (first.out / listed).read_bytes() == (second.out / listed).read_bytes(), listed
    measured = {
        image["name"]: {"first": image["digest"], "second": other["digest"], "identical": image["digest"] == other["digest"]}
        for image, other in zip(first.build["images"], second.build["images"], strict=True)
    }
    print(f"\ntwo cold builds of {first.sha[:12]}: {json.dumps(measured)}")


def test_the_image_ships_exactly_the_lock_s_runtime_set(lane: Lane) -> None:
    """The distributions the backend image's own interpreter finds equal what ``sign`` read from
    its filesystem, and both equal the lock's runtime set as ``uv export`` resolves it, its
    markers evaluated for the image's interpreter, plus the app itself."""
    release = lane.releases["c"]
    backend = release.image(web=False)
    reference = f"{backend['repository']}@{backend['digest']}"
    rl.run(["docker", "pull", "-q", reference])
    found = json.loads(rl.run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "python", reference,
                                "-I", "-c", rl.INSTALLED]).stdout)
    installed = {rl.normalise(name): version for name, version in found["installed"]}
    signed = {rl.normalise(name): version for name, version in json.loads(
        (release.out / f"packages-{backend['name']}.json").read_text(encoding="utf-8"))}
    assert signed == installed
    expected = rl.locked_runtime_set(lane.app, found["environment"])
    assert installed == {**expected, rl.normalise(lane.name): "0.1.0"}


# --------------------------------------------------------------------------- #
# sign                                                                         #
# --------------------------------------------------------------------------- #
def test_sign_from_the_signer_image_signs_every_release(lane: Lane) -> None:
    """Signed, every one, by reading the backend image's layers from ``registry:2``, which serves
    its own blobs: one is larger than a manifest may be, which the registry client once held
    every layer to (it kept the first request's client per host), so no image could be read."""
    from terp.cli.release import dsse
    from terp.cli.release._registry import MANIFEST_LIMIT

    backend = lane.releases["a"].image(web=False)
    sizes = rl.layer_sizes(lane.services.registry, backend["repository"].split("/", 1)[1], backend["digest"])
    assert max(sizes) > MANIFEST_LIMIT, sizes
    for release in lane.releases.values():
        assert release.signed is not None and release.signed.returncode == 0, release.signed and release.signed.stdout + release.signed.stderr
        payload, _keyid = dsse.verify(release.envelope.read_bytes(), [dsse.load_public_key(lane.public.read_bytes())])
        manifest = json.loads(payload)
        assert manifest["inputs"]["build"] == "generated"
        assert manifest["inputs"]["toolchain"]["terpArch"] == (FIRST if release.label.startswith("a") else SECOND)
        assert manifest["outputs"]["secretScan"]["findings"] == 0


def test_sign_refuses_an_image_whose_app_layer_changed_after_the_build(lane: Lane) -> None:
    """An image with one more layer that rewrites the app's entry module, pushed under a tag of
    its own with the web image beside it: everything about it is real but the app layer."""
    release = lane.releases["a"]
    backend, web = release.image(web=False), release.image(web=True)
    repository = backend["repository"].split("/", 1)[1]
    original = rl.git(lane.app, "show", f"{release.sha}:app/main.py") + "\n"
    digest, config = rl.tamper(lane.services.registry, repository, backend["digest"], "lane-tampered",
                               "srv/app/main.py", (original + "import os  # planted after the build\n").encode())
    rl.retag(lane.services.registry, web["repository"].split("/", 1)[1], web["digest"], "lane-tampered")
    document = json.loads(json.dumps(release.build))
    document["releaseTag"] = "lane-tampered"
    for image in document["images"]:
        image["tag"] = "lane-tampered"
        if not image["web"]:
            image["digest"], image["configDigest"] = digest, config
    tampered = lane.work / "build-tampered.json"
    tampered.write_text(json.dumps(document), encoding="utf-8")
    refused = _sign(lane, release, build_file=tampered, tag="lane-tampered", out=lane.work / "out-tampered")
    said = refused.stdout + refused.stderr
    assert refused.returncode == 1, said
    assert f"{repository}@{digest} is not this commit's build" in said, said
    assert "- /srv/app/main.py is not the tree's app/main.py" in said, said
    assert not (lane.work / "out-tampered" / "release.dsse.json").exists()


# --------------------------------------------------------------------------- #
# promote                                                                      #
# --------------------------------------------------------------------------- #
def _promote(lane: Lane, label: str, *, undo_to: str | None = None) -> list[str]:
    from terp.cli.release.promote import promote

    lane.deploy.mkdir(exist_ok=True)
    env_file = lane.deploy / ".app.env"
    if not env_file.exists():
        env_file.write_text(
            "MAIL_FROM=Release Lane <lane@example.invalid>\nSMTP_HOST=relay.example.invalid\n"
            f"SMTP_SECURITY=starttls\nJOB_SYSTEM_ACTOR_ID={rl.ACTOR_ID}\n", encoding="utf-8",
        )
    start = time.monotonic()
    try:
        return promote(
            lane.releases[label].envelope, [lane.public], lane.deploy, require_generated=True,
            undo_to=lane.releases[undo_to].envelope if undo_to else None, env=lane.env,
        )
    finally:
        _timed(lane, f"promote {label}{f' --undo-to {undo_to}' if undo_to else ''}", start)


def _exec(lane: Lane, service: str, *argv: str) -> str:
    (container,) = rl.project_containers(lane.project, service)
    return rl.run(["docker", "exec", container["Names"], *argv]).stdout.strip()


def _sql(lane: Lane, statement: str) -> str:
    return _exec(lane, "db", "psql", "-q", "-tA", "-U", "app", "-d", "app", "-c", statement)


def _journal(lane: Lane, tag: str) -> dict[str, list[str]]:
    return json.loads((lane.deploy / ".terp" / f"versions-before-{tag}.json").read_text(encoding="utf-8"))


def _runs(lane: Lane, label: str) -> None:
    """Every long-running unit runs *label*'s signed image, the checked ones healthy, and the
    migration step left no container behind: ``up --no-deps`` never started it again."""
    manifest = lane.releases[label].manifest()
    images = manifest["outputs"]["images"]
    containers = rl.project_containers(lane.project)
    assert {container["Labels"].split("com.docker.compose.service=")[1].split(",")[0] for container in containers} == {
        "db", "api", "web", "worker", "scheduler", "monitor"}, "no migrate container: run --rm, and up --no-deps"
    for container in containers:
        inspected = json.loads(rl.run(["docker", "inspect", container["Names"]]).stdout)[0]
        service = inspected["Config"]["Labels"]["com.docker.compose.service"]
        assert inspected["State"]["Status"] == "running", (service, inspected["State"])
        if service != "monitor":  # a companion writes no heartbeat and has no check (ADR 0191)
            assert inspected["State"]["Health"]["Status"] == "healthy", service
        if service == "db":
            continue
        signed = images[f"{lane.name}-frontend-prod" if service == "web" else f"{lane.name}-backend-prod"]
        assert inspected["Image"] in (signed["digest"], signed["imageId"]), (service, inspected["Image"])


def test_the_reference_app_moves_up_a_minor_and_rolls_back_by_promoting_the_previous_release(lane: Lane) -> None:
    log = _promote(lane, "a")
    assert log[-1] == "promoted lane-a" and any("ran the migration step once" in line for line in log), log
    assert _journal(lane, "lane-a") == {}, "a first deploy reads no version table: there is none yet"
    _runs(lane, "a")
    assert _exec(lane, "api", "terp", "--version") == f"terp {FIRST}"
    _sql(lane, "CREATE TABLE lane_marker (written_under text); INSERT INTO lane_marker VALUES ('lane-a')")

    log = _promote(lane, "b")
    assert log[-1] == "promoted lane-b", log
    heads = _journal(lane, "lane-b")
    assert len(heads) >= 7 and heads["alembic_version_notices"] == ["3efab17d59e8"], heads
    _runs(lane, "b")
    assert _exec(lane, "api", "terp", "--version") == f"terp {SECOND}"

    log = _promote(lane, "a")
    assert log[-1] == "promoted lane-a", log
    assert _journal(lane, "lane-a") == heads, "the minor applied no revision, so going back crosses none"
    _runs(lane, "a")
    assert _exec(lane, "api", "terp", "--version") == f"terp {FIRST}"
    assert _sql(lane, "SELECT written_under FROM lane_marker") == "lane-a", "no restore: the data is the data"


def test_a_deploy_that_fails_on_unchanged_version_tables_is_undone_without_a_restore(lane: Lane) -> None:
    from terp.cli.release._common import ReleaseError

    _promote(lane, "a")
    heads = _journal(lane, "lane-a")
    with pytest.raises(ReleaseError) as failed:
        _promote(lane, "c", undo_to="a")
    said = str(failed.value)
    assert "the migration step failed" in said and "division by zero" in said, said
    assert "undone: lane-a runs again on the database as it was, without a restore" in said, said
    assert _journal(lane, "lane-c") == heads
    assert _sql(lane, "SELECT to_regclass('public.lane_partial')") == "", "the failed step left nothing behind"
    _runs(lane, "a")
    assert _exec(lane, "api", "terp", "--version") == f"terp {FIRST}"


def test_a_changed_envelope_or_a_changed_image_is_refused(lane: Lane, monkeypatch: pytest.MonkeyPatch) -> None:
    from terp.cli.release import promote as promote_module
    from terp.cli.release._common import ReleaseError, canonical

    # The envelope: B's backend digest written into A's payload, A's signature kept.
    envelope = json.loads(lane.releases["a"].envelope.read_text(encoding="utf-8"))
    manifest = json.loads(base64.b64decode(envelope["payload"]))
    backend = f"{lane.name}-backend-prod"
    manifest["outputs"]["images"][backend]["digest"] = lane.releases["b"].manifest()["outputs"]["images"][backend]["digest"]
    envelope["payload"] = base64.b64encode(canonical(manifest)).decode()
    changed = lane.work / "changed.dsse.json"
    changed.write_bytes(canonical(envelope))
    ran: list[list[str]] = []
    real = promote_module.run
    monkeypatch.setattr(promote_module, "run", lambda argv, **kwargs: ran.append(list(argv)) or real(argv, **kwargs))
    with pytest.raises(ReleaseError, match="no signature of the envelope verifies"):
        promote_module.promote(changed, [lane.public], lane.work / "deploy-changed", env=lane.env)
    assert ran == [] and not (lane.work / "deploy-changed").exists(), "refused before anything ran or was written"
    monkeypatch.undo()

    # The image: A's tag on this engine moved to C's backend image, then an undo to A.
    _promote(lane, "a")
    signed = lane.releases["a"].manifest()["outputs"]["images"][backend]
    local = f"{backend}:lane-a"
    other = lane.releases["c"].image(web=False)
    rl.run(["docker", "pull", "-q", f"{other['repository']}@{other['digest']}"])
    rl.run(["docker", "tag", f"{other['repository']}@{other['digest']}", local])
    try:
        with pytest.raises(ReleaseError) as refused:
            _promote(lane, "c", undo_to="a")
        said = str(refused.value)
        assert f"{local} is " in said and f"not the image the release signs (manifest {signed['digest']}" in said, said
    finally:
        rl.run(["docker", "tag", f"{signed['repository']}@{signed['digest']}", local])


def test_the_lane_named_everything_it_made(lane: Lane) -> None:
    """What the lane put on the engine is findable by its prefix, so a shared engine's other
    projects are never touched and nothing is left behind (the fixture removes all of it)."""
    containers = rl.run(["docker", "ps", "-a", "--format", "{{.Names}}"]).stdout.split()
    ours = [name for name in containers if name.startswith(rl.prefix())]
    assert ours and all(name.startswith((rl.prefix(), f"{lane.project}-")) for name in ours)
    volumes = rl.run(["docker", "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={lane.project}"]).stdout.split()
    assert volumes and all(volume.startswith(lane.project) for volume in volumes), volumes
