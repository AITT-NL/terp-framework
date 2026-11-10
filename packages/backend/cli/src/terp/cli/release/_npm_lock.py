"""The npm lock a web image installs, read from where the image is built.

A web image's SBOM is read from an npm lock, and ``sign`` vouches for that list, so the lock
has to be the one the image installs. The Dockerfile says which: the ``package-lock.json`` it
copies from its build context. Only when it names none (``COPY . .``) is the lock looked for
by position, beside the Dockerfile or at the root of the context, and then one of the two may
exist, never both: two locks and nothing to choose between them is refused, because choosing
by position signed the SBOM of whichever lock stood first.

Nothing is run here. The Dockerfile is text, read with the parser ``sign`` compares an
image's configuration with (:mod:`terp.cli.release._dockerfile`).
"""

from __future__ import annotations

import fnmatch
import json
import posixpath
from typing import Protocol

from terp.cli.release import _dockerfile
from terp.cli.release._common import ReleaseError

#: The file a web image's npm lock is.
LOCK_FILE = "package-lock.json"


class Files(Protocol):
    """What the plan asks a commit's tree, or the files on disk."""

    def has(self, path: str) -> bool: ...

    def read_text(self, path: str) -> str: ...


def candidates(context: str, dockerfile: str) -> list[str]:
    """Where a lock the Dockerfile does not name may be, in the order looked for, each once."""
    found: list[str] = []
    for place in (posixpath.dirname(dockerfile), context):
        candidate = posixpath.normpath(posixpath.join(place, LOCK_FILE))
        if candidate not in found:
            found.append(candidate)
    return found


def _sources(rest: str) -> list[str]:
    """The sources of one ``COPY`` or ``ADD`` from the build context; none from elsewhere."""
    if rest.lstrip().startswith("["):
        try:
            words = [str(word) for word in json.loads(rest)]
        except ValueError:
            return []
    else:
        words = [word.strip("\"'") for word in _dockerfile._words(rest)]
    flags = [word for word in words if word.startswith("--")]
    if any(flag.startswith("--from=") for flag in flags):
        return []  # another stage's files, or another image's: not the context's lock
    paths = [word for word in words if not word.startswith("--")]
    return paths[:-1]


def copied(text: str, context: str, dockerfile: str) -> list[str]:
    """Every npm lock *dockerfile* copies from its build context by name, each once, sorted.

    A source names the lock when its last step is ``package-lock.json`` or a pattern that
    matches it (``package*.json``). A bare ``*``, a directory and a source holding a
    variable name no file, so they name no lock.
    """
    found: set[str] = set()
    for keyword, rest in _dockerfile._instructions(text, dockerfile):
        if keyword not in ("copy", "add"):
            continue
        for source in _sources(rest):
            last = posixpath.basename(source)
            if "$" in source or last == "*" or not fnmatch.fnmatchcase(LOCK_FILE, last):
                continue
            folder = posixpath.dirname(source).lstrip("/")
            found.add(posixpath.normpath(posixpath.join(context, folder, LOCK_FILE)))
    return sorted(found)


def choose(tree: Files, context: str, dockerfile: str) -> tuple[str | None, str | None]:
    """``(lock, None)`` for the lock the image installs, or ``(None, why)`` when none can be named."""
    try:
        named = copied(tree.read_text(dockerfile), context, dockerfile) if tree.has(dockerfile) else []
    except (ReleaseError, UnicodeDecodeError) as exc:
        return None, f"{dockerfile} cannot be read for the lock it copies ({exc})"
    by_name = f"{dockerfile} copies a package-lock.json by name"
    if len(named) > 1:
        return None, (
            f"{dockerfile} copies {len(named)} npm locks, {' and '.join(named)}, and a release "
            f"reads a web image's packages from the one lock it installs (allowed: {dockerfile} "
            "copies exactly one package-lock.json)"
        )
    if named:
        if tree.has(named[0]):
            return named[0], None
        return None, (
            f"{dockerfile} copies {named[0]}, which the commit does not hold (allowed: the "
            "committed package-lock.json the Dockerfile copies)"
        )
    found = [path for path in candidates(context, dockerfile) if tree.has(path)]
    if len(found) > 1:
        return None, (
            f"the commit holds {' and '.join(found)}, and {dockerfile} names neither: a release "
            "reads a web image's packages from the lock it installs, and position does not say "
            f"which that is (allowed: {by_name})"
        )
    if found:
        return found[0], None
    return None, (
        f"the commit holds no {' and no '.join(candidates(context, dockerfile))}, and a release "
        f"reads a web image's packages from the lock it installs (allowed: {by_name}, or a "
        f"committed package-lock.json beside {dockerfile} or at the root of its build context)"
    )
