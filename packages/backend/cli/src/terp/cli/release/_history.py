"""One migration history's listing, read from its revision files' source: what ``sign`` records.

Each revision file is read as data, never imported: its header with
:func:`terp.arch.revision_header`, its ``depends_on`` with :func:`terp.arch.revision_depends_on`,
and its operations with :func:`terp.arch.destructive_operations`, which lists the operations of
its ``upgrade()`` its static reading recognises as destructive, excused by their marker or not,
and each call it cannot see into as ``opaque``: what the reading recognises, no more. The listing is ``{"revisions": [{"id", "down"}], "operations": [{"revision",
"ordinal", "kind", "operation"}]}``, ``down`` being the revisions one follows: none for a base,
one, or several for a merge. Revisions are sorted by id, each ``down`` sorted, and operations by
revision then ordinal, all by code point, so one image and one tree give one byte string.

A history a deploy's plan cannot hold is refused by name rather than listed: a revision that is
no source text the interpreter can decode, that does not parse, that nests deeper than the
reading goes, or whose header cannot be read for certain; an id or a parent outside
``^[0-9A-Za-z_]{1,64}$``; a parent named twice, or more parents than a plan holds; a
``depends_on`` that is not ``None``; a revision id given twice, a parent that is no revision of the
history, a cycle; an operation whose text holds a lone surrogate, which no UTF-8 document holds;
and more revisions or operations than a plan holds.
"""

from __future__ import annotations

import importlib.util
import re
import reprlib
from typing import Any

from terp.arch import DestructiveOperation, RevisionHeader, destructive_operations, revision_depends_on, revision_header

#: The ids a deploy's plan holds.
_REVISION_ID = re.compile(r"[0-9A-Za-z_]{1,64}")

#: How many revisions and how many operations a plan holds for one history, and how many
#: revisions one revision may follow. No ordinal can pass the plan's 9,999 within a history's
#: 4,096 operations, since a revision counts its operations from 1.
MOST_IN_HISTORY = 4096
MOST_PARENTS = 16


def _encodes(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _undecodable(exc: SyntaxError | UnicodeError | LookupError) -> str:
    if isinstance(exc, SyntaxError):  # the coding declaration, or the bytes before it
        return exc.msg
    if isinstance(exc, UnicodeDecodeError):
        return f"its bytes are not {exc.encoding}"
    return "its coding declaration names no text encoding"


def _revision(
    label: str, path: str, data: bytes, findings: list[str]
) -> tuple[RevisionHeader, list[DestructiveOperation]] | None:
    """One revision file's header and operations, read from its source, or ``None`` unreadable."""
    named = f"{path}, a revision of the migration history {label!r},"
    try:
        source = importlib.util.decode_source(data)
    except (SyntaxError, UnicodeError, LookupError) as exc:
        findings.append(
            f"{named} is no source text the interpreter can decode ({_undecodable(exc)}): write it in "
            "UTF-8, as Alembic's template does; the upgrade would not load it either"
        )
        return None
    try:
        header = revision_header(source)
        depends_on = revision_depends_on(source)
        steps = destructive_operations(source)
    except SyntaxError as exc:
        where = f"{exc.msg}, line {exc.lineno}" if exc.lineno else exc.msg
        findings.append(
            f"{named} is no Python source sign can parse ({where}): correct the file, which the "
            "upgrade would fail to load"
        )
        return None
    except (MemoryError, RecursionError):  # past the parser's depth, or past the reading's
        findings.append(
            f"{named} nests too deeply for sign to read it: break up the expression that nests so deep"
        )
        return None
    except ValueError as exc:
        findings.append(
            f"{named} has a header sign cannot read for certain ({exc}): assign revision, "
            "down_revision and depends_on once each, at the top level and to a literal, as "
            "Alembic's template writes them"
        )
        return None
    for given in (header.revision, *header.parents):
        if _REVISION_ID.fullmatch(given) is None:
            findings.append(
                f"{path} names the revision {given!r}, outside ^[0-9A-Za-z_]{{1,64}}$, the ids a "
                "deploy's plan holds: give the revision an id of letters, digits and underscores "
                "(Alembic's own are twelve hexadecimal digits)"
            )
    for parent in sorted({parent for parent in header.parents if header.parents.count(parent) > 1}):
        findings.append(f"{path} names {parent!r} more than once in its down_revision: name each revision it follows once")
    if len(header.parents) > MOST_PARENTS:
        findings.append(
            f"{path} follows {len(header.parents)} revisions, more than the {MOST_PARENTS} a deploy's "
            "plan holds for one revision: merge the heads in steps"
        )
    if depends_on is not None:
        findings.append(
            f"{path} sets depends_on to {reprlib.repr(depends_on)}: Alembic then writes only the "
            "dependent revision to the version table, so a deploy that follows down_revision would "
            "count the other pending ever after, and a Terp history is linear (ADR 0027); order "
            "the two by down_revision and set depends_on to None"
        )
    for step in steps:
        if not _encodes(step.operation):
            findings.append(
                f"{named} lists the operation {ascii(step.operation)}, whose text holds a lone surrogate "
                "UTF-8 cannot encode: write the string literal it comes from without that escape"
            )
    return header, [step for step in steps if _encodes(step.operation)]


def _cycle(down: dict[str, tuple[str, ...]]) -> list[str]:
    """One cycle through ``down`` among the revisions of *down*, as the ids along it, each
    following the next, or none.

    A revision no other follows is a head, and a head lies on no cycle: taking the heads away,
    and then the revisions only they followed, until none is left to take, leaves exactly the
    revisions on a cycle and those a cycle follows. Each of those is followed by another left,
    so a walk from one to a revision that follows it comes round to where it has been.
    """
    parents = {revision: set(given) & down.keys() for revision, given in down.items()}
    followed = dict.fromkeys(parents, 0)
    for given in parents.values():
        for parent in given:
            followed[parent] += 1
    heads = [revision for revision, count in followed.items() if count == 0]
    while heads:
        for parent in parents.pop(heads.pop()):
            followed[parent] -= 1
            if followed[parent] == 0:
                heads.append(parent)
    follower: dict[str, str] = {}
    for revision in sorted(parents):  # the first by code point, whatever the files are called
        for parent in parents[revision]:
            follower.setdefault(parent, revision)
    walk: list[str] = []
    step = min(parents, default=None)
    while step is not None and step not in walk:
        walk.append(step)
        step = follower[step]
    return [] if step is None else [*walk[walk.index(step) :], step][::-1]


def listing(label: str, revisions: tuple[tuple[str, bytes], ...], findings: list[str]) -> dict[str, list[dict[str, Any]]]:
    """The history *label*'s ``{"revisions", "operations"}``, from its revision files' bytes by
    the path a refusal names, each array sorted by code point; what cannot be listed goes to
    *findings*."""
    files: dict[str, list[str]] = {}
    down: dict[str, tuple[str, ...]] = {}
    operations: list[dict[str, Any]] = []
    for path, data in revisions:
        read = _revision(label, path, data, findings)
        if read is None:
            continue
        header, steps = read
        files.setdefault(header.revision, []).append(path)
        down[header.revision] = header.parents
        operations.extend(
            {"revision": header.revision, "ordinal": step.ordinal, "kind": step.kind, "operation": step.operation}
            for step in steps
        )
    for revision, given_by in sorted(files.items()):
        if len(given_by) > 1:
            findings.append(
                f"the migration history {label!r} has the revision {revision!r} in {' and '.join(given_by)}: "
                "give each revision an id of its own"
            )
    for revision, parents in sorted(down.items()):
        for parent in sorted(set(parents) - down.keys()):
            findings.append(
                f"the revision {revision!r} of the migration history {label!r} follows {parent!r}, which "
                "is no revision of that history: point its down_revision at one the history holds"
            )
    cycle = _cycle(down)
    if cycle:
        findings.append(
            f"the migration history {label!r} runs in a cycle through down_revision ({' -> '.join(cycle)}, "
            "each following the next): a history starts at a revision that follows none, and each "
            "revision follows earlier ones"
        )
    for counted, what in ((len(down), "revisions"), (len(operations), "operations")):
        if counted > MOST_IN_HISTORY:
            findings.append(
                f"the migration history {label!r} lists {counted} {what}, more than the "
                f"{MOST_IN_HISTORY} a deploy's plan holds for one history: squash its earliest revisions"
            )
    return {
        "revisions": [{"id": revision, "down": sorted(down[revision])} for revision in sorted(down)],
        "operations": sorted(operations, key=lambda step: (step["revision"], step["ordinal"])),
    }


__all__ = ["MOST_IN_HISTORY", "MOST_PARENTS", "listing"]
