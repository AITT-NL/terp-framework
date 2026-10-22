"""What the three release jobs and ``terp promote`` share: the error, the tag, bytes, processes.

Every job reads and writes JSON documents another job or a deploy tool reads back, so each is
written one way, :func:`canonical`: sorted keys, no whitespace, UTF-8 and no floats, the form
the signed manifest takes (ADR 0187 decision 6). Every external program - git, docker, uv,
gitleaks - is run through :func:`run`: a fixed argument list, no shell, a missing program an
answer rather than a traceback, and one seam a test replaces.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any

#: The per-release tag: Docker's own tag grammar, because it is the tag of every image a
#: release pushes and the value ``TERP_RELEASE_TAG`` takes when the release is promoted.
RELEASE_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")

#: An exact commit: the full object name, SHA-1 or SHA-256. A branch, a tag or an abbreviation
#: names whatever it names at the moment it is read, and a release is cut from one commit.
COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")

#: The exit status a shell gives a program it cannot find; :func:`run` answers the same.
NOT_FOUND = 127


class ReleaseError(Exception):
    """A release job or ``terp promote`` refusing, in a sentence written for its operator.

    *cause* is what a program or a library said, kept apart from the sentence so the sentence
    stays the job's own words; the command line prints both.
    """

    def __init__(self, message: str, *, cause: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause.strip()

    def __str__(self) -> str:
        return f"{self.message}\n  {self.cause}" if self.cause else self.message


def release_tag(value: str) -> str:
    """*value* when it is a release tag, refused otherwise."""
    if RELEASE_TAG.fullmatch(value) is None:
        raise ReleaseError(
            f"{value!r} is not a release tag (allowed: letters, digits, '_', '.' and '-', at "
            "most 128, not starting with '.' or '-': a Docker image tag)"
        )
    return value


def commit_id(value: str) -> str:
    """*value* when it names one commit exactly, refused otherwise."""
    if COMMIT.fullmatch(value) is None:
        raise ReleaseError(
            f"{value!r} is not an exact commit (allowed: the full 40- or 64-character "
            "lower-case hexadecimal object name; a branch, a tag or a prefix moves)"
        )
    return value


def _no_floats(value: Any, where: str = "") -> None:
    if isinstance(value, float):
        raise ReleaseError(f"{where or 'the document'} holds a float, which no release document may")
    if isinstance(value, dict):
        for key, item in value.items():
            _no_floats(item, f"{where}.{key}" if where else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _no_floats(item, f"{where}[{index}]")


def canonical(value: Any) -> bytes:
    """*value* as the one byte string every release document is: sorted, compact, UTF-8."""
    _no_floats(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256(data: bytes) -> str:
    """The hexadecimal SHA-256 of *data*."""
    return hashlib.sha256(data).hexdigest()


def read_document(path: str | os.PathLike[str], kind: str, version: int = 1) -> dict[str, Any]:
    """A job's JSON document at *path*: one object whose *kind* key holds *version*."""
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ReleaseError(f"{path} is not a readable JSON document", cause=str(exc)) from exc
    if not isinstance(loaded, dict) or loaded.get(kind) != version:
        raise ReleaseError(f"{path} is not a {kind} document of version {version}")
    return loaded


def write_document(path: str | os.PathLike[str], value: dict[str, Any]) -> None:
    """Write *value* canonically, with a final newline, so it reads back as written."""
    with open(path, "wb") as handle:
        handle.write(canonical(value) + b"\n")


def run(
    argv: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    stdin: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run *argv* exactly as given, no shell; a program not found exits :data:`NOT_FOUND`.

    *env* replaces the environment when given: a job decides what a program it runs may see.
    """
    executable = shutil.which(argv[0]) or argv[0]
    try:
        return subprocess.run(  # noqa: S603 - a fixed argument list, never a shell
            [executable, *argv[1:]],
            cwd=cwd,
            env=None if env is None else dict(env),
            input=stdin,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(
            list(argv), NOT_FOUND, b"", f"{argv[0]}: not found on PATH".encode()
        )


def output_of(completed: subprocess.CompletedProcess[bytes]) -> str:
    """A finished program's standard error, then its output, as text for a message."""
    return (completed.stderr + completed.stdout).decode("utf-8", errors="replace").strip()


def require(completed: subprocess.CompletedProcess[bytes], what: str) -> bytes:
    """The output of a program that had to succeed, or a refusal naming what failed."""
    if completed.returncode != 0:
        raise ReleaseError(f"{what} failed (exit {completed.returncode})", cause=output_of(completed)[-4000:])
    return completed.stdout


#: Where a job finds the programs it runs and their own per-user files, and nothing else of the
#: operator's environment: the operating system's names, POSIX and Windows alike.
_OS_NAMES = (
    "PATH", "HOME", "TEMP", "TMP", "TMPDIR", "LANG", "SYSTEMROOT", "WINDIR", "COMSPEC",
    "PATHEXT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
)

#: What a docker client needs to reach its engine, beside the operating system's names.
DOCKER_NAMES = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY")


def os_environment(
    extra: Mapping[str, str] | None = None,
    *,
    names: Sequence[str] = (),
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The operating system's own variables, *names* too, then *extra*: from *source*, this
    process's environment by default."""
    given = os.environ if source is None else source
    wanted = (*_OS_NAMES, *names)
    found = {name: given[name] for name in wanted if name in given}
    return {**found, **(extra or {})}


__all__ = [
    "COMMIT",
    "DOCKER_NAMES",
    "NOT_FOUND",
    "RELEASE_TAG",
    "ReleaseError",
    "canonical",
    "commit_id",
    "os_environment",
    "output_of",
    "read_document",
    "release_tag",
    "require",
    "run",
    "sha256",
    "write_document",
]
