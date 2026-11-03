"""``terp release sign``: the operator's toolchain checks the release as data, then signs it.

ADR 0187 decision 6. Here the registry and the sandbox are stood in for (the Docker lane runs
them for real); the tree, git, the pinned ``terp-arch`` wheel, its render in a process of its
own, the comparison, the manifest and the DSSE signature are all real. The app fails on
import, and ``sign`` signs it: nothing of the app runs.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from terp.cli.release import _render, dsse, sign
from terp.cli.release._common import ReleaseError, canonical, write_document
from terp.cli.release._git import Tree
from terp.cli.release.manifest import parse
from tests.architecture.release_fixtures import PROJECT, TOOLCHAIN, app_files, committed_app, git
from tests.architecture.test_release_compare import faithful
from tests.architecture.test_release_dsse import pem_private, pem_public
from tests.architecture.test_release_image import FakeRegistry, layer
from tests.architecture.test_release_render import build_wheel, table

REGISTRY = "127.0.0.1:5000/rel"
NAME = f"{PROJECT}-backend-prod"
ASSURANCE = {"terp_assurance": 1, "ok": True, "lanes": []}
SCHEDULES = [{"name": "nightly", "cron": "0 3 * * *", "job": "sync"}]


class Release:
    """One commit, its pushed image in a fake registry, and the build and gate documents."""

    def __init__(self, tmp_path: pathlib.Path, monkeypatch, files: dict[str, bytes] | None = None) -> None:
        self.tmp = tmp_path
        self.repo = tmp_path / "repo"
        self.sha = committed_app(self.repo, files)
        self.tree = Tree.read(self.repo, self.sha)
        monkeypatch.setattr(_render, "FLOOR", TOOLCHAIN)
        wheel = build_wheel(tmp_path / "index")
        self.releases = table(tmp_path, wheel)
        self.registry = FakeRegistry()
        self.digest = self.registry.push_image([layer(("srv/app/main.py", b"x"))], tag="r1")
        self.config_digest = json.loads(self.registry.manifests[self.digest][1])["config"]["digest"]
        monkeypatch.setattr(sign, "egress_getter", lambda host, http: self.registry)
        self.answer = faithful(self.tree)
        self.answer.update(digest=self.digest, configDigest=self.config_digest)
        self.scan = {"database": "https://osv.example", "queried": 3, "vulnerable": {f"pkg:pypi/terp-cli@{TOOLCHAIN}": ["GHSA-x"]}}
        self.secrets: dict = {"tool": "gitleaks", "version": "8.30.1", "findings": []}
        self.tasks: list[tuple[str, dict]] = []
        monkeypatch.setattr(sign, "sandboxed", self._sandboxed)
        self.key = ed25519.Ed25519PrivateKey.generate()
        (tmp_path / "key.pem").write_bytes(pem_private(self.key))
        (tmp_path / "key.pub").write_bytes(pem_public(self.key))
        self.build_doc = tmp_path / "build.json"
        self.gate_doc = tmp_path / "gate.json"
        self.write_build()
        self.write_gate()

    def _sandboxed(self, task: str, payload: dict) -> dict:
        self.tasks.append((task, payload))
        return {"image": self.answer, "scan": self.scan, "secrets": self.secrets}[task]

    def write_build(self, **changes) -> None:  # type: ignore[no-untyped-def]
        image = {"name": NAME, "repository": f"{REGISTRY}/{NAME}", "tag": "r1", "digest": self.digest,
                 "configDigest": self.config_digest, "context": ".", "dockerfile": "Dockerfile.prod",
                 "services": ["api", "migrate"], "web": False} | changes
        write_document(self.build_doc, {"terpReleaseBuild": 1, "commit": self.sha, "releaseTag": "r1",
                                        "platform": "linux/amd64", "builder": {"buildkit": "v0.34.1"}, "images": [image]})

    def write_gate(self, **changes) -> None:  # type: ignore[no-untyped-def]
        write_document(self.gate_doc, {"terpReleaseGate": 1, "commit": self.sha, "assurance": ASSURANCE,
                                       "schedules": SCHEDULES, "image": "x"} | changes)

    def sign(self, **options):  # type: ignore[no-untyped-def]
        options = {"hosts": "separated", "sign_key": self.tmp / "key.pem", "test_key": True,
                   "releases": self.releases, "index": str(self.tmp / "index"), "registry_http": True} | options
        return sign.sign(self.repo, self.sha, "r1", REGISTRY, self.build_doc, self.gate_doc, self.tmp / "out", **options)


def _import_watch() -> list[str]:
    """Every import of the app's own modules while a test watches; an audit hook stays installed."""
    imported: list[str] = []
    state = {"on": True}

    def hook(event: str, args: tuple) -> None:  # type: ignore[type-arg]
        if state["on"] and event == "import" and str(args[0]).split(".")[0] in ("app", "control_plane"):
            imported.append(str(args[0]))

    sys.addaudithook(hook)
    imported.append("")  # the hook is installed
    imported.pop()
    _import_watch.stop = lambda: state.update(on=False)  # type: ignore[attr-defined]
    return imported


def test_sign_signs_a_release_whose_app_fails_on_import_and_runs_none_of_it(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    imported = _import_watch()
    try:
        done = release.sign()
    finally:
        _import_watch.stop()  # type: ignore[attr-defined]
    assert imported == [], f"sign imported the app's own modules: {imported}"
    envelope = (tmp_path / "out" / sign.ENVELOPE).read_bytes()
    payload, keyid = dsse.verify(envelope, [dsse.load_public_key(pem_public(release.key))])
    assert keyid == done["keyid"] and payload + b"\n" == (tmp_path / "out" / sign.MANIFEST).read_bytes()
    manifest = parse(payload)
    given, out, collected = manifest["inputs"], manifest["outputs"], manifest["collected"]
    assert given["commit"] == {"sha": release.sha, "tree": release.tree.tree}
    assert given["projectRoot"] == "." and given["developmentProfile"] == "docker-compose.yml"
    assert given["releaseTag"] == "r1" and given["build"] == "generated" and given["platform"] == "linux/amd64"
    assert given["toolchain"] == {"signer": given["toolchain"]["signer"], "terpCli": TOOLCHAIN, "terpArch": TOOLCHAIN}
    assert given["spec"]["release"] == "0.40.0" and len(given["spec"]["schemaSha256"]) == 64
    assert given["generator"]["version"] == TOOLCHAIN and given["generator"]["project"] == PROJECT
    assert sorted(given["generator"]["files"]) == ["Dockerfile.prod", "docker-compose.prod.yml"]
    assert given["declaration"]["content"] == app_files()["deployment.json"].decode()
    assert [item["path"] for item in given["profiles"]] == ["docker-compose.prod.yml"]
    assert given["datastores"] == {"kinds": {"postgres": {"role": "database", "versions": {
        "17": "postgres@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24"}}}}
    assert given["buildArgs"] == {"SOURCE_DATE_EPOCH": release.tree.time}, "no TERP_VERSION: no label reads it"
    assert [lock["path"] for lock in given["locks"]] == ["uv.lock"]
    assert {base["image"].split("@")[0] for base in given["baseImages"]} == {"ghcr.io/astral-sh/uv", "python"}
    assert given["fetches"]["baseImageRegistries"] == ["docker.io", "ghcr.io"]
    assert given["fetches"]["python"] == given["fetches"]["buildBackend"] == ["https://pypi.org/simple"]
    image = out["images"][NAME]
    assert image["digest"] == release.digest and image["imageId"] == release.config_digest
    assert image["vulnerabilities"] == {f"pkg:pypi/terp-cli@{TOOLCHAIN}": ["GHSA-x"]}
    assert out["services"]["api"] == out["services"]["migrate"] == f"{REGISTRY}/{NAME}@{release.digest}"
    assert out["units"]["db"].startswith("postgres@sha256:") and out["units"]["api"] == out["services"]["api"]
    assert out["secretScan"] == {"tool": "gitleaks", "version": "8.30.1", "findings": 0}
    assert "migrationHeads" not in collected and "heads" not in json.dumps(out)
    assert collected == {"schedules": SCHEDULES, "assurance": ASSURANCE, "hosts": "separated",
                         "build": {"builder": {"buildkit": "v0.34.1"}, "images": [
                             {"name": NAME, "digest": release.digest, "configDigest": release.config_digest}]}}
    packages = json.loads((tmp_path / "out" / f"packages-{NAME}.json").read_text())
    assert packages == [[PROJECT, "0.1.0"], ["terp-arch", TOOLCHAIN], ["terp-cli", TOOLCHAIN]]
    sbom = json.loads((tmp_path / "out" / f"sbom-{NAME}.cdx.json").read_text())
    assert sbom["bomFormat"] == "CycloneDX" and {c["purl"] for c in sbom["components"]} >= {f"pkg:pypi/terp-cli@{TOOLCHAIN}"}
    [image_task] = [payload for task, payload in release.tasks if task == "image"]
    assert image_task["base"].startswith("python@sha256:"), "the compile runs in the Dockerfile's own pinned base"
    assert "key" not in json.dumps(image_task) and str(tmp_path / "key.pem") not in json.dumps(release.tasks)


def test_two_signs_of_one_commit_record_the_same_inputs(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    release.sign()
    first = parse((tmp_path / "out" / sign.MANIFEST).read_bytes().strip())["inputs"]
    sign.sign(release.repo, release.sha, "r1", REGISTRY, release.build_doc, release.gate_doc, tmp_path / "out2",
              hosts="separated", sign_key=tmp_path / "key.pem", test_key=True, releases=release.releases,
              index=str(tmp_path / "index"), registry_http=True)
    second = parse((tmp_path / "out2" / sign.MANIFEST).read_bytes().strip())["inputs"]
    assert canonical(first) == canonical(second)


def test_a_web_image_is_described_from_the_frontend_lock(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch, app_files(web=True))
    web = f"{PROJECT}-frontend-prod"
    web_digest = release.registry.push_image([layer(("usr/share/nginx/html/index.html", b"<html>"))])
    web_config = json.loads(release.registry.manifests[web_digest][1])["config"]["digest"]
    release.registry.repo_tags[(f"rel/{web}", "r1")] = web_digest
    backend = json.loads(release.build_doc.read_text())["images"][0]
    write_document(release.build_doc, {
        "terpReleaseBuild": 1, "commit": release.sha, "releaseTag": "r1", "platform": "linux/amd64", "builder": {},
        "images": [backend, {"name": web, "repository": f"{REGISTRY}/{web}", "tag": "r1", "digest": web_digest,
                             "configDigest": web_config, "context": ".", "dockerfile": "frontend/Dockerfile.prod",
                             "services": ["web"], "web": True}],
    })
    release.sign()
    manifest = parse((tmp_path / "out" / sign.MANIFEST).read_bytes().strip())
    assert manifest["outputs"]["images"][web]["web"] is True
    assert manifest["outputs"]["services"]["web"] == f"{REGISTRY}/{web}@{web_digest}"
    sbom = json.loads((tmp_path / "out" / f"sbom-{web}.cdx.json").read_text())
    assert [c["purl"] for c in sbom["components"]] == ["pkg:npm/react@19.0.0"]
    assert [task for task, _ in release.tasks].count("image") == 1, "only the backend image is read"
    assert any(lock["path"] == "frontend/package-lock.json" for lock in manifest["inputs"]["locks"])
    assert manifest["inputs"]["fetches"]["npm"] == ["registry.npmjs.org"]
    assert sorted(manifest["inputs"]["generator"]["files"]) == ["Dockerfile.prod", "docker-compose.prod.yml", "frontend/Dockerfile.prod"]


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({"test_key": False}, "--sign-key puts a private key in this process"),
        ({"sign_key": None}, "sign with exactly one of --signer"),
        ({"signer": ["x"]}, "sign with exactly one of --signer"),
        ({"sign_key": None, "signer": ["x"]}, "--signer needs --public-key"),
        ({"hosts": "same"}, "--hosts is 'same'"),
    ],
)
def test_the_signing_options_are_refused_unless_honest(tmp_path: pathlib.Path, monkeypatch, options, expected) -> None:
    release = Release(tmp_path, monkeypatch)
    with pytest.raises(ReleaseError, match=expected):
        release.sign(**options)
    assert release.tasks == [] and not (tmp_path / "out").exists()


def test_the_production_signer_is_held_to_the_public_key_it_was_given(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    script = tmp_path / "signer.py"
    script.write_text(
        "import base64, json, sys\n"
        "from cryptography.hazmat.primitives import serialization\n"
        "from terp.cli.release import dsse\n"
        f"key = serialization.load_pem_private_key(open({str(tmp_path / 'key.pem')!r}, 'rb').read(), None)\n"
        "print(json.dumps({'keyid': dsse.keyid(key.public_key()), 'sig': base64.b64encode(key.sign(sys.stdin.buffer.read())).decode()}))\n",
        encoding="utf-8",
    )
    done = release.sign(sign_key=None, test_key=False, signer=[sys.executable, str(script)], public_key=tmp_path / "key.pub")
    assert done["keyid"] == dsse.keyid(dsse.load_public_key(pem_public(release.key)))
    other = ed25519.Ed25519PrivateKey.generate()
    (tmp_path / "other.pub").write_bytes(pem_public(other))
    with pytest.raises(ReleaseError, match="no signature of the envelope verifies"):
        release.sign(sign_key=None, test_key=False, signer=[sys.executable, str(script)], public_key=tmp_path / "other.pub")


def test_documents_of_another_commit_and_a_failed_gate_are_refused(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    release.write_gate(assurance={**ASSURANCE, "ok": False})
    with pytest.raises(ReleaseError, match="release-assurance claim does not hold"):
        release.sign()
    release.write_gate(commit="0" * 40)
    with pytest.raises(ReleaseError, match="the gate document is of 0+"):
        release.sign()
    with pytest.raises(ReleaseError, match="for a registry on this machine's loopback"):
        sign.sign(release.repo, release.sha, "r1", "registry.example/rel", release.build_doc, release.gate_doc,
                  tmp_path / "out", hosts="shared", sign_key=tmp_path / "key.pem", test_key=True, registry_http=True)


def test_the_registry_credentials_reach_the_registry_and_the_sandbox(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    (tmp_path / "creds.json").write_text('{"username": "u", "password": "p"}', encoding="utf-8")
    release.sign(registry_credentials=tmp_path / "creds.json")
    [image_task] = [payload for task, payload in release.tasks if task == "image"]
    assert image_task["credentials"] == ["u", "p"]


def _change_files(change) -> dict[str, bytes]:  # type: ignore[no-untyped-def]
    files = app_files()
    change(files)
    return files


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda f: f.update({"docker-compose.prod.yml": f["docker-compose.prod.yml"] + b"# an edit\n"}),
         "the committed docker-compose.prod.yml is not the render of deployment.json"),
        (lambda f: f.update({"frontend/Dockerfile.prod": b"FROM scratch\n"}),
         "the committed frontend/Dockerfile.prod is not the render"),
        (lambda f: f.update({"uv.lock": f["uv.lock"].replace(b'name = "terp-arch"', b'name = "terp-arch-x"')}),
         "pins no single terp-cli and terp-arch"),
        (lambda f: f.update({".terp-dist/x": b"x"}), ".terp-dist/ is committed"),
        (lambda f: f.update({"pyproject.toml": f["pyproject.toml"].replace(b'packages = ["app", "control_plane"]', b'sources = ["src"]')}),
         "a shape sign cannot compare"),
        (lambda f: f.update({"pyproject.toml": f["pyproject.toml"].replace(b'version = "0.1.0"\n', b"")}),
         "names no \\[project\\] name and version"),
    ],
)
def test_the_commit_is_refused_by_what_its_tree_says(tmp_path: pathlib.Path, monkeypatch, change, expected: str) -> None:
    release = Release(tmp_path, monkeypatch, _change_files(change))
    with pytest.raises(ReleaseError, match=expected):
        release.sign()
    assert not (tmp_path / "out" / sign.ENVELOPE).exists()


def test_a_declaration_the_pinned_generator_refuses_is_refused(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    monkeypatch.setattr(sign, "render", lambda pinned, root, scratch: ({}, [], ["a refusal of the pinned generator"]))
    with pytest.raises(ReleaseError, match="cannot render this commit's declaration:\n- a refusal of the pinned generator"):
        release.sign()


def test_a_declaration_written_against_a_newer_standard_is_refused(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    monkeypatch.setattr(sign, "SPEC_RELEASE", "0.39.0")
    with pytest.raises(ReleaseError, match="Terp Standard 0.40.0, newer than 0.39.0"):
        release.sign()


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"name": "other"}, "the build pushed other, and this commit builds relapp-backend-prod"),
        ({"repository": "127.0.0.1:5000/elsewhere/x"}, "not 127.0.0.1:5000/rel/relapp-backend-prod:r1"),
        ({"tag": "r2"}, "not 127.0.0.1:5000/rel/relapp-backend-prod:r1"),
        ({"configDigest": "sha256:" + "0" * 64}, "has another configuration than the build recorded"),
        ({"digest": "sha256:" + "0" * 64}, "has no manifest"),
    ],
)
def test_the_pushed_digests_are_checked_in_the_registry(tmp_path: pathlib.Path, monkeypatch, changes, expected: str) -> None:
    release = Release(tmp_path, monkeypatch)
    release.write_build(**changes)
    with pytest.raises(ReleaseError, match=expected):
        release.sign()


def test_a_tag_moved_since_the_build_and_an_index_are_refused(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    release.registry.tags["r1"] = release.registry.push_image([layer(("other", b"1"))])
    with pytest.raises(ReleaseError, match="no longer names"):
        release.sign()
    index = json.dumps({"mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [
        {"digest": release.digest, "platform": {"os": "linux", "architecture": "amd64"}}]}).encode()
    import hashlib

    index_digest = "sha256:" + hashlib.sha256(index).hexdigest()
    release.registry.manifests[index_digest] = ("application/vnd.oci.image.index.v1+json", index)
    release.write_build(digest=index_digest)
    with pytest.raises(ReleaseError, match="is an index, and a release pushes one image per name"):
        release.sign()


def test_an_image_whose_app_layer_differs_from_the_tree_is_refused(tmp_path: pathlib.Path, monkeypatch) -> None:
    from terp.cli.release._image import Node

    release = Release(tmp_path, monkeypatch)
    release.answer["nodes"]["srv/app/main.py"] = Node("file", "f" * 64, 9).as_data()
    with pytest.raises(ReleaseError, match="is not this commit's build:\n- /srv/app/main.py is not the tree's app/main.py"):
        release.sign()
    assert not (tmp_path / "out" / sign.ENVELOPE).exists()


def test_a_secret_in_the_history_is_never_signed_over(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    release.secrets["findings"] = [{"rule": "aws", "file": "x", "commit": "c"}]
    with pytest.raises(ReleaseError, match="gitleaks finds 1 secrets in the history"):
        release.sign()
    assert not (tmp_path / "out" / sign.ENVELOPE).exists()


def test_the_scan_is_handed_the_acknowledgements_the_tree_commits(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch, app_files() | {".gitleaksignore": b"c:x:aws:1\n"})
    release.sign()
    [secrets] = [payload for task, payload in release.tasks if task == "secrets"]
    assert secrets["ignore"] == "c:x:aws:1\n" and secrets["sha"] == release.sha and secrets["gitleaks"] == "gitleaks"


def test_a_signer_installed_from_a_source_checkout_names_version_0(monkeypatch) -> None:
    import importlib.metadata

    def missing(name):  # type: ignore[no-untyped-def]
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(sign.importlib.metadata, "version", missing)
    assert sign._signer_version() == "0"


def test_the_plan_not_the_build_says_which_image_is_compared(tmp_path: pathlib.Path, monkeypatch) -> None:
    """A build document that calls the backend image the web tier gains nothing: the commit's
    own plan says which image runs the app, and that one is held to the tree."""
    from terp.cli.release._image import Node

    release = Release(tmp_path, monkeypatch)
    release.write_build(web=True)
    release.answer["nodes"]["srv/app/main.py"] = Node("file", "f" * 64, 9).as_data()
    with pytest.raises(ReleaseError, match="is not this commit's build"):
        release.sign()
    release.answer["configDigest"] = "sha256:" + "0" * 64
    with pytest.raises(ReleaseError, match="the sandbox read another image"):
        release.sign()


def test_an_image_built_for_another_platform_than_recorded_is_refused(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    write_document(release.build_doc, {**json.loads(release.build_doc.read_text()), "platform": "linux/arm64"})
    with pytest.raises(ReleaseError, match="is built for linux/amd64, not linux/arm64"):
        release.sign()
