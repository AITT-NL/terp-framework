"""``terp release build | gate | sign`` and ``terp promote`` on the command line.

Each job is stood in for at its module, so what is held here is the command line itself: the
arguments reach the job, its document is written where ``--out`` says, its answer is printed,
and a refusal prints its sentence on standard error and exits 1.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from terp.cli import main
from terp.cli.release import build, gate, promote, sign
from terp.cli.release._common import ReleaseError

SHA = "a" * 40


def _exit(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as exited:
        main(argv)
    return int(exited.value.code or 0)


def test_release_build_writes_its_document_and_prints_what_it_pushed(tmp_path: pathlib.Path, monkeypatch, capsys) -> None:
    seen: dict = {}

    def fake(repo, sha, tag, target, **options):  # type: ignore[no-untyped-def]
        seen.update(repo=repo, sha=sha, tag=tag, target=target, **options)
        return {"terpReleaseBuild": 1, "images": [{"repository": "r.example/x", "tag": tag, "digest": "sha256:1"}]}

    monkeypatch.setattr(build, "build", fake)
    out = tmp_path / "b.json"
    assert _exit(["release", "build", "--sha", SHA, "--tag", "r1", "--registry", "r.example", "--registry-http",
                  "--platform", "linux/arm64", "--out", str(out)]) == 0
    assert seen == {"repo": ".", "sha": SHA, "tag": "r1", "target": "r.example", "platform": "linux/arm64", "registry_http": True}
    assert json.loads(out.read_text())["terpReleaseBuild"] == 1
    assert "pushed r.example/x:r1 as sha256:1" in capsys.readouterr().out


def test_a_refused_job_prints_its_sentence_and_exits_1(monkeypatch, capsys) -> None:
    from terp.cli.release._common import ReleaseError as Refusal

    def refuse(*args, **options):  # type: ignore[no-untyped-def]
        raise Refusal("terp release refuses this commit", cause="- .terp-dist/ is committed")

    monkeypatch.setattr(build, "build", refuse)
    assert _exit(["release", "build", "--sha", SHA, "--tag", "r1", "--registry", "r.example"]) == 1
    assert "terp release refuses this commit\n  - .terp-dist/ is committed" in capsys.readouterr().err


@pytest.mark.parametrize("ok", [True, False])
def test_release_gate_exits_with_its_claim(tmp_path: pathlib.Path, monkeypatch, capsys, ok: bool) -> None:
    monkeypatch.setattr(gate, "gate", lambda repo, sha, document, pull_credentials=None: {
        "terpReleaseGate": 1, "schedules": [], "image": "x@sha256:1", "assurance": {"ok": ok}})
    assert _exit(["release", "gate", "--sha", SHA, "--build", "b.json", "--out", str(tmp_path / "g.json")]) == (0 if ok else 1)
    assert ("holds" if ok else "does NOT hold") in capsys.readouterr().out


def test_release_sign_passes_its_options_through(monkeypatch, capsys) -> None:
    seen: dict = {}

    def fake(*args, **options):  # type: ignore[no-untyped-def]
        seen.update(args=args, **options)
        return {"images": ["x"], "keyid": "f" * 64, "envelope": "out/release.dsse.json"}

    monkeypatch.setattr(sign, "sign", fake)
    assert _exit(["release", "sign", "--sha", SHA, "--tag", "r1", "--registry", "r.example", "--build", "b", "--gate", "g",
                  "--hosts", "shared", "--signer", '["kms", "sign"]', "--public-key", "k.pub",
                  "--terp-index", "idx", "--osv", "https://osv.example"]) == 0
    assert seen["signer"] == ["kms", "sign"] and seen["hosts"] == "shared" and seen["index"] == "idx"
    assert seen["osv"] == "https://osv.example" and "releases" not in seen
    assert "signed x with key ffffffffffffffff" in capsys.readouterr().out


@pytest.mark.parametrize("signer", ["kms sign", "[]", '[1]', '{"a": 1}'])
def test_a_signer_that_is_not_an_argument_list_is_refused(capsys, signer: str) -> None:
    assert _exit(["release", "sign", "--sha", SHA, "--tag", "r1", "--registry", "r.example", "--build", "b", "--gate", "g",
                  "--hosts", "shared", "--signer", signer]) == 1
    assert "--signer is a JSON list of strings" in capsys.readouterr().err


def test_promote_prints_what_it_did_and_a_refusal_exits_1(monkeypatch, capsys) -> None:
    monkeypatch.setattr(promote, "promote", lambda *args, **options: ["verified r1", "promoted r1"])
    assert _exit(["promote", "release.dsse.json", "--public-key", "a.pub", "--public-key", "b.pub", "--project-dir", "d"]) == 0
    assert "promoted r1" in capsys.readouterr().out

    def refuse(*args, **options):  # type: ignore[no-untyped-def]
        raise ReleaseError("no signature verifies", cause="details")

    monkeypatch.setattr(promote, "promote", refuse)
    assert _exit(["promote", "e", "--public-key", "a.pub", "--project-dir", "d", "--rollback"]) == 1
    assert "no signature verifies\n  details" in capsys.readouterr().err


def test_release_sign_with_a_test_key_has_no_signer(monkeypatch, capsys) -> None:
    seen: dict = {}
    monkeypatch.setattr(sign, "sign", lambda *args, **options: seen.update(options) or {
        "images": [], "keyid": "0" * 64, "envelope": "e"})
    assert _exit(["release", "sign", "--sha", SHA, "--tag", "r1", "--registry", "r.example", "--build", "b", "--gate", "g",
                  "--hosts", "separated", "--sign-key", "k.pem", "--test-key", "--terp-arch-releases", "t.json"]) == 0
    assert seen["signer"] is None and seen["sign_key"] == "k.pem" and seen["test_key"] is True
    assert seen["releases"] == "t.json"
