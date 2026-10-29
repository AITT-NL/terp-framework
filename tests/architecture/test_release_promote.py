"""``terp promote``: a signed release, verified before anything, deployed without rebuilding.

ADR 0184 decision 9 and ADR 0187 decision 6. Every docker call goes through :class:`Runs`, so a
refusal is shown to come before anything is pulled or started by the list of calls it leaves:
none at all for a bad envelope, no compose call for a changed image. The envelopes are signed
with throwaway keys over manifests made here, so each case can carry exactly one wrong thing.
"""

from __future__ import annotations

import base64
import json
import pathlib
import re
import sys

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import ed25519

from terp.arch.deployment import published_table
from terp.cli.release import dsse, promote
from terp.cli.release._common import ReleaseError, canonical, sha256
from tests.architecture.release_fixtures import PROJECT, Runs, app_files
from tests.architecture.test_release_dsse import pem_public

REPO = f"registry.example/rel/{PROJECT}-backend-prod"
DIGEST = "sha256:" + "1" * 64
IMAGE_ID = "sha256:" + "2" * 64
POSTGRES = published_table().find("postgres", "17").image
BEFORE = {"alembic_version_audit": ["a1"]}


def _file(path: str, data: bytes) -> dict:
    return {"path": path, "sha256": sha256(data), "content": data.decode()}


def make_manifest(files: dict[str, bytes] | None = None, *, tag: str = "r1", build: str | None = None, spec: str = "0.40.0") -> dict:
    files = files if files is not None else app_files()
    declaration = json.loads(files["deployment.json"])
    if build is not None:
        declaration["build"] = build
        files = {**files, "deployment.json": json.dumps(declaration).encode()}
    try:
        services = yaml.safe_load(files["docker-compose.prod.yml"])["services"]
    except yaml.YAMLError:
        services = {}
    refs = {name: (POSTGRES if name == "db" else f"{REPO}@{DIGEST}") for name in services}
    return {
        "schemaVersion": 1,
        "inputs": {
            "releaseTag": tag, "build": declaration["build"], "spec": {"release": spec, "schemaSha256": "0" * 64},
            "declaration": _file("deployment.json", files["deployment.json"]),
            "profiles": [_file("docker-compose.prod.yml", files["docker-compose.prod.yml"])],
            "datastores": {"kinds": {"postgres": {"role": "database", "versions": {"17": POSTGRES}}}},
        },
        "outputs": {
            "images": {f"{PROJECT}-backend-prod": {"repository": REPO, "digest": DIGEST, "imageId": IMAGE_ID}},
            "services": refs,
        },
        "collected": {},
    }


@pytest.fixture
def keys(tmp_path: pathlib.Path):  # type: ignore[no-untyped-def]
    key = ed25519.Ed25519PrivateKey.generate()
    (tmp_path / "trusted.pub").write_bytes(pem_public(key))
    return key


def envelope(tmp_path: pathlib.Path, key, body: dict | bytes, name: str = "release.dsse.json") -> pathlib.Path:  # type: ignore[no-untyped-def]
    payload = body if isinstance(body, bytes) else canonical(body)
    path = tmp_path / name
    path.write_bytes(canonical(dsse.envelope(payload, [dsse.sign_with_key(key, payload)])))
    return path


def docker(before: dict | None = None, after: dict | None = None, *, image_id: str = IMAGE_ID,
           migrate_code: int = 0, up_code: int = 0) -> Runs:
    readings = [before if before is not None else BEFORE, after if after is not None else (before if before is not None else BEFORE)]

    def compose_run(argv, stdin):  # type: ignore[no-untyped-def]
        if "--entrypoint" in argv:
            return 0, ("log line\n" + json.dumps(readings.pop(0) if len(readings) > 1 else readings[0])).encode(), b""
        if "check" in argv:
            return 0, b"migrations current", b""
        return migrate_code, b"upgraded", b"refused" if migrate_code else b""

    def compose_up(argv, stdin):  # type: ignore[no-untyped-def]
        return (up_code if "--no-deps" in argv else 0), b"", b"unhealthy" if up_code and "--no-deps" in argv else b""

    return (
        Runs()
        .on("docker", "pull")
        .on("docker", "tag")
        .on("docker", "image", "inspect", out=image_id.encode() + b"\n")
        .on("docker", "compose", then=lambda argv, stdin: compose_run(argv, stdin) if "run" in argv else compose_up(argv, stdin))
    )


def _promote(tmp_path, keys, body=None, runs=None, monkeypatch=None, **options):  # type: ignore[no-untyped-def]
    path = envelope(tmp_path, keys, body if body is not None else make_manifest())
    monkeypatch.setattr(promote, "run", runs)
    return promote.promote(path, [tmp_path / "trusted.pub"], tmp_path / "deploy", **options)


# --------------------------------------------------------------------------- the deploy
def test_a_release_is_deployed_exactly_as_signed_and_migrated_once(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    runs = docker()
    env = {"PATH": "/bin", "SECRET_KEY": "s" * 40, "POSTGRES_PASSWORD": "p", "AWS_SECRET_ACCESS_KEY": "never",
           "COMPOSE_FILE": "evil.yml", "TERP_RELEASE_TAG": "stale"}
    log = _promote(tmp_path, keys, runs=runs, monkeypatch=monkeypatch, env=env)
    assert log[-1] == "promoted r1"
    calls = [call[:3] if call[1] != "compose" else ["compose", *[part for part in call if part in ("up", "run")]] for call in runs.calls]
    assert runs.ran("docker", "pull") == [["docker", "pull", f"{REPO}@{DIGEST}"], ["docker", "pull", POSTGRES]]
    assert runs.ran("docker", "tag") == [["docker", "tag", f"{REPO}@{DIGEST}", f"{PROJECT}-backend-prod:r1"]]
    composes = runs.ran("docker", "compose")
    ups = [call for call in composes if "up" in call]
    assert all({"--no-build", "--wait"} <= set(call) and call[call.index("--pull") + 1] == "never" for call in ups)
    assert ups[0][-1] == "db" and "--no-deps" not in ups[0]
    assert ups[1][-1] == "api" and "--no-deps" in ups[1] and "migrate" not in ups[1]
    migrations = [call for call in composes if "run" in call and "--entrypoint" not in call]
    assert len(migrations) == 1 and migrations[0][-1] == "migrate", "the migration step runs exactly once, as written"
    [reading] = [call for call in composes if "--entrypoint" in call]
    assert composes.index(reading) < composes.index(migrations[0]), "the version tables are read before the step"
    assert reading[reading.index("--entrypoint") + 1] == "python" and reading[reading.index("migrate") + 1:][:2] == ["-I", "-c"]
    journal = tmp_path / "deploy" / ".terp" / "versions-before-r1.json"
    assert json.loads(journal.read_text()) == BEFORE
    assert (tmp_path / "deploy" / "docker-compose.prod.yml").read_bytes() == app_files()["docker-compose.prod.yml"]
    assert (tmp_path / "deploy" / "deployment.json").read_bytes() == app_files()["deployment.json"]
    assert calls[0] == ["docker", "pull", f"{REPO}@{DIGEST}"]


def test_compose_runs_with_an_allowlisted_environment_never_its_own(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    seen: list[dict] = []
    runs = docker()
    real = runs.__call__

    def recording(argv, *, cwd=None, env=None, stdin=None):  # type: ignore[no-untyped-def]
        if argv[:2] == ["docker", "compose"]:
            seen.append(env)
        return real(argv, cwd=cwd, env=env, stdin=stdin)

    env = {"PATH": "/bin", "SECRET_KEY": "s" * 40, "POSTGRES_PASSWORD": "p", "AWS_SECRET_ACCESS_KEY": "never",
           "COMPOSE_FILE": "evil.yml", "COMPOSE_PROJECT_NAME": "x", "TERP_RELEASE_TAG": "stale", "DOCKER_HOST": "unix:///d"}
    _promote(tmp_path, keys, runs=recording, monkeypatch=monkeypatch, env=env)
    for env_seen in seen:
        assert env_seen["TERP_RELEASE_TAG"] == "r1", "the tag is the signed one, never the environment's"
        assert env_seen["SECRET_KEY"] == "s" * 40 and env_seen["POSTGRES_PASSWORD"] == "p"
        assert "AWS_SECRET_ACCESS_KEY" not in env_seen and not any(name.startswith("COMPOSE_") for name in env_seen)
        assert env_seen["DOCKER_HOST"] == "unix:///d"


def test_without_a_migration_step_the_one_api_runs_the_upgrade(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    files = app_files()
    profile = yaml.safe_load(files["docker-compose.prod.yml"])
    profile["services"].pop("migrate")
    profile["services"]["api"]["depends_on"].pop("migrate")
    declaration = json.loads(files["deployment.json"])
    declaration["build"] = "own"
    declaration["units"] = [unit for unit in declaration["units"] if unit["id"] != "migrate"]
    declaration["units"][1]["dependsOn"] = ["db"]
    files = {**files, "deployment.json": json.dumps(declaration).encode(), "docker-compose.prod.yml": yaml.safe_dump(profile).encode()}
    runs = docker()
    _promote(tmp_path, keys, body=make_manifest(files), runs=runs, monkeypatch=monkeypatch, env={})
    composes = runs.ran("docker", "compose")
    [upgrade] = [call for call in composes if "run" in call and "--entrypoint" not in call]
    assert upgrade[-4:] == ["api", "terp", "migrate", "upgrade"]
    [up] = [call for call in composes if "up" in call and "--no-deps" in call]
    assert up[-1] == "api", "the api still starts after its own upgrade"


# --------------------------------------------------------------------------- refused before anything
def _no_calls() -> Runs:
    return Runs()


def test_an_envelope_that_does_not_verify_is_refused_before_anything_starts(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    payload = canonical(make_manifest())
    good = json.loads(canonical(dsse.envelope(payload, [dsse.sign_with_key(keys, payload)])))
    other = ed25519.Ed25519PrivateKey.generate()
    tampered = canonical(make_manifest()).replace(DIGEST.encode(), ("sha256:" + "9" * 64).encode())
    cases = {
        "unsigned": {**good, "signatures": []},
        "broken": {**good, "signatures": [{**good["signatures"][0], "sig": base64.b64encode(b"\x00" * 64).decode()}]},
        "other-key": dsse.envelope(payload, [dsse.sign_with_key(other, payload)]),
        "changed-image": {**good, "payload": base64.b64encode(tampered).decode()},
    }
    runs = _no_calls()
    monkeypatch.setattr(promote, "run", runs)
    for name, document in cases.items():
        path = tmp_path / f"{name}.json"
        path.write_bytes(canonical(document))
        with pytest.raises(ReleaseError, match="carries no signature|no signature of the envelope verifies"):
            promote.promote(path, [tmp_path / "trusted.pub"], tmp_path / "deploy")
    assert runs.calls == [], "nothing was pulled, tagged or started"
    assert not (tmp_path / "deploy").exists(), "nothing was written"


def test_a_changed_image_under_a_valid_signature_is_refused_before_compose(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    runs = docker(image_id="sha256:" + "f" * 64)
    # Both names of the signed image: an engine on the containerd store shows the manifest's
    # digest as the local id, the classic store the configuration's, and the refusal is read
    # on whichever the deploy runs on.
    with pytest.raises(
        ReleaseError,
        match=r"is sha256:f+, not the image the release signs "
        + re.escape(f"(manifest {DIGEST}, configuration {IMAGE_ID})"),
    ):
        _promote(tmp_path, keys, runs=runs, monkeypatch=monkeypatch, env={})
    assert runs.ran("docker", "compose") == []
    gone = docker().on("docker", "pull", code=1, err=b"manifest unknown")
    with pytest.raises(ReleaseError, match="pulling .* the signed image failed"):
        _promote(tmp_path, keys, runs=gone, monkeypatch=monkeypatch, env={})
    assert gone.ran("docker", "compose") == [] and gone.ran("docker", "tag") == []


@pytest.mark.parametrize(
    ("change", "options", "expected"),
    [
        (lambda m: m, {"require_generated": True, "_build": "own"}, '--require-generated: the release says "build": "own"'),
        (lambda m: m["inputs"]["spec"].update(release="9.0.0"), {}, "Terp Standard 9.0.0, newer than"),
        (lambda m: m.update(schemaVersion=2), {}, "schemaVersion 2, which this terp promote does not read"),
        (lambda m: m["inputs"]["declaration"].update(sha256="0" * 64), {}, "is not the content its SHA-256 names"),
        (lambda m: m["inputs"].update(releaseTag="-bad"), {}, "is not a Docker tag"),
        (lambda m: m["inputs"].update(build="maybe"), {}, "neither own nor generated"),
        (lambda m: m["outputs"]["images"][f"{PROJECT}-backend-prod"].pop("imageId"), {}, "imageId is missing"),
        (lambda m: m["inputs"].pop("datastores"), {}, "inputs.datastores is missing"),
        (lambda m: m["inputs"]["profiles"].clear(), {}, "not the ones the declaration names"),
        (lambda m: m["inputs"]["datastores"]["kinds"]["postgres"]["versions"].pop("17"), {}, "cannot be read"),
        (lambda m: m["inputs"].update(build="own"), {}, "disagree on the build"),
    ],
)
def test_a_manifest_promote_cannot_honour_is_refused_before_anything(tmp_path: pathlib.Path, keys, monkeypatch, change, options, expected) -> None:
    body = make_manifest(build=options.pop("_build", None))
    change(body)
    runs = _no_calls()
    with pytest.raises(ReleaseError, match=expected):
        _promote(tmp_path, keys, body=body, runs=runs, monkeypatch=monkeypatch, **options)
    assert runs.calls == []


def test_a_payload_that_is_not_a_manifest_is_refused(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    for body, expected in ((b"not json", "is not JSON"), (canonical([1]), "top level is missing")):
        with pytest.raises(ReleaseError, match=expected):
            _promote(tmp_path, keys, body=body, runs=_no_calls(), monkeypatch=monkeypatch)


def test_a_retired_datastore_version_still_reads_from_the_manifest_s_own_record(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    retired = "postgres@sha256:" + "6" * 64
    files = app_files()
    declaration = json.loads(files["deployment.json"])
    declaration["build"] = "own"
    declaration["units"][0]["version"] = "16"
    profile = yaml.safe_load(files["docker-compose.prod.yml"])
    profile["services"]["db"]["image"] = retired
    files = {**files, "deployment.json": json.dumps(declaration).encode(), "docker-compose.prod.yml": yaml.safe_dump(profile).encode()}
    body = make_manifest(files)
    body["inputs"]["datastores"]["kinds"]["postgres"]["versions"] = {"16": retired}
    log = _promote(tmp_path, keys, body=body, runs=docker(), monkeypatch=monkeypatch, env={})
    assert log[-1] == "promoted r1"


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        (lambda text: text.replace('command: ["terp", "migrate", "upgrade", "--app-root", "/srv/app"]',
                                   'command: ["sh", "-c", "${SECRET_KEY}"]'), "interpolates outside the generator's fixed list"),
        (lambda text: text.replace("restart: unless-stopped", "restart: !!str unless-stopped", 1), "carries a YAML tag"),
    ],
)
def test_a_generated_profile_is_audited_for_escapes_and_tags(tmp_path: pathlib.Path, keys, monkeypatch, edit, expected) -> None:
    files = app_files()
    files["docker-compose.prod.yml"] = edit(files["docker-compose.prod.yml"].decode()).encode()
    runs = _no_calls()
    with pytest.raises(ReleaseError, match=expected):
        _promote(tmp_path, keys, body=make_manifest(files), runs=runs, monkeypatch=monkeypatch)
    assert runs.calls == []


def test_a_carried_profile_that_cannot_be_read_is_refused(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    files = app_files()
    files["docker-compose.prod.yml"] = b"services: [unclosed"
    with pytest.raises(ReleaseError, match="cannot be read"):
        _promote(tmp_path, keys, body=make_manifest({**files, "deployment.json": files["deployment.json"]}, build="own"),
                 runs=_no_calls(), monkeypatch=monkeypatch)


# --------------------------------------------------------------------------- failure, undo, rollback
def test_a_failed_deploy_on_unchanged_version_tables_is_restore_free_to_undo(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    runs = docker(up_code=1)
    with pytest.raises(ReleaseError, match="did not come up healthy.*\\n.*restore-free.*--undo-to"):
        _promote(tmp_path, keys, runs=runs, monkeypatch=monkeypatch, env={})


def test_a_failed_deploy_whose_migration_moved_the_tables_is_restore_based(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    runs = docker(after={"alembic_version_audit": ["a2"]}, up_code=1)
    with pytest.raises(ReleaseError, match="changed the version tables, so going back is restore-based"):
        _promote(tmp_path, keys, runs=runs, monkeypatch=monkeypatch, env={})


def test_the_undo_starts_the_previous_release_after_its_own_check(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    previous = envelope(tmp_path, keys, make_manifest(tag="r0"), name="previous.dsse.json")
    runs = docker(migrate_code=1)
    with pytest.raises(ReleaseError, match="the migration step failed") as raised:
        _promote(tmp_path, keys, runs=runs, monkeypatch=monkeypatch, env={}, undo_to=previous)
    assert "undone: r0 runs again on the database as it was, without a restore" in raised.value.message
    composes = runs.ran("docker", "compose")
    [check] = [call for call in composes if "check" in call]
    assert check[-6:] == ["migrate", "terp", "migrate", "check", "--app-root", "/srv/app"], "the step's own command, upgrade as check"
    assert composes[-1][-1] == "api" and "--no-build" in composes[-1]
    assert runs.ran("docker", "tag") == [["docker", "tag", f"{REPO}@{DIGEST}", f"{PROJECT}-backend-prod:r1"]], "the undo pulls nothing"
    assert json.loads((tmp_path / "deploy" / "deployment.json").read_text())["units"]


def test_a_rollback_in_an_invocation_of_its_own_is_restore_based(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    runs = _no_calls()
    with pytest.raises(ReleaseError, match="restore-based .* --rollback --restored"):
        _promote(tmp_path, keys, runs=runs, monkeypatch=monkeypatch, rollback=True)
    assert runs.calls == []
    runs = docker()
    log = _promote(tmp_path, keys, runs=runs, monkeypatch=monkeypatch, env={}, rollback=True, restored=True)
    assert log[-1] == "promoted r1" and "r1's own migration check passes on the restored database" in log
    composes = [call for call in runs.ran("docker", "compose") if "run" in call and "--entrypoint" not in call]
    assert composes[0][-6:] == ["migrate", "terp", "migrate", "check", "--app-root", "/srv/app"]
    assert composes[1][-1] == "migrate", "then the step itself, which applies nothing on the target's own heads"
    failing = docker().on("docker", "compose", then=lambda argv, stdin: (1, b"", b"orphaned") if "check" in argv else (
        (0, json.dumps(BEFORE).encode(), b"") if "--entrypoint" in argv else (0, b"", b"")))
    with pytest.raises(ReleaseError, match="own migration check on the restored database failed"):
        _promote(tmp_path, keys, runs=failing, monkeypatch=monkeypatch, env={}, rollback=True, restored=True)
    assert not [call for call in failing.calls if "up" in call and "--no-deps" in call], "nothing but the datastores started"


def test_the_version_tables_are_read_as_version_tables(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    for out, expected in ((b"", "could not be read"), (b'{"users": ["x"]}', "read as something else"), (b"[1]", "read as something else")):
        runs = docker()
        runs.on("docker", "compose", then=lambda argv, stdin, out=out: (0, out, b"") if "--entrypoint" in argv else (0, b"", b""))
        with pytest.raises(ReleaseError, match=expected):
            _promote(tmp_path, keys, runs=runs, monkeypatch=monkeypatch, env={})


def test_a_migration_step_that_interpolates_has_no_check_to_run(tmp_path: pathlib.Path, keys) -> None:
    files = app_files()
    text = files["docker-compose.prod.yml"].decode().replace(
        '"--app-root", "/srv/app"]', '"--app-root", "${APP_ROOT}"]')
    files = {**files, "docker-compose.prod.yml": text.encode()}
    body = make_manifest(files, build="own")
    release = promote.load(canonical(dsse.envelope(canonical(body), [dsse.sign_with_key(keys, canonical(body))])),
                           [pem_public(keys)])
    with pytest.raises(ReleaseError, match="interpolates, so its own check cannot be run"):
        promote._check_command(release)


def test_promote_needs_cryptography(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    path = envelope(tmp_path, keys, make_manifest())
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives", None)
    with pytest.raises(ReleaseError, match=r"install terp-cli\[release\]"):
        promote.promote(path, [tmp_path / "trusted.pub"], tmp_path / "deploy")




def test_a_carried_declaration_that_is_not_json_is_refused(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    body = make_manifest()
    body["inputs"]["declaration"] = _file("deployment.json", b"{not json")
    with pytest.raises(ReleaseError, match="the carried declaration or datastore record cannot be read"):
        _promote(tmp_path, keys, body=body, runs=_no_calls(), monkeypatch=monkeypatch)


def test_without_a_migration_step_the_check_is_terp_migrate_check_in_the_api(keys) -> None:
    files = app_files()
    profile = yaml.safe_load(files["docker-compose.prod.yml"])
    profile["services"].pop("migrate")
    profile["services"]["api"]["depends_on"].pop("migrate")
    declaration = json.loads(files["deployment.json"])
    declaration["build"] = "own"
    declaration["units"] = [unit for unit in declaration["units"] if unit["id"] != "migrate"]
    declaration["units"][1]["dependsOn"] = ["db"]
    files = {**files, "deployment.json": json.dumps(declaration).encode(), "docker-compose.prod.yml": yaml.safe_dump(profile).encode()}
    body = canonical(make_manifest(files))
    release = promote.load(canonical(dsse.envelope(body, [dsse.sign_with_key(keys, body)])), [pem_public(keys)])
    assert promote._check_command(release) == ("api", ["terp", "migrate", "check"])


def test_an_unmanaged_carried_declaration_is_refused(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    body = make_manifest()
    body["inputs"]["declaration"] = _file("deployment.json", b'{"unmanaged": true, "reason": "by hand"}')
    with pytest.raises(ReleaseError, match="it is unmanaged"):
        _promote(tmp_path, keys, body=body, runs=_no_calls(), monkeypatch=monkeypatch)


@pytest.mark.parametrize("path", ["../outside.yml", "/etc/compose.yml", "C:/x.yml", "a\\..\\b.yml"])
def test_a_carried_file_is_written_inside_the_project_directory_only(tmp_path: pathlib.Path, keys, monkeypatch, path: str) -> None:
    body = make_manifest()
    body["inputs"]["declaration"]["path"] = path
    with pytest.raises(ReleaseError, match="a path outside the directory a release is written to"):
        _promote(tmp_path, keys, body=body, runs=_no_calls(), monkeypatch=monkeypatch)


def test_a_carried_generated_profile_that_is_not_yaml_is_refused(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    files = app_files()
    files["docker-compose.prod.yml"] = b"services: [unclosed"
    with pytest.raises(ReleaseError, match="is not YAML"):
        _promote(tmp_path, keys, body=make_manifest(files), runs=_no_calls(), monkeypatch=monkeypatch)


def test_an_engine_that_names_images_by_their_manifest_is_held_to_the_signed_digest(tmp_path: pathlib.Path, keys, monkeypatch) -> None:
    """The containerd image store names a local image by its manifest digest, the classic one by
    its configuration's: both are the signed image, and anything else is not."""
    assert _promote(tmp_path, keys, runs=docker(image_id=DIGEST), monkeypatch=monkeypatch, env={})[-1] == "promoted r1"
