"""Guardrail: every decision record has its own number, and says which one it is.

Added after two numbers collided in the working tree. Two lines of work numbered a new ADR
independently — one on ``main``, one on a feature branch — and both picked the next free number
they could see, which was the same one. Nothing noticed. The branch that merged second had to
renumber its record and every reference to it across the repository, and the references are the
expensive part: they sit in docstrings, tests, changelog entries and the OpenAPI descriptions
generated from those docstrings, and a stale one silently points a reader at somebody else's
decision.

Nothing here checks that the numbers are contiguous. A gap is a record that was withdrawn or a
number claimed in a branch that has not merged yet, and refusing either would make the gate an
obstacle rather than a guard.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

DECISIONS = Path(__file__).resolve().parents[2] / "docs" / "decisions"

#: ``0121-a-module-role-is-an-assignment-not-a-policy.md``
FILENAME = re.compile(r"(?P<number>\d{4})-[a-z0-9-]+\.md")

#: Both spellings are in use and both are fine — ``# 0121 — …`` and ``# ADR 0041 — …``. Only the
#: number is load-bearing, because it is what every reference in the codebase cites.
HEADING = re.compile(r"#\s*(?:ADR\s+)?(?P<number>\d{4})\b")


def _records() -> list[Path]:
    found = sorted(path for path in DECISIONS.glob("*.md") if FILENAME.fullmatch(path.name))
    # Guards the two tests below against a directory this stopped being able to see: an empty
    # list would make both of them pass while checking nothing at all.
    assert len(found) > 50, f"only {len(found)} decision records found under {DECISIONS}"
    return found


def test_every_decision_record_has_a_unique_number() -> None:
    by_number: dict[str, list[str]] = defaultdict(list)
    for path in _records():
        match = FILENAME.fullmatch(path.name)
        assert match is not None
        by_number[match.group("number")].append(path.name)

    collisions = {number: names for number, names in by_number.items() if len(names) > 1}
    assert not collisions, (
        "two decision records share a number, so every reference to it is ambiguous: "
        f"{collisions}. Renumber the one that has not been published yet — the record already "
        "on the default branch keeps its number, because references to it exist outside this "
        "repository too."
    )


def test_every_decision_record_states_its_own_number() -> None:
    """The heading has to agree with the filename, in the first line.

    The filename is what a link resolves to and the heading is what a reader sees, so a record
    whose two halves disagree sends a reader looking for the wrong decision — the exact failure
    a renumbering introduces if the heading is missed.
    """
    wrong: dict[str, str] = {}
    for path in _records():
        match = FILENAME.fullmatch(path.name)
        assert match is not None
        first_line = path.read_text(encoding="utf-8").split("\n", 1)[0]
        heading = HEADING.match(first_line)
        if heading is None or heading.group("number") != match.group("number"):
            wrong[path.name] = first_line.strip()[:80]

    assert not wrong, (
        "these decision records do not open with their own number: "
        f"{wrong}. The first line must be `# NNNN — title` (or `# ADR NNNN — title`), matching "
        "the filename."
    )
