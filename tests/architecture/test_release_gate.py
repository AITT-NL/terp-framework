"""``terp release gate``: the release profile, and the schedules read from the pushed image.

ADR 0187 decision 6. The gate runs the app, so it holds nothing a release is protected by: its
docker client gets a configuration directory of its own, and the pushed image is run sealed,
as its own non-root user, with no network. ADR 0200: it runs the release profile once, and
records every check's verdict beside the claim those same results compose, and nothing any
check printed.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

from terp.cli.release import gate
from terp.cli.release._common import ReleaseError, canonical, write_document
from terp.cli.verify import PROFILES, assurance_document
from tests.architecture.release_fixtures import PROJECT, Runs, committed_app

DIGEST = "sha256:" + "1" * 64
CONTROL_PLANE = {"schedules": [{"name": "nightly.sync", "cron": "0 3 * * *", "job": "sync.pull", "extra": "x"}]}

#: Every check of the release profile, green: what the gate records of a green run.
CHECKS = [{"id": check.id, "ok": True, "applicable": True} for check in PROFILES["release"]]


def _printed(
    red: tuple[str, ...] = (), *, app: tuple[str, ...] = (), said: str = "", inapplicable: tuple[str, ...] = ()
) -> bytes:
    """What ``terp verify --profile release --format json`` prints: every check of the profile,
    then the app's own, each with more than the gate keeps of it."""
    checks = [
        {"id": check, "category": "test", "command": f"terp verify --only {check}", "scope": ["app/**"],
         "ok": check not in red, "applicable": check not in inapplicable, "exit_code": int(check in red),
         "output_tail": f"no conformance/ - {check} not applicable" if check in inapplicable else said,
         "reports": []}
        for check in [*(check.id for check in PROFILES["release"]), *app]
    ]
    return json.dumps({"terp_verify": 1, "profile": "release", "ok": not red, "checks": checks}).encode()


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


def _runs(user: bytes = b'"appuser"', control: bytes | None = None, printed: bytes | None = None) -> Runs:
    from terp.cli.release._common import run as real

    return (
        Runs(real=real)
        .on(sys.executable, "-c", out=printed if printed is not None else _printed())
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
        "terpReleaseGate": 3, "commit": sha,
        "profile": {"name": "release", "ok": True, "checks": CHECKS}, "assurance": assurance_document(CHECKS),
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


def test_the_gate_records_every_check_and_the_claim_of_one_run(tmp_path: pathlib.Path, monkeypatch) -> None:
    """ADR 0200 decision 1. Two checks no required lane composes are red, so the claim still holds:
    the document records both red beside it, the app's own check among them, from the one run the
    claim was composed of, and nothing either check printed."""
    repo = tmp_path / "repo"
    sha = committed_app(repo)
    said = "SOME_API_TOKEN=an-example-value-a-failing-check-printed"
    runs = _runs(printed=_printed(("api-contract", "domain-invariants"), app=("domain-invariants",), said=said))
    composed: list = []
    monkeypatch.setattr(gate, "assurance_document", lambda results: composed.append(results) or assurance_document(results))
    monkeypatch.setattr(gate, "run", runs)
    document = gate.gate(repo, sha, _build(tmp_path, sha))
    assert len(runs.ran(sys.executable, "-c")) == 1, "the release profile runs once, for both verdicts"
    checks = document["profile"]["checks"]
    assert document["terpReleaseGate"] == 3 and document["profile"]["ok"] is False
    assert [check["id"] for check in checks] == [*(check.id for check in PROFILES["release"]), "domain-invariants"]
    assert [check["id"] for check in checks if not check["ok"]] == ["api-contract", "domain-invariants"]
    assert all(sorted(check) == ["applicable", "id", "ok"] for check in checks), (
        "a check is its id, its verdict and whether it had anything to judge"
    )
    assert composed == [checks], "the claim is composed from the very checks the document records"
    assert document["assurance"] == assurance_document(checks) and document["assurance"]["ok"] is True
    assert said not in canonical(document).decode(), "nothing a check printed reaches the document"
    assert gate.red(document) == ["api-contract", "domain-invariants"]


def test_what_a_red_check_printed_goes_to_the_gate_s_own_log_and_nowhere_else(
    tmp_path: pathlib.Path, monkeypatch, capsys
) -> None:
    """ADR 0200 decision 1. The document carries no check's output, so the operator reads why a
    check is red in the log of the job that ran the gate: the gate writes each red check's tail
    there, and nothing of a green one."""
    repo = tmp_path / "repo"
    sha = committed_app(repo)
    said = "openapi.json records a field the app no longer serves"
    runs = _runs(printed=_printed(("api-contract",), said=said))
    monkeypatch.setattr(gate, "run", runs)
    document = gate.gate(repo, sha, _build(tmp_path, sha))
    captured = capsys.readouterr()
    assert "verify: api-contract FAILED\n" + said in captured.out
    assert captured.out.count("FAILED") == 1, "a green check prints nothing"
    assert said not in canonical(document).decode()


def test_a_check_with_nothing_to_judge_is_recorded_so_and_its_lane_is_not_run(
    tmp_path: pathlib.Path, monkeypatch, capsys
) -> None:
    """ADR 0202 decision 4: an app with no conformance suite has nothing for the suite to judge.
    The gate records that, so the lane the suite alone composes is not-run in the claim it writes,
    as ``terp verify`` says, and the gate's log says why rather than staying silent about it."""
    repo = tmp_path / "repo"
    sha = committed_app(repo)
    monkeypatch.setattr(gate, "run", _runs(printed=_printed(inapplicable=("conformance",))))
    document = gate.gate(repo, sha, _build(tmp_path, sha))
    [suite] = [check for check in document["profile"]["checks"] if check["id"] == "conformance"]
    assert suite == {"id": "conformance", "ok": True, "applicable": False}
    lanes = {lane["id"]: lane for lane in document["assurance"]["lanes"]}
    assert lanes["blackbox-conformance"] == {"id": "blackbox-conformance", "status": "not-run", "checks": []}
    assert "verify: conformance not applicable: no conformance/ - conformance not applicable" in capsys.readouterr().out
    gate.require_passed(document, gate.APPLICABLE_SINCE)


def _verdict(**changes) -> bytes:  # type: ignore[no-untyped-def]
    printed = json.loads(_printed())
    for key, value in changes.items():
        printed[key] = value(printed[key]) if callable(value) else value
    return json.dumps(printed).encode()


@pytest.mark.parametrize(
    "printed",
    [
        b'{"ok": "yes"}',
        b"[]",
        _verdict(terp_verify=2),
        _verdict(profile="full"),
        _verdict(checks=[]),
        _verdict(checks="architecture"),
        _verdict(checks=lambda checks: [*checks, {"id": "x", "ok": "yes"}]),
        _verdict(checks=lambda checks: [*checks, {"ok": True}]),
        _verdict(checks=lambda checks: [*checks, "x"]),
        _verdict(checks=lambda checks: [*checks, {"id": "x", "ok": False}]),
        _verdict(checks=lambda checks: [{key: value for key, value in check.items() if key != "applicable"} for check in checks]),
        _verdict(checks=lambda checks: [{**check, "applicable": "yes"} for check in checks]),
        _verdict(ok=False),
        _verdict(ok="yes"),
    ],
)
def test_a_run_that_wrote_no_verdict_of_each_check_is_refused(tmp_path: pathlib.Path, monkeypatch, printed: bytes) -> None:
    """A run the gate cannot read as each check's verdict is refused before the image is pulled,
    including one whose ``ok`` its checks contradict: green over a red check, or red over none."""
    repo = tmp_path / "repo"
    sha = committed_app(repo)
    runs = _runs(printed=printed)
    monkeypatch.setattr(gate, "run", runs)
    with pytest.raises(ReleaseError, match="terp verify --profile release wrote no verdict of each check it ran"):
        gate.gate(repo, sha, _build(tmp_path, sha))
    assert not runs.ran("docker"), "the image is not pulled for a run that said nothing"


def test_a_verdict_document_and_a_schedule_catalog_are_required(tmp_path: pathlib.Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    sha = committed_app(repo)
    monkeypatch.setattr(gate, "run", _runs().on(sys.executable, "-c", out=b"not json", err=b"Traceback"))
    with pytest.raises(ReleaseError, match="wrote no verdict document\n  Traceback"):
        gate.gate(repo, sha, _build(tmp_path, sha))
    monkeypatch.setattr(gate, "run", _runs(control=b"{}"))
    with pytest.raises(ReleaseError, match="printed no schedule catalog"):
        gate.gate(repo, sha, _build(tmp_path, sha))
    monkeypatch.setattr(gate, "run", _runs())
    with pytest.raises(ReleaseError, match="pushed 0 backend images"):
        gate.gate(repo, sha, _build(tmp_path, sha, images=[]))


def test_what_a_secret_scanner_printed_is_not_relayed(tmp_path: pathlib.Path, monkeypatch, capsys) -> None:
    """A scanner's matched line is the secret it found, so a red secret-scanning check is named
    in the gate's log and its output is not, with the command that shows it in a checkout."""
    repo = tmp_path / "repo"
    sha = committed_app(repo)
    said = "SOME_API_TOKEN=an-example-value-the-scanner-matched"
    runs = _runs(printed=_printed(("secret-scanning",), said=said))
    monkeypatch.setattr(gate, "run", runs)
    gate.gate(repo, sha, _build(tmp_path, sha))
    out = capsys.readouterr().out
    assert "verify: secret-scanning FAILED" in out and "is not relayed" in out
    assert "`terp verify --only secret-scanning`" in out
    assert said not in out
