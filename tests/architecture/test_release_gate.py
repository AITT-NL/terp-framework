"""``terp release gate``: the release profile, and the schedules read from the pushed image.

ADR 0187 decision 6. The gate runs the app, so it holds nothing a release is protected by: its
docker client gets a configuration directory of its own, and the pushed image is run sealed,
as its own non-root user, with no network.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from terp.cli.release import gate
from terp.cli.release._common import ReleaseError, write_document
from tests.architecture.release_fixtures import PROJECT, Runs, committed_app

DIGEST = "sha256:" + "1" * 64
ASSURANCE = {"terp_assurance": 1, "ok": True, "lanes": []}
CONTROL_PLANE = {"schedules": [{"name": "nightly.sync", "cron": "0 3 * * *", "job": "sync.pull", "extra": "x"}]}


def _build(tmp_path: pathlib.Path, sha: str, images: list[dict] | None = None) -> pathlib.Path:
    path = tmp_path / "build.json"
    write_document(path, {
        "terpReleaseBuild": 1, "commit": sha, "releaseTag": "r1",
        "images": images if images is not None else [
            {"name": f"{PROJECT}-backend-prod", "repository": f"127.0.0.1:5000/rel/{PROJECT}-backend-prod",
             "digest": DIGEST, "web": False},
            {"name": f"{PROJECT}-frontend-prod", "repository": "x/y", "digest": DIGEST, "web": True},
        ],
    })
    return path


def _runs(user: bytes = b'"appuser"', control: bytes | None = None) -> Runs:
    import sys

    from terp.cli.release._common import run as real

    return (
        Runs(real=real)
        .on(sys.executable, "-c", out=json.dumps(ASSURANCE).encode())
        .on("docker", "pull")
        .on("docker", "image", "inspect", out=user)
        .on("docker", "run", out=control if control is not None else json.dumps(CONTROL_PLANE).encode())
    )


def test_the_gate_runs_the_release_profile_then_reads_the_schedules_sealed(tmp_path: pathlib.Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    sha = committed_app(repo)
    runs = _runs()
    seen: dict = {}
    real_call = runs.__call__

    def recording(argv, *, cwd=None, env=None, stdin=None):  # type: ignore[no-untyped-def]
        seen.setdefault(argv[0] if argv[0] != "docker" else " ".join(argv[:2]), (cwd, env))
        return real_call(argv, cwd=cwd, env=env, stdin=stdin)

    monkeypatch.setattr(gate, "run", recording)
    credentials = tmp_path / "pull.json"
    credentials.write_text('{"auths": {}}', encoding="utf-8")
    document = gate.gate(repo, sha, _build(tmp_path, sha), pull_credentials=credentials)
    assert document == {
        "terpReleaseGate": 1, "commit": sha, "assurance": ASSURANCE,
        "schedules": [{"name": "nightly.sync", "cron": "0 3 * * *", "job": "sync.pull"}],
        "image": f"127.0.0.1:5000/rel/{PROJECT}-backend-prod@{DIGEST}",
    }
    [verify] = [call for call in runs.calls if "verify" in call]
    assert verify[-5:] == list(gate.VERIFY)
    cwd, env = next(value for key, value in seen.items() if key not in ("docker pull", "docker image", "docker run"))
    assert pathlib.Path(cwd) == repo and env["npm_config_ignore_scripts"] == "true"
    [run] = runs.ran("docker", "run")
    assert {"--network", "none", "--read-only", "--cap-drop", "ALL"} <= set(run)
    assert run[run.index("--network") + 1] == "none" and run[run.index("--pull") + 1] == "never"
    assert run[-4:] == ["inspect", "control-plane", "--format", "json"]
    assert "--user" not in run, "the image runs as its own user, which the gate checked is not root"
    _cwd, pull_env = seen["docker pull"]
    assert "DOCKER_CONFIG" in pull_env and pathlib.Path(pull_env["DOCKER_CONFIG"]) != pathlib.Path.home() / ".docker"


@pytest.mark.parametrize("user", [b'""', b'"0"', b'"root"', b'"0:0"', b'"root:staff"'])
def test_an_image_that_runs_as_root_is_never_run(tmp_path: pathlib.Path, monkeypatch, user: bytes) -> None:
    repo = tmp_path / "repo"
    sha = committed_app(repo)
    runs = _runs(user=user)
    monkeypatch.setattr(gate, "run", runs)
    with pytest.raises(ReleaseError, match="runs as root"):
        gate.gate(repo, sha, _build(tmp_path, sha))
    assert not runs.ran("docker", "run")


def test_the_gate_runs_only_in_a_clean_checkout_of_the_build_s_commit(tmp_path: pathlib.Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    sha = committed_app(repo)
    monkeypatch.setattr(gate, "run", _runs())
    with pytest.raises(ReleaseError, match="is the build of 0+, not of"):
        gate.gate(repo, sha, _build(tmp_path, "0" * 40))
    (repo / "stray.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ReleaseError, match="with changes checked out"):
        gate.gate(repo, sha, _build(tmp_path, sha))


def test_an_assurance_document_and_a_schedule_catalog_are_required(tmp_path: pathlib.Path, monkeypatch) -> None:
    import sys

    repo = tmp_path / "repo"
    sha = committed_app(repo)
    monkeypatch.setattr(gate, "run", _runs().on(sys.executable, "-c", out=b"not json", err=b"Traceback"))
    with pytest.raises(ReleaseError, match="wrote no assurance document"):
        gate.gate(repo, sha, _build(tmp_path, sha))
    monkeypatch.setattr(gate, "run", _runs().on(sys.executable, "-c", out=b'{"ok": "yes"}'))
    with pytest.raises(ReleaseError, match="wrote no assurance claim"):
        gate.gate(repo, sha, _build(tmp_path, sha))
    monkeypatch.setattr(gate, "run", _runs(control=b"{}"))
    with pytest.raises(ReleaseError, match="printed no schedule catalog"):
        gate.gate(repo, sha, _build(tmp_path, sha))
    monkeypatch.setattr(gate, "run", _runs())
    with pytest.raises(ReleaseError, match="pushed 0 backend images"):
        gate.gate(repo, sha, _build(tmp_path, sha, images=[]))
