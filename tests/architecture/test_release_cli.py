"""``terp release build | gate`` on the command line.

Each job is stood in for at its module, so what is held here is the command line itself: the
arguments reach the job, its document is written where ``--out`` says, its answer is printed,
and a refusal prints its sentence on standard error and exits 1.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from terp.cli import main
from terp.cli.release import build, gate

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
