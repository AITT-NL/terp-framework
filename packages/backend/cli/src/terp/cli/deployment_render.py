"""``terp deployment render`` and ``terp verify --only generated`` (ADR 0187 decision 3).

Where ``deployment.json`` says ``"build": "generated"``, ``Dockerfile.prod``,
``frontend/Dockerfile.prod`` and ``docker-compose.prod.yml`` are the framework's to write:
``terp deployment render`` writes the generator's render of the declaration, the project name
and this framework release's tables, and removes a generator-owned file the declaration no
longer renders. It writes every file or none, and refuses with the generator's own words what
the generator cannot render; it never writes for any other state, because under ``own`` the
files are the app's.

The gate never writes (a gate that wrote would hide the change from review). ``terp verify
--only generated``, and ``terp deployment render --check``, run the
``deployment_generated_files_match_their_render`` rule: red when a committed copy is not the
render, when an environment file a unit loads is not ignored, or when the template's recorded
build disagrees; silent for an undeclared app, ``own``, ``unmanaged`` and a declaration that
cannot be read; with notes for what it does not judge and for a profile ``terp release`` will
refuse.

It is its own check rather than part of ``--only deployment``, for the reason ``locks`` is: a
stale render contradicts nothing the declaration says.
"""

from __future__ import annotations

import os
import pathlib

from terp.arch.deployment import Generated, generated
from terp.arch.deployment.generator import OWNED_PATHS
from terp.arch.deployment.render_check import RENDER_COMMAND
from terp.cli._output import emit

#: The suffix of a file being written, replaced over its target once every file is written.
_PENDING = ".terp-render"


def _lines(result: Generated) -> list[str]:
    out: list[str] = []
    for finding in result.drift.findings:
        out.append(f"- {finding.file}: {finding.message}")
        if finding.remedy:
            out.append(f"  {finding.remedy}")
    return out


def _notes(result: Generated) -> list[str]:
    from terp.cli.verify import NOTE_PREFIX

    return [f"{NOTE_PREFIX}{note}" for note in result.drift.notes]


def run_generated_check(project_root: pathlib.Path) -> tuple[int, str]:
    """The ``generated`` verify runner: ``(exit_code, output)``."""
    result = generated(project_root)
    if not result.applies:
        return 0, f"{result.reason} (nothing to compare with a render)"
    if result.drift.findings:
        return 1, "\n".join(
            [
                'deployment.json says "build": "generated", and what is committed is not what '
                "the generator renders from it.",
                "",
                *_lines(result),
                *_notes(result),
            ]
        )
    return 0, "\n".join(
        [
            "every generator-owned file is the render of deployment.json: "
            + ", ".join(path for path in OWNED_PATHS if path in result.drift.files),
            *_notes(result),
        ]
    )


def write_files(
    project_root: pathlib.Path, files: dict[str, bytes], removed: list[str]
) -> None:
    """Write every one of *files* or none, then remove *removed*.

    Each file is staged beside its target first, so a write that fails part-way leaves every
    committed file as it was; the staged files then replace their targets.
    """
    pending: list[tuple[pathlib.Path, pathlib.Path]] = []
    try:
        for path, data in files.items():
            target = project_root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            staged = target.with_name(target.name + _PENDING)
            staged.write_bytes(data)
            pending.append((staged, target))
    except OSError:
        for staged, _target in pending:
            staged.unlink(missing_ok=True)
        raise
    for staged, target in pending:
        os.replace(staged, target)
    for path in removed:
        (project_root / path).unlink()


def render_changes(
    project_root: pathlib.Path, files: dict[str, bytes]
) -> tuple[list[str], list[str]]:
    """The owned paths a render writes because they differ, and the ones it removes."""
    changed = [
        path
        for path, data in files.items()
        if not (project_root / path).is_file() or (project_root / path).read_bytes() != data
    ]
    stale = [path for path in OWNED_PATHS if path not in files and (project_root / path).exists()]
    return changed, stale


def _write_all(project_root: pathlib.Path, files: dict[str, bytes]) -> list[str]:
    """Write every file or none, remove the owned paths the render has not got; what changed."""
    changed, stale = render_changes(project_root, files)
    write_files(project_root, {path: files[path] for path in changed}, stale)
    return [*(f"wrote {path}" for path in changed), *(f"removed {path}" for path in stale)]


def run_render_command(*, root: str | pathlib.Path = ".", check: bool = False) -> int:
    """``terp deployment render [--check]``: the exit code; what it did is printed."""
    project_root = pathlib.Path(root)
    if check:
        code, output = run_generated_check(project_root)
        emit(output)
        return code
    result = generated(project_root)
    if not result.applies:
        emit(f"nothing rendered: {result.reason}")
        emit(
            'The generator writes the build files only where deployment.json says "build": '
            '"generated".'
        )
        return 1
    if not result.drift.files:
        emit("nothing rendered: the generator cannot render deployment.json as it stands.")
        emit("")
        emit("\n".join(_lines(result)))
        return 1
    done = _write_all(project_root, result.drift.files)
    emit("\n".join(done) or "every generator-owned file was already the render")
    after = generated(project_root)
    if after.drift.findings:
        emit("")
        emit("still red under `terp verify --only generated`:")
        emit("\n".join(_lines(after)))
        return 1
    emit("commit them together with deployment.json")
    return 0


__all__ = [
    "RENDER_COMMAND",
    "render_changes",
    "run_generated_check",
    "run_render_command",
    "write_files",
]
