"""``terp release build`` and the refusals every release job repeats (ADR 0184 d9, 0187 d6).

The plan is read from the commit alone; the build runs BuildKit through docker, which a
:class:`Runs` stands in for, so what is asserted is exactly the argument lists the job hands
the builder: a builder of its own from a pinned image, ``--pull``, no cache, the pristine
tree as the context, the release tag, BuildKit's metadata, and the builder removed after.
"""

from __future__ import annotations

import json
import pathlib

import pytest
import yaml

from terp.arch.deployment import published_table
from terp.cli.release import _plan, build
from terp.cli.release._common import ReleaseError
from terp.cli.release._git import Tree
from tests.architecture.release_fixtures import PROJECT, Runs, app_files, committed_app, git

SEAM = "${TERP_RELEASE_TAG:?TERP_RELEASE_TAG is required, one new image tag per release}"


def _plan_of(tmp_path: pathlib.Path, files: dict[str, bytes]) -> _plan.Plan:
    sha = committed_app(tmp_path / "repo", files)
    tree = Tree.read(tmp_path / "repo", sha)
    tree.materialize(tmp_path / "tree")
    return _plan.release_plan(tree, tmp_path / "tree", published_table())


def _refusals(tmp_path: pathlib.Path, files: dict[str, bytes]) -> str:
    with pytest.raises(ReleaseError) as raised:
        _plan_of(tmp_path, files)
    assert raised.value.message.startswith("terp release refuses this commit:")
    return raised.value.message


def _own(profile: dict, units: list[dict] | None = None) -> dict[str, bytes]:
    """The app under ``"build": "own"``, with *profile* as its own production profile."""
    files = app_files()
    declaration = json.loads(files["deployment.json"])
    declaration["build"] = "own"
    if units is not None:
        declaration["units"] = units
    files["deployment.json"] = json.dumps(declaration, indent=2).encode()
    files["docker-compose.prod.yml"] = yaml.safe_dump(profile, sort_keys=False).encode()
    return files


def _profile() -> dict:
    """The rendered profile, as data, to change one thing in."""
    return yaml.safe_load(app_files()["docker-compose.prod.yml"])


# --------------------------------------------------------------------------- the plan
def test_the_generated_app_plans_one_backend_image_run_by_every_backend_unit(tmp_path: pathlib.Path) -> None:
    plan = _plan_of(tmp_path, app_files())
    assert [(image.name, image.context, image.dockerfile, image.services, image.web) for image in plan.images] == [
        (f"{PROJECT}-backend-prod", ".", "Dockerfile.prod", ("api", "migrate"), False)
    ]
    assert plan.migration_step == "migrate" and plan.api == "api"
    assert plan.datastores == {"db": published_table().find("postgres", "17").image}
    assert plan.image_of("api") is plan.images[0] and plan.image_of("db") is None
    assert _plan.argv(["terp", "$$x", "${Y}"]) == ("terp", "$x", None)
    assert _plan.argv("terp jobs worker") == ("terp", "jobs", "worker")
    assert _plan.argv("echo $X") == (None,)
    assert _plan.argv(None) is None


def test_a_web_image_is_planned_as_the_web_tier_s(tmp_path: pathlib.Path) -> None:
    profile = _profile()
    profile["services"]["web"] = {
        "build": {"context": "frontend", "dockerfile": "Dockerfile.web"},
        "image": f"{PROJECT}-frontend-prod:{SEAM}",
        "depends_on": {"api": {"condition": "service_healthy"}},
    }
    profile["services"]["tools"] = {"image": "busybox", "profiles": ["debug"]}
    units = json.loads(app_files()["deployment.json"])["units"] + [{"id": "web", "role": "web", "dependsOn": ["api"]}]
    files = _own(profile, units) | {"frontend/Dockerfile.web": b"FROM scratch\n"}
    plan = _plan_of(tmp_path, files)
    web = next(image for image in plan.images if image.web)
    assert (web.name, web.context, web.dockerfile, web.services) == (
        f"{PROJECT}-frontend-prod", "frontend", "frontend/Dockerfile.web", ("web",)
    )
    assert "tools" not in plan.services, "a service under a compose profile is not part of the release"


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda f: f.pop("deployment.json"), "has no deployment.json: terp release drives a declared app only"),
        (lambda f: f.update({"deployment.json": b'{"schemaVersion": 1, "build": "x"}'}), "deployment.json cannot be read"),
        (lambda f: f.update({"deployment.json": b'{"unmanaged": true, "reason": "by hand"}'}), "declares this app unmanaged (by hand)"),
        (lambda f: f.update({".terp-dist/wheels/x.whl": b"x"}), ".terp-dist/ is committed"),
        (lambda f: f.pop("uv.lock"), "uv.lock is not committed"),
        (lambda f: f.update({"uv.lock": f["uv.lock"] + b'\n[[package]]\nname = "v"\nversion = "1"\nsource = { path = "../v" }\n'}),
         "uv.lock takes v (path = '../v') from a path"),
        (lambda f: f.update({"frontend/package-lock.json": json.dumps({"packages": {"": {}, "node_modules/x": {"version": "1", "resolved": "file:../x.tgz"}}}).encode()}),
         "frontend/package-lock.json takes node_modules/x from a path"),
    ],
)
def test_the_commit_is_refused_from_data(tmp_path: pathlib.Path, change, expected: str) -> None:
    files = app_files()
    change(files)
    assert expected in _refusals(tmp_path, files)


def test_an_untrue_declaration_and_a_profile_it_cannot_read_are_refused(tmp_path: pathlib.Path) -> None:
    files = app_files()
    files.pop("docker-compose.prod.yml")
    message = _refusals(tmp_path, files)
    assert "deployment.json is not true" in message and "does not exist" in message


def test_a_submodule_is_refused(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "repo"
    sha = committed_app(root)
    git(root, "update-index", "--add", "--cacheinfo", f"160000,{sha},vendor/other")
    git(root, "commit", "-q", "-m", "submodule")
    tree = Tree.read(root, git(root, "rev-parse", "HEAD"))
    tree.materialize(tmp_path / "tree")
    with pytest.raises(ReleaseError, match="vendor/other is a submodule"):
        _plan.release_plan(tree, tmp_path / "tree", published_table())


def _own_case(change) -> dict[str, bytes]:
    profile = _profile()
    change(profile)
    return _own(profile)


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda p: p["services"].update(cache={"image": "redis:7"}),
         "service cache runs redis:7, which is neither built from the checkout nor a datastore table digest"),
        (lambda p: p["services"]["db"].pop("healthcheck"),
         "postgres unit db has no healthcheck"),
        (lambda p: p["services"]["db"].update(healthcheck={"disable": True, "test": ["NONE"]}),
         "postgres unit db has no healthcheck"),
        (lambda p: p["services"].update(seed={"image": p["x-backend"]["image"], "command": ["terp", "migrate", "upgrade"]}),
         "services migrate, seed each run terp migrate upgrade"),
        (lambda p: p["services"]["migrate"].update(command=["terp", "migrate", "upgrade", "--revision", "abc"]),
         "service migrate runs the migration step with --revision"),
        (lambda p: p["services"]["migrate"].update(command=["terp", "migrate", "upgrade", "--sql=yes"]),
         "service migrate runs the migration step with --sql"),
        (lambda p: p["services"]["api"]["build"].update(args={"X": "1"}),
         "service api builds with args: a release builds a service from its context and Dockerfile only"),
        (lambda p: p["services"]["api"].update(build=["not", "a", "build"]),
         "service api builds with list"),
        (lambda p: [s.update(image=f"{PROJECT}-backend-prod") for s in (p["services"]["api"], p["services"]["migrate"])],
         "builds the image 'relapp-backend-prod', which does not read the per-release tag"),
        (lambda p: p["services"]["migrate"].update(build={"context": ".", "dockerfile": "Other.prod"}),
         "the image relapp-backend-prod is built twice"),
    ],
)
def test_the_profile_is_refused_where_a_release_cannot_drive_it(tmp_path: pathlib.Path, change, expected: str) -> None:
    assert expected in _refusals(tmp_path, _own_case(change))


def test_no_migration_step_needs_exactly_one_api(tmp_path: pathlib.Path) -> None:
    profile = _profile()
    profile["services"].pop("migrate")
    profile["services"]["api"]["depends_on"].pop("migrate")
    profile["services"]["api2"] = {**profile["services"]["api"]}
    profile["services"]["api2"].pop("build")
    units = [unit for unit in json.loads(app_files()["deployment.json"])["units"] if unit["id"] != "migrate"]
    units[1]["dependsOn"] = ["db"]
    units.append({**units[1], "id": "api2"})
    message = _refusals(tmp_path, _own(profile, units))
    assert "no migration step and 2 api units" in message
    plan = _plan_of(tmp_path / "one", _own(profile | {"services": {k: v for k, v in profile["services"].items() if k != "api2"}}, units[:2]))
    assert plan.migration_step is None and plan.api == "api"


def test_a_string_build_is_its_context(tmp_path: pathlib.Path) -> None:
    profile = _profile()
    profile["services"]["api"]["build"] = "."
    files = _own(profile) | {"Dockerfile": b"FROM scratch\n"}
    plan = _plan_of(tmp_path, files)
    assert (plan.images[0].context, plan.images[0].dockerfile) == (".", "Dockerfile")


# --------------------------------------------------------------------------- the registry
def test_the_registry_is_a_host_and_a_path_and_http_is_loopback_only() -> None:
    assert build.registry("localhost:5000/rel") == ("localhost:5000", "localhost:5000/rel")
    assert build.registry("registry.example") == ("registry.example", "registry.example")
    for wrong in ("https://r.example", "r.example/x:tag", "R.example", "r.example/x@sha256:1", ""):
        with pytest.raises(ReleaseError, match="is not a registry and path"):
            build.registry(wrong)
    assert build.loopback("127.0.0.1:5000") and build.loopback("localhost")
    assert not build.loopback("registry.example:5000")


# --------------------------------------------------------------------------- the build
def _builder_runs(scratch: dict, digest: str = "sha256:" + "1" * 64) -> Runs:
    def buildx_build(argv, stdin):  # type: ignore[no-untyped-def]
        metadata = pathlib.Path(argv[argv.index("--metadata-file") + 1])
        context = pathlib.Path(argv[-1])
        scratch["context"] = sorted(p.relative_to(context).as_posix() for p in context.rglob("*") if p.is_file())
        scratch["main"] = (context / "app" / "main.py").read_bytes()
        metadata.write_text(json.dumps({"containerimage.digest": digest, "containerimage.config.digest": "sha256:" + "2" * 64}))
        return 0, b"", b""

    return (
        Runs()
        .on("docker", "buildx", "create")
        .on("docker", "buildx", "inspect", out=b"Name: x\nBuildKit version: v0.34.1\n")
        .on("docker", "buildx", "version", out=b"github.com/docker/buildx v0.30.1\n")
        .on("docker", "buildx", "build", then=buildx_build)
        .on("docker", "buildx", "rm")
    )


def test_the_build_pushes_from_the_pristine_tree_in_a_builder_of_its_own(tmp_path: pathlib.Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    sha = committed_app(root)
    (root / "app" / "main.py").write_text("an edit nobody committed", encoding="utf-8")
    (root / ".env").write_text("SECRET_KEY=never-in-a-context", encoding="utf-8")
    seen: dict = {}
    runs = _builder_runs(seen)
    monkeypatch.setattr(build, "run", runs)
    document = build.build(root, sha, "r1", "127.0.0.1:5000/rel", registry_http=True)
    assert seen["main"] == app_files()["app/main.py"], "the context is the commit, never the working copy"
    assert seen["context"] == sorted(app_files()), "exactly the commit's files: no .env, no .git"
    [create] = runs.ran("docker", "buildx", "create")
    name = create[create.index("--name") + 1]
    assert name.startswith("rel-") and f"image={build.BUILDKIT_IMAGE}" in create
    assert "network=host" in create and "--buildkitd-config" in create
    [built] = runs.ran("docker", "buildx", "build")
    assert {"--pull", "--no-cache", "--provenance=false", "--sbom=false"} <= set(built)
    assert built[built.index("--builder") + 1] == name
    assert f"SOURCE_DATE_EPOCH={Tree.read(root, sha).time}" in built
    output = built[built.index("--output") + 1]
    assert output == f"type=image,name=127.0.0.1:5000/rel/{PROJECT}-backend-prod:r1,push=true,rewrite-timestamp=true"
    assert not [part for part in built if part.startswith("--cache")], "no cache import or export"
    assert runs.ran("docker", "buildx", "rm", "--force", name)
    assert document["commit"] == sha and document["releaseTag"] == "r1"
    assert document["builder"] == {"buildkit": "v0.34.1", "buildx": "github.com/docker/buildx v0.30.1", "image": build.BUILDKIT_IMAGE}
    assert document["images"] == [{
        "name": f"{PROJECT}-backend-prod", "repository": f"127.0.0.1:5000/rel/{PROJECT}-backend-prod",
        "tag": "r1", "digest": "sha256:" + "1" * 64, "configDigest": "sha256:" + "2" * 64,
        "context": ".", "dockerfile": "Dockerfile.prod", "services": ["api", "migrate"], "web": False,
    }]


def test_the_builder_is_removed_when_a_build_fails_and_its_removal_is_held(tmp_path: pathlib.Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    sha = committed_app(root)
    runs = _builder_runs({}).on("docker", "buildx", "build", code=1, err=b"ERROR: failed to solve")
    monkeypatch.setattr(build, "run", runs)
    with pytest.raises(ReleaseError, match=r"building relapp-backend-prod failed \(exit 1\)"):
        build.build(root, sha, "r1", "registry.example/rel")
    assert runs.ran("docker", "buildx", "rm"), "the builder goes even when the build fails"
    assert "network=host" not in runs.ran("docker", "buildx", "create")[0]
    runs = _builder_runs({}).on("docker", "buildx", "rm", code=1, err=b"busy")
    monkeypatch.setattr(build, "run", runs)
    with pytest.raises(ReleaseError, match="could not be removed"):
        build.build(root, sha, "r1", "registry.example/rel")


def test_metadata_without_a_digest_and_a_builder_without_a_version_are_handled(tmp_path: pathlib.Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    sha = committed_app(root)

    def no_digest(argv, stdin):  # type: ignore[no-untyped-def]
        pathlib.Path(argv[argv.index("--metadata-file") + 1]).write_text("{}")
        return 0, b"", b""

    runs = _builder_runs({}).on("docker", "buildx", "build", then=no_digest).on("docker", "buildx", "inspect", out=b"Name: x\n")
    monkeypatch.setattr(build, "run", runs)
    with pytest.raises(ReleaseError, match="BuildKit wrote no digest for relapp-backend-prod"):
        build.build(root, sha, "r1", "registry.example/rel")


def test_the_build_refuses_before_any_builder_exists(tmp_path: pathlib.Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    files = app_files()
    files[".terp-dist/wheels/x.whl"] = b"x"
    sha = committed_app(root, files)
    runs = Runs()
    monkeypatch.setattr(build, "run", runs)
    with pytest.raises(ReleaseError, match=".terp-dist/ is committed"):
        build.build(root, sha, "r1", "registry.example/rel")
    with pytest.raises(ReleaseError, match="for a registry on this machine's loopback"):
        build.build(root, sha, "r1", "registry.example/rel", registry_http=True)
    with pytest.raises(ReleaseError, match="is not a release tag"):
        build.build(root, sha, "-bad", "registry.example/rel")
    assert runs.calls == [], "nothing was built, created or pushed"
