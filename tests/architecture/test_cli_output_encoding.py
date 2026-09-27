"""``terp`` writes UTF-8 to a stream that would not, so a cp1252 pipe cannot end a command.

On Windows a pipe takes the ANSI code page, and a pipe is how an agent, an editor task or a
workbench reads the CLI. cp1252 has no ``→``, so ``terp dev`` died with
``UnicodeEncodeError`` on the line it prints before starting the servers. The subprocess
test below forces a cp1252 stdout on any platform, so it holds on a Linux runner too.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys

import pytest

from terp.cli._output import use_utf8_output


def _cp1252_stream() -> io.TextIOWrapper:
    # ``newline="\n"`` so the bytes compared below are the same on every platform.
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict", newline="\n")


def test_a_cp1252_stream_is_switched_to_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    out, err = _cp1252_stream(), _cp1252_stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    use_utf8_output()
    print("backend → uvicorn")
    print("stderr → too", file=sys.stderr)
    out.flush()
    err.flush()

    assert out.buffer.getvalue() == "backend → uvicorn\n".encode()  # type: ignore[attr-defined]
    assert err.buffer.getvalue() == "stderr → too\n".encode()  # type: ignore[attr-defined]


def test_a_utf8_stream_is_left_exactly_as_it_was(monkeypatch: pytest.MonkeyPatch) -> None:
    """``errors`` would read ``backslashreplace`` had the stream been reconfigured."""
    stream = io.TextIOWrapper(io.BytesIO(), encoding="UTF8", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", stream)

    use_utf8_output()

    assert (stream.encoding, stream.errors) == ("UTF8", "strict")


def test_a_stream_that_cannot_be_reconfigured_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replacement = io.StringIO()
    monkeypatch.setattr(sys, "stdout", replacement)
    monkeypatch.setattr(sys, "stderr", None)

    use_utf8_output()  # neither has a ``reconfigure``; nothing to do and nothing raised

    assert sys.stdout is replacement


def test_a_lone_surrogate_prints_as_an_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _cp1252_stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", _cp1252_stream())

    use_utf8_output()
    print("file-\udcff")
    out.flush()

    assert out.buffer.getvalue() == b"file-\\udcff\n"  # type: ignore[attr-defined]


def test_the_entry_point_switches_before_it_prints() -> None:
    """A real process with a cp1252 stdout: the em dash arrives as UTF-8, not as 0x97."""
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    env.pop("PYTHONUTF8", None)
    result = subprocess.run(
        [sys.executable, "-c", "from terp.cli import main; main(['guide'])"],
        capture_output=True,
        env=env,
        check=True,
    )
    assert "—".encode() in result.stdout
    assert b"\x97" not in result.stdout
