"""The conformance suite's image and its record in the release manifest (ADR 0219).

The generator renders the suite's Dockerfile where the checkout commits the suite's lock; the
release plan builds it as an image no service runs, named after the project and driving the
app's own web tier; ``sign`` checks it in the registry as every image, describes it from the
suite's lock, keeps it out of the backend's comparison and of the deployment, and records
``outputs.suite``; and ``terp promote``'s reader holds that record to its form.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import Any

import pytest

from terp.arch.deployment import published_tables, reader
from terp.arch.deployment.generator import (
    OWNED_PATHS,
    SUITE_COMMAND,
    SUITE_DOCKERFILE,
    SUITE_LOCK,
    SUITE_READS,
    generate,
)
from terp.arch.deployment.render_check import check
from terp.arch.deployment.tables import TableError, read_base_images
from terp.cli.release import _render as _signer_render
from terp.cli.release import sign
from terp.cli.release._common import ReleaseError, write_document
from terp.cli.release._git import Tree
from terp.cli.release._plan import release_plan
from terp.cli.release.manifest import parse
from tests.architecture.release_fixtures import PROJECT, app_files, committed_app
from tests.architecture.test_release_image import layer
from tests.architecture.test_release_sign import REGISTRY, Release, _sbom_purls

SUITE = f"{PROJECT}-conformance-prod"
FRONTEND = f"{PROJECT}-frontend-prod"


def _declared(files: dict[str, bytes]) -> reader.Declaration:
    tables = published_tables()
    declared, findings = reader.read(json.loads(files["deployment.json"]), tables.datastores, tables.system_packages)
    assert findings == [] and declared is not None
    return declared


# ---- the generator -----------------------------------------------------------------------


def test_the_suite_s_dockerfile_is_rendered_where_its_lock_is_committed_alone() -> None:
    files = app_files(web=True)
    declared = _declared(files)
    with_lock, refused = generate(declared, PROJECT, tables=published_tables(), frontend_lock=True, conformance_lock=True)
    without, _ = generate(declared, PROJECT, tables=published_tables(), frontend_lock=True)
    assert refused == []
    assert SUITE_DOCKERFILE in with_lock and SUITE_DOCKERFILE not in without
    assert SUITE_DOCKERFILE in OWNED_PATHS
    assert {path: data for path, data in with_lock.items() if path != SUITE_DOCKERFILE} == without, (
        "the suite changes no other file"
    )


def test_the_suite_s_dockerfile_builds_on_the_pinned_playwright_and_runs_its_command() -> None:
    """On Playwright's own image by digest, refusing another @playwright/test; as the image's
    unprivileged user; and running the command the manifest records, with nothing before it."""
    tables = published_tables()
    files, _ = generate(_declared(app_files(web=True)), PROJECT, tables=tables, frontend_lock=True, conformance_lock=True)
    text = files[SUITE_DOCKERFILE].decode("ascii")
    base = tables.base_images.get("playwright")
    assert f"FROM {base.image}\n" in text and f"# {base.tag}\n" in text
    assert base.image.startswith("mcr.microsoft.com/playwright@sha256:")
    version = tables.base_images.playwright_version
    assert version == "1.62.1"
    assert f'if [ "$found" != "{version}" ]' in text and f"@playwright/test@{version}" in text
    assert "USER pwuser\n" in text and "npm ci --ignore-scripts" in text
    assert text.rstrip().endswith("CMD " + json.dumps(list(SUITE_COMMAND)))
    assert "@@" not in text, "every placeholder is filled"


@pytest.mark.parametrize("tag", ["mcr.microsoft.com/playwright:latest", "mcr.microsoft.com/playwright:v1.62-noble",
                                 "docker.io/playwright:v1.62.1-noble"])
def test_a_playwright_base_whose_tag_names_no_release_is_refused(tag: str) -> None:
    raw = json.loads((pathlib.Path(sys.modules["terp.arch.deployment.tables"].__file__).parent / "base-images.json").read_text())
    raw["images"]["playwright"]["tag"] = tag
    with pytest.raises(TableError, match="names no Playwright release"):
        read_base_images(raw)


def test_the_render_check_says_why_no_suite_is_rendered_and_holds_one_that_is(tmp_path: pathlib.Path) -> None:
    files = app_files(suite=True)
    for path, data in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(data)
    tables = published_tables()
    declared = _declared(files)
    assert check(tmp_path, declared, tables).findings == []
    (tmp_path / SUITE_DOCKERFILE).unlink()
    missing = [finding.message for finding in check(tmp_path, declared, tables).findings]
    assert any(SUITE_DOCKERFILE in message for message in missing), missing
    (tmp_path / SUITE_DOCKERFILE).write_bytes(files[SUITE_DOCKERFILE])
    (tmp_path / SUITE_LOCK).unlink()
    stray = [finding.message for finding in check(tmp_path, declared, tables).findings]
    assert any("commits no conformance/package-lock.json" in message for message in stray), stray


_OLD_GENERATOR = '''
OWNED_PATHS = ("Dockerfile.prod", "frontend/Dockerfile.prod", "site/Dockerfile.prod", "docker-compose.prod.yml")
FRONTEND_LOCK = "frontend/package-lock.json"


def generate(declaration, name, *, tables, frontend_lock, site_lock=False):
    return {"docker-compose.prod.yml": b"rendered"}, []
'''


def test_the_signer_hands_the_suite_s_lock_only_to_a_generator_that_reads_one(tmp_path: pathlib.Path) -> None:
    """A commit that pins a terp-arch from before ADR 0219 renders with that release's
    generator, whose ``generate`` takes no ``conformance_lock``: the call is the one it answers."""
    package = tmp_path / "arch" / "terp" / "arch" / "deployment"
    package.mkdir(parents=True)
    for parent in (tmp_path / "arch" / "terp", tmp_path / "arch" / "terp" / "arch"):
        (parent / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text(
        "class Declaration: ...\ndef published_tables():\n    return None\n"
        "def readable(root):\n    return Declaration(), []\n",
        encoding="utf-8",
    )
    (package / "generator.py").write_text(_OLD_GENERATOR, encoding="utf-8")
    (package / "render_check.py").write_text("def project_name(root):\n    return 'demo', []\n", encoding="utf-8")
    tree = tmp_path / "tree"
    (tree / "conformance").mkdir(parents=True)
    (tree / "conformance" / "package-lock.json").write_text("{}", encoding="utf-8")
    run = subprocess.run(
        [sys.executable, "-I", "-c", _signer_render._RENDER, str(tmp_path / "arch"), str(tmp_path), str(tree)],
        capture_output=True, text=True, check=False,
    )
    assert run.returncode == 0, run.stderr
    assert list(json.loads(run.stdout)["files"]) == ["docker-compose.prod.yml"]


# ---- the plan ----------------------------------------------------------------------------


def _plan(tmp_path: pathlib.Path, files: dict[str, bytes]) -> Any:
    repo = tmp_path / "repo"
    sha = committed_app(repo, files)
    tree = Tree.read(repo, sha)
    root = tmp_path / "root"
    tree.materialize(root)
    return release_plan(tree, root, published_tables().datastores)


def test_a_commit_with_its_suite_plans_an_image_no_service_runs(tmp_path: pathlib.Path) -> None:
    plan = _plan(tmp_path, app_files(suite=True))
    suite = plan.suite
    assert suite is not None and suite.name == SUITE and suite.suite and not suite.web
    assert (suite.context, suite.dockerfile, suite.npm_lock, suite.services) == (".", SUITE_DOCKERFILE, SUITE_LOCK, ())
    assert plan.suite_target == "web", "the app's own web tier"
    assert SUITE_LOCK in plan.npm_locks, "the manifest records the lock the image installs"
    assert plan.image_of("web").name == FRONTEND


def test_a_commit_without_its_suite_plans_none(tmp_path: pathlib.Path) -> None:
    plan = _plan(tmp_path, app_files(web=True))
    assert plan.suite is None and plan.suite_target is None


def test_a_static_site_is_not_the_web_tier_the_suite_drives(tmp_path: pathlib.Path) -> None:
    files = app_files(site=True)
    suite = app_files(suite=True)
    files |= {path: suite[path] for path in suite if path.startswith("conformance/")}
    plan = _plan(tmp_path, files)
    assert plan.suite_target == "web"


def _refused(tmp_path: pathlib.Path, files: dict[str, bytes]) -> str:
    with pytest.raises(ReleaseError) as refused:
        _plan(tmp_path, files)
    return str(refused.value)


def test_a_suite_whose_lock_is_not_committed_is_refused(tmp_path: pathlib.Path) -> None:
    files = app_files(suite=True)
    del files[SUITE_LOCK]
    said = _refused(tmp_path, files)
    assert f"{SUITE_DOCKERFILE} is committed and {SUITE_LOCK}" in said and "npm --prefix conformance install" in said


def test_a_suite_lock_that_takes_a_package_from_a_path_is_refused(tmp_path: pathlib.Path) -> None:
    files = app_files(suite=True)
    lock = json.loads(files[SUITE_LOCK])
    lock["packages"]["node_modules/local"] = {"version": "1.0.0", "resolved": "file:../local"}
    files[SUITE_LOCK] = json.dumps(lock).encode()
    assert "from a path" in _refused(tmp_path, files)


def test_a_project_name_that_makes_no_image_name_is_refused(tmp_path: pathlib.Path) -> None:
    files = app_files(suite=True)
    files["pyproject.toml"] = files["pyproject.toml"].replace(f'name = "{PROJECT}"'.encode(), b'name = "Rel App"')
    assert "makes no image name" in _refused(tmp_path, files)


def test_a_suite_image_a_service_also_builds_is_refused(tmp_path: pathlib.Path) -> None:
    files = app_files(suite=True)
    files["docker-compose.prod.yml"] = files["docker-compose.prod.yml"].replace(
        f"{PROJECT}-frontend-prod:".encode(), f"{SUITE}:".encode()
    )
    files["deployment.json"] = json.dumps({**json.loads(files["deployment.json"]), "build": "own"}).encode()
    assert "which a service of the profile also builds" in _refused(tmp_path, files)


@pytest.mark.parametrize("units", [0, 2], ids=["no-web-unit", "two-web-units"])
def test_a_suite_with_no_one_web_unit_of_the_app_s_own_is_refused(tmp_path: pathlib.Path, units: int) -> None:
    files = app_files(suite=True)
    declaration = json.loads(files["deployment.json"])
    declaration["build"] = "own"
    if units == 0:
        declaration["units"] = [unit for unit in declaration["units"] if unit["role"] != "web"]
    else:
        declaration["units"].append({"id": "admin", "role": "web"})
    files["deployment.json"] = json.dumps(declaration).encode()
    assert f"this declaration has {units} web units of its own" in _refused(tmp_path, files)


# ---- sign --------------------------------------------------------------------------------


def _push(release: Release, name: str, dockerfile: str, services: list[str], web: bool) -> dict[str, Any]:
    digest = release.registry.push_image([layer(("srv/" + name, name.encode()))])
    config = json.loads(release.registry.manifests[digest][1])["config"]["digest"]
    release.registry.repo_tags[(f"rel/{name}", "r1")] = digest
    return {"name": name, "repository": f"{REGISTRY}/{name}", "tag": "r1", "digest": digest,
            "configDigest": config, "context": ".", "dockerfile": dockerfile, "services": services, "web": web}


def _signed_with_suite(tmp_path: pathlib.Path, monkeypatch) -> tuple[Release, dict[str, Any], dict[str, Any]]:
    release = Release(tmp_path, monkeypatch, app_files(suite=True))
    backend = json.loads(release.build_doc.read_text())["images"][0]
    frontend = _push(release, FRONTEND, "frontend/Dockerfile.prod", ["web"], True)
    suite = _push(release, SUITE, SUITE_DOCKERFILE, [], False)
    write_document(release.build_doc, {"terpReleaseBuild": 1, "commit": release.sha, "releaseTag": "r1",
                                       "platform": "linux/amd64", "builder": {}, "images": [backend, frontend, suite]})
    release.sign()
    return release, parse((tmp_path / "out" / sign.MANIFEST).read_bytes().strip()), suite


def test_sign_records_the_suite_and_runs_nothing_of_it(tmp_path: pathlib.Path, monkeypatch) -> None:
    release, manifest, suite = _signed_with_suite(tmp_path, monkeypatch)
    out = manifest["outputs"]
    assert out["suite"] == {"image": SUITE, "command": list(SUITE_COMMAND), "target": "web", "reads": SUITE_READS}
    assert out["images"][SUITE]["digest"] == suite["digest"]
    reference = f"{REGISTRY}/{SUITE}@{suite['digest']}"
    assert reference not in out["services"].values() and reference not in out["units"].values()
    images = {service["image"] for service in out["deployment"]["services"]}
    assert reference not in images, "no unit of the deployment runs the suite"
    assert [task for task, _ in release.tasks].count("image") == 1, "only the backend image is read"
    assert _sbom_purls(tmp_path, SUITE) == ["pkg:npm/%40playwright/test@1.62.1", "pkg:npm/%40terpjs/conformance@0.43.0"]
    given = manifest["inputs"]
    assert SUITE_LOCK in [lock["path"] for lock in given["locks"]]
    assert any(base["image"].startswith("mcr.microsoft.com/playwright@") for base in given["baseImages"])
    assert SUITE_DOCKERFILE in given["generator"]["files"]


def test_the_build_must_push_the_suite_the_commit_plans(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch, app_files(suite=True))
    backend = json.loads(release.build_doc.read_text())["images"][0]
    frontend = _push(release, FRONTEND, "frontend/Dockerfile.prod", ["web"], True)
    write_document(release.build_doc, {"terpReleaseBuild": 1, "commit": release.sha, "releaseTag": "r1",
                                       "platform": "linux/amd64", "builder": {}, "images": [backend, frontend]})
    with pytest.raises(ReleaseError, match=f"this commit builds .*{SUITE}"):
        release.sign()


# ---- the manifest's reader ---------------------------------------------------------------


def _with_suite(manifest: dict[str, Any], **changes: Any) -> bytes:
    carried = json.loads(json.dumps(manifest))
    carried["outputs"]["suite"].update(changes)
    return json.dumps(carried).encode()


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"extra": 1}, "holds other fields"),
        ({"image": "nowhere"}, "not an image the release built"),
        ({"image": FRONTEND}, "not an image the release built that no service runs"),
        ({"command": []}, "outputs.suite.command is not a non-empty list"),
        ({"command": ["ok", ""]}, "outputs.suite.command is not a non-empty list"),
        ({"target": 7}, "outputs.suite.target"),
        ({"reads": {"address": "A", "email": "B"}}, "outputs.suite.reads is not three"),
        ({"reads": {"address": "A", "email": "B", "password": "1x"}}, "outputs.suite.reads is not three"),
        ({"reads": {"address": "A", "email": "A", "password": "C"}}, "outputs.suite.reads is not three"),
    ],
)
def test_the_reader_refuses_a_suite_record_of_another_form(
    tmp_path: pathlib.Path, monkeypatch, change: dict[str, Any], said: str
) -> None:
    _release, manifest, _suite = _signed_with_suite(tmp_path, monkeypatch)
    with pytest.raises(ReleaseError, match=said):
        parse(_with_suite(manifest, **change))


def test_the_reader_refuses_a_suite_record_that_is_no_object(tmp_path: pathlib.Path, monkeypatch) -> None:
    _release, manifest, _suite = _signed_with_suite(tmp_path, monkeypatch)
    carried = json.loads(json.dumps(manifest))
    carried["outputs"]["suite"] = ["not", "an", "object"]
    with pytest.raises(ReleaseError, match="outputs.suite is missing"):
        parse(json.dumps(carried).encode())
