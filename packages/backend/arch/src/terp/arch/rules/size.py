"""File-size rule: no source file grows past the line-count cap.

A file that keeps growing stops being reviewable — it hides more than one
responsibility and is exactly what an automated author tends to produce when it
appends to an existing file instead of factoring the work into a new one. This
rule caps the physical line count of every scanned ``*.py`` file so a
responsibility that outgrows its file is split into its own file, not piled onto
the current one. Generated and machine-owned trees (dependency caches, the
database migration history, the test suite) are excluded by ``iter_python_files``
— their size is not an authoring decision the cap should second-guess.
"""

from __future__ import annotations

import pathlib

from terp.arch._ast import iter_python_files
from terp.arch.rules._support import ArchViolation, _rel

#: Maximum number of physical lines a scanned source file may have. A file at or
#: below this stays reviewable in one sitting; past it, split cohesive helpers or
#: sub-services into their own modules.
_MAX_FILE_LINES = 500


def check_no_oversized_python_files(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Every scanned ``*.py`` file stays at or under ``_MAX_FILE_LINES`` lines.

    Line count is physical (``str.splitlines``), so blank lines and comments count
    — the cap is about how much a reader has to scroll, not how much logic runs.
    Generated/vendored caches, the migration history and the test tree are excluded
    (``iter_python_files``); their size is not a hand-authored decision. A file past
    the cap is reported at line 1 so the opt-out marker lives naturally at the top.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        count = len(path.read_text(encoding="utf-8").splitlines())
        if count <= _MAX_FILE_LINES:
            continue
        violations.append(
            ArchViolation(
                "no_oversized_python_files",
                _rel(path, root),
                1,
                f"file has {count} lines, over the {_MAX_FILE_LINES}-line cap; split it "
                "into smaller, cohesive modules (extract helpers or sub-services into "
                "their own files) so each stays reviewable in one sitting",
            )
        )
    return violations


__all__ = ["check_no_oversized_python_files"]
