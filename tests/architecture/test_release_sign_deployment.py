"""``terp release sign`` writes the resolved deployment the release runs, and checks it first.

The commit's own ``terp-arch`` writes it, in a process of its own as the render is, from the images
``sign`` verified (:func:`terp.cli.release._render.resolve`); the signer holds it to its own
``terp-arch``'s schema copy and checks (:mod:`terp.arch.deployment.resolved_check`) before the
manifest, then version 2, carries it. A pinned ``terp-arch`` from before the writer signs a
version 1 manifest without it. The wheel here is built from this repository's ``terp-arch``,
so the document a test reads is the writer's own, written for real in a process of its own.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from terp.arch.deployment import published_tables, reader
from terp.arch.deployment.resolved import resolved_deployment
from terp.cli.release import _render, sign
from terp.cli.release._common import ReleaseError
from terp.cli.release.manifest import parse
from tests.architecture.release_fixtures import PROJECT, TOOLCHAIN, app_files
from tests.architecture.test_release_image import layer
from tests.architecture.test_release_render import ARCH, build_wheel, table
from tests.architecture.test_release_sign import NAME, REGISTRY, Release, _push_web

_RESOLVED = "terp/arch/deployment/resolved.py"


def _writer_then(change: str) -> dict[str, bytes]:
    """The real writer, with *change* applied to every document it writes (``document`` names it)."""
    wrapped = (ARCH / _RESOLVED).read_bytes() + (
        "\n_written = resolved_deployment\n"
        "def resolved_deployment(*arguments, **options):\n"
        "    document = _written(*arguments, **options)\n"
        f"    {change}\n"
        "    return document\n"
    ).encode()
    return {_RESOLVED: wrapped}


def _manifest(tmp_path: pathlib.Path) -> dict:
    return parse((tmp_path / "out" / sign.MANIFEST).read_bytes().strip())


def _repin(release: Release, *, drop: str | None = None, replace: dict[str, bytes] | None = None) -> None:
    """Pin the release to a terp-arch wheel built without *drop*, or with *replace*'s files."""
    release.releases = table(release.tmp, build_wheel(release.tmp / "index", drop=drop, replace=replace))


def _push(release: Release, config: dict) -> None:
    """Push the backend image again with *config*, and record it as the build's and the sandbox's."""
    release.digest = release.registry.push_image([layer(("srv/app/main.py", b"x"))], config=config, tag="r1")
    release.config_digest = json.loads(release.registry.manifests[release.digest][1])["config"]["digest"]
    release.answer.update(digest=release.digest, configDigest=release.config_digest)
    release.write_build()


def test_a_generated_release_carries_the_deployment_its_own_terp_arch_writes(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    release.sign()
    manifest = _manifest(tmp_path)
    out = manifest["outputs"]
    assert manifest["schemaVersion"] == 2
    tables = published_tables()
    declared, found = reader.read(json.loads(app_files()["deployment.json"]), tables.datastores, tables.system_packages)
    assert found == [] and declared is not None
    expected = resolved_deployment(declared, PROJECT, tables=tables, images=out["units"], frontend_lock=False)
    assert out["deployment"] == expected, "written in the pinned process exactly as the library writes it"
    assert [service["id"] for service in expected["services"]] == [unit.id for unit in declared.units]
    assert {service["id"]: service["image"] for service in expected["services"]} == out["units"]
    assert out["images"][NAME]["volumes"] == []


def test_a_pinned_terp_arch_without_the_writer_signs_a_version_1_manifest(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    _repin(release, drop=_RESOLVED)
    release.sign()
    manifest = _manifest(tmp_path)
    assert manifest["schemaVersion"] == 1
    assert "deployment" not in manifest["outputs"] and "volumes" not in manifest["outputs"]["images"][NAME]


def test_a_release_with_its_own_build_files_signs_a_version_1_manifest(tmp_path: pathlib.Path, monkeypatch) -> None:
    files = app_files()
    declaration = json.loads(files["deployment.json"])
    declaration["build"] = "own"  # the same files, now the app's own rather than the generator's
    files["deployment.json"] = json.dumps(declaration, indent=2).encode()
    release = Release(tmp_path, monkeypatch, files)
    release.sign()
    manifest = _manifest(tmp_path)
    assert manifest["inputs"]["build"] == "own"
    assert manifest["schemaVersion"] == 1 and "deployment" not in manifest["outputs"]


def test_an_image_volume_no_named_volume_covers_is_signed_as_an_anonymous_mount(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    _push(release, {"architecture": "amd64", "os": "linux", "rootfs": {"diff_ids": []},
                    "config": {"Volumes": {"/var/cache/example": {}}}})
    release.sign()
    out = _manifest(tmp_path)["outputs"]
    assert out["images"][NAME]["volumes"] == ["/var/cache/example"]
    by_id = {service["id"]: service for service in out["deployment"]["services"]}
    for ident, image in out["units"].items():
        anonymous = [mount for mount in by_id[ident]["mounts"] if mount["type"] == "anonymous"]
        expected = [{"type": "anonymous", "target": "/var/cache/example"}] if image.startswith(REGISTRY) else []
        assert anonymous == expected, ident


@pytest.mark.parametrize("volumes", [["/var/cache/example"], "x"])
def test_an_image_configuration_whose_volumes_are_not_paths_is_refused(tmp_path: pathlib.Path, monkeypatch, volumes) -> None:
    release = Release(tmp_path, monkeypatch)
    _push(release, {"architecture": "amd64", "os": "linux", "rootfs": {"diff_ids": []}, "config": {"Volumes": volumes}})
    with pytest.raises(ReleaseError, match=r"config.Volumes is not an object keyed by path"):
        release.sign()


@pytest.mark.parametrize("path", ["/srv/app", "/var/cache/example/", "cache"])
def test_an_image_volume_no_mount_can_carry_is_refused_as_the_image_s(tmp_path: pathlib.Path, monkeypatch, path: str) -> None:
    release = Release(tmp_path, monkeypatch)
    _push(release, {"architecture": "amd64", "os": "linux", "rootfs": {"diff_ids": []},
                    "config": {"Volumes": {path: {}}}})
    with pytest.raises(ReleaseError, match=(
        rf'@sha256:[0-9a-f]{{64}} declares the volume "{path}" in its configuration, where a resolved '
        r"deployment cannot mount one .*: change the VOLUME instruction that declares it"
    )):
        release.sign()
    assert not (tmp_path / "out" / sign.ENVELOPE).exists()


def test_a_service_that_leaves_its_image_s_volume_unmounted_is_never_signed(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    _push(release, {"architecture": "amd64", "os": "linux", "rootfs": {"diff_ids": []},
                    "config": {"Volumes": {"/var/cache/example": {}}}})
    _repin(release, replace=_writer_then(
        "[service.update(mounts=[m for m in service['mounts'] if m['type'] != 'anonymous']) "
        "for service in document['services']]"
    ))
    with pytest.raises(ReleaseError, match=(
        r"is not one this signer signs .*\n- \$\.services\[\d+\]\.mounts: a mount at /var/cache/example, "
        r"which its image declares a volume"
    )):
        release.sign()
    assert not (tmp_path / "out" / sign.ENVELOPE).exists()


def test_a_service_that_runs_another_unit_s_image_is_never_signed(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch, app_files(web=True))
    _push_web(release, (f"{PROJECT}-frontend-prod", "frontend/Dockerfile.prod", "web"))
    # Both are images the release built, so only the manifest's own record tells them apart.
    _repin(release, replace=_writer_then(
        "by = {service['id']: service for service in document['services']}; "
        "by['api']['image'], by['web']['image'] = by['web']['image'], by['api']['image']"
    ))
    with pytest.raises(ReleaseError, match=r"\n- \$\.services\[\d+\]\.image: \S+, the image outputs.units records for api"):
        release.sign()
    assert not (tmp_path / "out" / sign.ENVELOPE).exists()


def test_a_pinned_release_that_prints_beside_its_answer_is_refused(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    _repin(release, replace={_RESOLVED: (ARCH / _RESOLVED).read_bytes() + b"\nprint('loaded')\n"})
    with pytest.raises(ReleaseError, match=(
        f"terp-arch {TOOLCHAIN} answered writing the resolved deployment with something other than the "
        "JSON object this signer reads"
    )) as refused:
        release.sign()
    assert refused.value.cause, "what the JSON reader said is kept"


def test_what_the_pinned_writer_refuses_is_refused_in_its_words(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    _repin(release, replace={_RESOLVED: (
        b"class ResolvedDeploymentError(ValueError):\n    pass\n"
        b"def resolved_deployment(*arguments, **options):\n"
        b"    raise ResolvedDeploymentError('db is something version 1 cannot say')\n"
    )})
    with pytest.raises(ReleaseError, match=f"terp-arch {TOOLCHAIN} cannot write this commit's resolved deployment:\n"
                                           "- db is something version 1 cannot say"):
        release.sign()


def test_a_document_the_signer_refuses_is_never_signed(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    _repin(release, replace={_RESOLVED: (
        b"class ResolvedDeploymentError(ValueError):\n    pass\n"
        b"def resolved_deployment(*arguments, **options):\n"
        b"    return {'schemaVersion': 1, 'services': [], 'volumes': []}\n"
    )})
    with pytest.raises(ReleaseError, match=r"is not one this signer signs .*\n- \$\.services: has 0 item"):
        release.sign()
    assert not (tmp_path / "out" / sign.ENVELOPE).exists()


def test_a_pinned_writer_that_answers_with_no_document_is_refused(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = Release(tmp_path, monkeypatch)
    monkeypatch.setattr(sign, "resolve", lambda *arguments, **options: (None, []))
    with pytest.raises(ReleaseError, match="cannot write this commit's resolved deployment:\n- it answered with no document"):
        release.sign()


def test_the_pinned_wheel_says_whether_it_writes_the_resolved_deployment(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(_render, "FLOOR", TOOLCHAIN)
    writes = build_wheel(tmp_path / "with")
    assert _render.fetch(table(tmp_path / "with", writes), str(tmp_path / "with"), TOOLCHAIN, tmp_path).resolves
    older = build_wheel(tmp_path / "without", drop=_RESOLVED)
    assert not _render.fetch(table(tmp_path / "without", older), str(tmp_path / "without"), TOOLCHAIN, tmp_path).resolves
