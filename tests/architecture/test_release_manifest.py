"""The release manifest: what ``sign`` records, and how a verified payload is read back.

ADR 0187 decision 6. :func:`terp.cli.release.manifest.parse` is the one reader of a payload a
signature has already verified, so every field ``terp promote`` relies on is held to its shape
there; the rest of the module assembles what ``sign`` writes.
"""

from __future__ import annotations

import json

import pytest

from terp.cli.release import manifest
from terp.cli.release._common import ReleaseError, canonical, sha256

CONTENT = '{"schemaVersion": 1}'


def good() -> dict:
    carried = {"path": "deployment.json", "sha256": sha256(CONTENT.encode()), "content": CONTENT}
    return {
        "schemaVersion": 1,
        "inputs": {
            "releaseTag": "r1", "build": "generated", "spec": {"release": "0.40.0", "schemaSha256": "0" * 64},
            "declaration": carried, "profiles": [{**carried, "path": "docker-compose.prod.yml"}], "datastores": {"kinds": {}},
        },
        "outputs": {"images": {"app": {"repository": "r.example/app", "digest": "sha256:1", "imageId": "sha256:2"}}, "services": {}},
        "collected": {},
    }


def test_a_well_formed_manifest_reads_back_as_written() -> None:
    assert manifest.parse(canonical(good())) == good()
    assert manifest.parse(manifest.assemble(good()["inputs"], good()["outputs"], {})) == good()


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda m: m.update(schemaVersion=2), "schemaVersion 2, which this terp promote does not read"),
        (lambda m: m.pop("inputs"), "the manifest's inputs is missing"),
        (lambda m: m.update(outputs=[]), "the manifest's outputs is missing"),
        (lambda m: m["inputs"].update(releaseTag=1), "inputs.releaseTag is missing"),
        (lambda m: m["inputs"].update(releaseTag="a b"), "is not a Docker tag"),
        (lambda m: m["inputs"].update(build="maybe"), "neither own nor generated"),
        (lambda m: m["inputs"]["spec"].pop("release"), "inputs.spec.release is missing"),
        (lambda m: m["inputs"].update(profiles={}), "inputs.profiles is missing"),
        (lambda m: m["inputs"]["profiles"].append("x"), r"inputs.profiles\[\] is missing"),
        (lambda m: m["inputs"]["declaration"].pop("content"), "carried file content is missing"),
        (lambda m: m["inputs"]["declaration"].update(content="{}"), "is not the content its SHA-256 names"),
        (lambda m: m["inputs"].pop("datastores"), "inputs.datastores is missing"),
        (lambda m: m["outputs"]["images"].update(web=[]), "outputs.images.web is missing"),
        (lambda m: m["outputs"]["images"]["app"].pop("digest"), "outputs.images.app.digest is missing"),
        (lambda m: m["outputs"].pop("services"), "outputs.services is missing"),
    ],
)
def test_a_payload_promote_could_not_honour_is_refused_by_name(change, expected: str) -> None:
    body = good()
    change(body)
    with pytest.raises(ReleaseError, match=expected):
        manifest.parse(canonical(body))


def test_a_payload_that_is_not_one_object_is_refused() -> None:
    with pytest.raises(ReleaseError, match="is not JSON"):
        manifest.parse(b"{")
    with pytest.raises(ReleaseError, match="top level is missing"):
        manifest.parse(json.dumps([1]).encode())


class _Tree:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    def has(self, path: str) -> bool:
        return path in self.files

    def read_text(self, path: str) -> str:
        return self.files[path]


def test_the_development_profile_is_the_one_workbench_json_names() -> None:
    assert manifest.development_profile(_Tree({})) == "docker-compose.yml"
    assert manifest.development_profile(_Tree({"workbench.json": '{"compose": {"file": "dev/compose.yml"}}'})) == "dev/compose.yml"
    assert manifest.development_profile(_Tree({"workbench.json": "{broken"})) == "docker-compose.yml"
    assert manifest.development_profile(_Tree({"workbench.json": '{"compose": {"file": ""}}'})) == "docker-compose.yml"
    assert manifest.PROJECT_ROOT == "."


def test_an_sbom_names_each_package_by_its_package_url() -> None:
    npm = manifest.sbom("web", "r1", [("@terpjs/react-core", "0.35.0")], "npm")
    assert manifest.purls(npm) == ["pkg:npm/%40terpjs/react-core@0.35.0"]
    pypi = manifest.sbom("api", "r1", [("Zope.Interface", "7")], "pypi")
    assert manifest.purls(pypi) == ["pkg:pypi/zope-interface@7"]
    assert "timestamp" not in json.dumps(pypi), "one set is one byte string"
