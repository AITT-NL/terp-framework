"""``terp release build`` and the refusals every release job repeats (ADR 0184 d9, 0187 d6).

The plan is read from the commit alone; the build runs BuildKit through docker, which a
:class:`Runs` stands in for, so what is asserted is exactly the argument lists the job hands
the builder: a builder of its own from a pinned image, ``--pull``, no cache, the pristine
tree as the context, the release tag, BuildKit's metadata, and the builder removed after.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess

import pytest
import yaml

from terp.arch.deployment import published_table
from terp.cli.release import _plan, build
from terp.cli.release._common import ReleaseError
from terp.cli.release._git import Tree
from tests.architecture.release_fixtures import NPM_LOCK, PROJECT, SITE_LOCK, Runs, app_files, committed_app, git

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
    files = _own(profile, units) | {"frontend/Dockerfile.web": b"FROM scratch\n",
                                    "frontend/package-lock.json": json.dumps(NPM_LOCK).encode()}
    plan = _plan_of(tmp_path, files)
    web = next(image for image in plan.images if image.web)
    assert (web.name, web.context, web.dockerfile, web.services, web.npm_lock) == (
        f"{PROJECT}-frontend-prod", "frontend", "frontend/Dockerfile.web", ("web",), "frontend/package-lock.json"
    )
    assert plan.npm_locks == ("frontend/package-lock.json",)
    assert "tools" not in plan.services, "a service under a compose profile is not part of the release"


def test_a_static_site_image_is_planned_from_the_site_s_own_lock(tmp_path: pathlib.Path) -> None:
    """ADR 0198 decision 4: the site's image is found from the profile, as the other two are, and
    is the one image whose SBOM reads ``site/package-lock.json``."""
    plan = _plan_of(tmp_path, app_files(site=True))
    assert [(image.name, image.context, image.dockerfile, image.services, image.web, image.npm_lock)
            for image in plan.images] == [
        (f"{PROJECT}-backend-prod", ".", "Dockerfile.prod", ("api", "migrate"), False, None),
        (f"{PROJECT}-frontend-prod", ".", "frontend/Dockerfile.prod", ("web",), True, "frontend/package-lock.json"),
        (f"{PROJECT}-site-prod", ".", "site/Dockerfile.prod", ("site",), True, "site/package-lock.json"),
    ]


def _own_with_webs(builds: dict[str, dict[str, str]], extra: dict[str, bytes]) -> dict[str, bytes]:
    """The app under ``own`` with a web unit per entry of *builds*, each built as it says."""
    profile = _profile()
    units = json.loads(app_files()["deployment.json"])["units"]
    for unit, made_from in builds.items():
        profile["services"][unit] = {"build": made_from, "image": f"{PROJECT}-{unit}-prod:{SEAM}"}
        units.append({"id": unit, "role": "web"})
    return _own(profile, units) | extra


def test_under_own_a_web_image_takes_the_lock_beside_its_dockerfile(tmp_path: pathlib.Path) -> None:
    """Under ``own`` the declaration names no recipe (``generator`` is refused beside it), so a
    site built by the app's own Dockerfile was planned with the frontend's lock: its SBOM listed
    the SPA's packages. The lock is read from where the image is built: beside its Dockerfile,
    else at the root of its build context."""
    files = _own_with_webs(
        {"web": {"context": ".", "dockerfile": "frontend/Dockerfile.prod"},
         "site": {"context": ".", "dockerfile": "site/Dockerfile.prod"},
         "docs": {"context": "docs", "dockerfile": "../build/docs.Dockerfile"}},
        {"frontend/Dockerfile.prod": b"FROM scratch\n", "frontend/package-lock.json": json.dumps(NPM_LOCK).encode(),
         "site/Dockerfile.prod": b"FROM scratch\n", "site/package-lock.json": json.dumps(SITE_LOCK).encode(),
         "build/docs.Dockerfile": b"FROM scratch\n", "docs/package-lock.json": json.dumps(SITE_LOCK).encode()},
    )
    plan = _plan_of(tmp_path, files)
    assert {image.services: (image.dockerfile, image.npm_lock) for image in plan.images if image.web} == {
        ("web",): ("frontend/Dockerfile.prod", "frontend/package-lock.json"),
        ("site",): ("site/Dockerfile.prod", "site/package-lock.json"),
        ("docs",): ("build/docs.Dockerfile", "docs/package-lock.json"),
    }
    assert plan.npm_locks == ("docs/package-lock.json", "frontend/package-lock.json", "site/package-lock.json")
    assert _plan.npm_lock_of(Tree.read(tmp_path / "repo", git(tmp_path / "repo", "rev-parse", "HEAD")),
                             ".", "Dockerfile.web") is None, "no lock at the root, beside or in the context"


def test_a_web_image_with_no_npm_lock_is_refused_naming_the_remedy(tmp_path: pathlib.Path) -> None:
    files = _own_with_webs(
        {"site": {"context": ".", "dockerfile": "site/Dockerfile.prod"}},
        {"site/Dockerfile.prod": b"FROM scratch\n", "frontend/package-lock.json": json.dumps(NPM_LOCK).encode()},
    )
    assert (
        f"the web image {PROJECT}-site-prod has no npm lock: the commit holds no "
        "site/package-lock.json and no package-lock.json, and a release reads a web image's "
        "packages from the lock it installs (allowed: a committed package-lock.json beside "
        "site/Dockerfile.prod or at the root of its build context - run `npm install` there and "
        "commit the lock it writes)"
    ) in _refusals(tmp_path, files), "another web image's lock is not this image's"


def test_a_lock_an_image_is_built_from_anywhere_is_held_to_the_path_rule(tmp_path: pathlib.Path) -> None:
    path_source = {"packages": {"": {}, "node_modules/z": {"version": "1", "resolved": "file:../z.tgz"}}}
    files = _own_with_webs(
        {"www": {"context": "www", "dockerfile": "Dockerfile"}},
        {"www/Dockerfile": b"FROM scratch\n", "www/package-lock.json": json.dumps(path_source).encode()},
    )
    assert "www/package-lock.json takes node_modules/z from a path" in _refusals(tmp_path, files)


def test_the_gate_holds_the_npm_locks_the_plan_reads(tmp_path: pathlib.Path, monkeypatch) -> None:
    """The release plan finds a web image's lock beside its Dockerfile, else in its context, so
    under own it reads locks outside frontend/ and site/. terp verify's locks check and npm audit
    read only the generator's two, and drifted from it. They now ask the plan's own rule of the
    files on disk (web_npm_locks): the same set, held here against the plan of the same commit."""
    from terp.cli import verify as verify_module
    from terp.cli.dependency_audit import run_dependency_audit_npm
    from terp.cli.locks import run_locks_check

    files = _own_with_webs(
        {"www": {"context": ".", "dockerfile": "www/Dockerfile"},
         "docs": {"context": "docs", "dockerfile": "../build/docs.Dockerfile"}},
        {"www/Dockerfile": b"FROM scratch\n", "www/package.json": b'{"name": "www"}\n',
         "www/package-lock.json": json.dumps(NPM_LOCK).encode(),
         "build/docs.Dockerfile": b"FROM scratch\n", "docs/package-lock.json": json.dumps(SITE_LOCK).encode()},
    )
    plan = _plan_of(tmp_path, files)
    on_disk = tmp_path / "tree"  # the commit written out, as the gate reads a checkout
    assert _plan.web_npm_locks(on_disk, published_table()) == plan.npm_locks == (
        "docs/package-lock.json", "www/package-lock.json"
    )
    asked: list[list[str]] = []

    def run(argv, root, *, env=None):  # type: ignore[no-untyped-def]
        asked.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(verify_module, "_run_argv", run)
    assert run_locks_check(on_disk)[0] == 0
    assert [argv[2] for argv in asked if argv[0] == "npm"] == ["docs", "www"], "each planned lock, asked of npm"
    asked.clear()
    (on_disk / "www" / "node_modules" / "react").mkdir(parents=True)  # what the lock installs
    code, output = run_dependency_audit_npm(on_disk)
    assert code == 0 and [argv[2] for argv in asked] == ["www"], output
    assert "no docs/package.json - dependency-audit-npm not applicable" in output


def test_a_service_built_from_outside_the_checkout_is_refused_and_the_gate_holds_the_rest(
    tmp_path: pathlib.Path,
) -> None:
    """Being readable refuses a declared unit's build path that leaves the checkout, but reads no
    service the declaration does not name. The plan resolved such a path against the checkout and
    raised, so ``terp release`` ended in a traceback. It is refused with the rule it breaks, and
    the gate, which asks the plan's rule, skips it and holds the locks of the images built inside."""
    files = _own_with_webs(
        {"web": {"context": ".", "dockerfile": "frontend/Dockerfile.prod"}},
        {"frontend/Dockerfile.prod": b"FROM scratch\n", "frontend/package-lock.json": json.dumps(NPM_LOCK).encode()},
    )
    profile = yaml.safe_load(files["docker-compose.prod.yml"])
    profile["services"]["tool"] = {"build": "../outside", "image": f"{PROJECT}-tool-prod:{SEAM}"}
    profile["services"]["probe"] = {
        "build": {"context": ".", "dockerfile": "/etc/Dockerfile"}, "image": f"{PROJECT}-probe-prod:{SEAM}",
    }
    files["docker-compose.prod.yml"] = yaml.safe_dump(profile, sort_keys=False).encode()
    message = _refusals(tmp_path / "release", files)
    for service, context, dockerfile, outside in (
        ("tool", "../outside", "Dockerfile", "context"), ("probe", ".", "/etc/Dockerfile", "Dockerfile"),
    ):
        assert (
            f"service {service} builds from {context!r} with the Dockerfile {dockerfile!r}, and its {outside} "
            "resolves outside the checkout: a release builds from the commit's own files alone (allowed: a "
            "build context and a Dockerfile inside the checkout)"
        ) in message
    on_disk = tmp_path / "gate"
    for path, data in files.items():
        (on_disk / path).parent.mkdir(parents=True, exist_ok=True)
        (on_disk / path).write_bytes(data)
    assert _plan.web_npm_locks(on_disk, published_table()) == ("frontend/package-lock.json",)


def test_the_plan_s_web_locks_are_none_where_a_release_would_refuse(tmp_path: pathlib.Path) -> None:
    """Undeclared, or a profile that cannot be read: the gate holds the generator's two alone."""
    assert _plan.web_npm_locks(tmp_path, published_table()) == ()
    files = app_files(web=True)
    files.pop("docker-compose.prod.yml")
    for path, data in files.items():
        (tmp_path / "app" / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "app" / path).write_bytes(data)
    assert _plan.web_npm_locks(tmp_path / "app", published_table()) == ()


def test_sign_refuses_to_describe_a_web_image_from_no_lock(tmp_path: pathlib.Path) -> None:
    """The plan refuses such an image first; ``sign`` refuses again rather than build the empty
    SBOM it used to, should a lock be missing all the same."""
    sha = committed_app(tmp_path / "repo", app_files(web=True))
    tree = Tree.read(tmp_path / "repo", sha)

    def image(lock: str | None) -> _plan.Image:
        return _plan.Image(f"{PROJECT}-frontend-prod", ".", "frontend/Dockerfile.prod", ("web",), True, lock)

    message = f"the web image {PROJECT}-frontend-prod has no npm lock in this commit, so its SBOM would list no package"
    for lock in (None, "site/package-lock.json"):  # none planned, and one the commit does not hold
        with pytest.raises(ReleaseError, match=re.escape(message)):
            _plan.web_packages(tree, image(lock))
    assert _plan.web_packages(tree, image("frontend/package-lock.json")) == [("react", "19.0.0")]


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
        (lambda f: f.update({"site/package-lock.json": json.dumps({"packages": {"": {}, "node_modules/y": {"version": "1", "link": True}}}).encode()}),
         "site/package-lock.json takes node_modules/y from a path"),
    ],
)
def test_the_commit_is_refused_from_data(tmp_path: pathlib.Path, change, expected: str) -> None:
    files = app_files()
    change(files)
    assert expected in _refusals(tmp_path, files)


def test_a_site_lock_npm_cannot_read_is_refused_by_its_own_path(tmp_path: pathlib.Path) -> None:
    files = app_files()
    files["site/package-lock.json"] = b"[]"
    with pytest.raises(ReleaseError, match="^site/package-lock.json is not a lockfile npm ci reads"):
        _plan_of(tmp_path, files)


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
