"""The signer image's build context: the framework's wheels, every distribution hash-locked.

``tools/signer_context.py`` writes what ``packages/backend/cli/signer/Dockerfile`` builds from
(ADR 0187 decision 6); CI builds and runs the image from it. Held here: what the requirements
file pins, that nothing unhashed reaches it, and that the Dockerfile installs only by hash and
pins every image it copies from by digest.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import runpy
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tools"))
import signer_context  # noqa: E402

DOCKERFILE = signer_context.SIGNER / "Dockerfile"
EXPORTED = "alembic==1.20.1 \\\n    --hash=sha256:" + "a" * 64


def _runner(calls: list):  # type: ignore[no-untyped-def]
    def run(argv):  # type: ignore[no-untyped-def]
        calls.append(list(argv))
        if argv[:2] == ("uv", "build"):
            out = pathlib.Path(argv[argv.index("--out-dir") + 1])
            name = pathlib.Path(argv[-1]).name.replace("capabilities/", "")
            (out / f"terp_{name}-0.34.0-py3-none-any.whl").write_bytes(name.encode())
            return ""
        return EXPORTED

    return run


def test_the_context_pins_every_wheel_this_run_built_and_the_lock_s_hashes(tmp_path: pathlib.Path) -> None:
    calls: list = []
    signer_context.write_context(tmp_path / "ctx", run=_runner(calls))
    requirements = (tmp_path / "ctx" / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert requirements[:2] == EXPORTED.splitlines()
    # By its file, never by name and version: between two releases the tree's version is the
    # last published one, and an index then answers for that name with the published wheel,
    # whose hash is not this build's (the signer image's first real build failed so).
    assert (
        f"terp-cli @ file:///wheels/terp_cli-0.34.0-py3-none-any.whl "
        f"--hash=sha256:{hashlib.sha256(b'cli').hexdigest()}"
    ) in requirements
    assert len([line for line in requirements if line.startswith("terp-")]) == len(signer_context.PACKAGES)
    assert all(" @ file:///wheels/" in line for line in requirements if line.startswith("terp-"))
    assert calls[-1] == list(signer_context.EXPORT)
    assert {"Dockerfile", "terp-arch-releases.json", "requirements.txt", "wheels"} == {
        path.name for path in (tmp_path / "ctx").iterdir()}


def test_nothing_unhashed_and_no_wheel_it_cannot_name_reaches_the_image(tmp_path: pathlib.Path) -> None:
    with pytest.raises(SystemExit, match="answered no hashes"):
        signer_context.write_context(tmp_path / "ctx", run=lambda argv: "alembic==1.20.1")
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "terp_x-1-cp314-win_amd64.whl").write_bytes(b"")
    with pytest.raises(SystemExit, match="is not a pure-Python wheel"):
        signer_context.pinned_wheels(tmp_path / "w")
    with pytest.raises(SystemExit, match="exists"):
        signer_context.write_context(tmp_path / "w", run=_runner([]))


def test_the_command_line_writes_the_context(tmp_path: pathlib.Path, monkeypatch, capsys) -> None:
    seen: list = []
    monkeypatch.setattr(signer_context, "write_context", lambda destination: seen.append(destination))
    assert signer_context.main([str(tmp_path / "ctx")]) == 0
    assert seen == [tmp_path / "ctx"] and "wrote the signer's build context" in capsys.readouterr().out
    calls: list = []
    monkeypatch.setattr(signer_context.subprocess, "run", lambda argv, **kw: calls.append(argv) or type("R", (), {"stdout": "ok"})())
    assert signer_context._run(["uv", "version"]) == "ok" and calls == [["uv", "version"]]
    monkeypatch.setattr(sys, "argv", ["signer_context.py", str(tmp_path / "ctx2")])
    monkeypatch.setattr(signer_context.subprocess, "run", lambda argv, **kw: type("R", (), {"stdout": ""})())
    with pytest.raises(SystemExit) as exited:
        runpy.run_path(str(signer_context.REPO_ROOT / "tools" / "signer_context.py"), run_name="__main__")
    assert "answered no hashes" in str(exited.value)


def test_the_signer_image_installs_only_by_hash_and_copies_only_from_digests() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    froms = re.findall(r"^FROM (\S+)", text, re.MULTILINE)
    assert froms and all("@sha256:" in image for image in froms), froms
    assert "--require-hashes" in text and "--no-deps" in text
    # No index or link may stand in for a framework wheel: the file names each one.
    assert "--find-links" not in text and "COPY wheels/ /wheels/" in text
    assert re.search(r"^USER (?!root|0)\S+", text, re.MULTILINE)
    from terp.arch.deployment.tables import published_tables

    assert published_tables().base_images.get("python").image in text, "the signer runs the table's interpreter"
    assert (signer_context.SIGNER / "terp-arch-releases.json").read_text(encoding="utf-8") == (
        '{"releases":{},"terpArchReleases":1}\n'
    )
