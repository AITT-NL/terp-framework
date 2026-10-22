"""One commit's tree, read from git's object store as data (ADR 0187 decision 6).

A release is cut from an exact SHA, and every job reads what that SHA holds, never a working
copy: a working copy is whatever the last command left there, and on a checkout that converts
line endings it is not even the committed bytes. So the tree is read through git's plumbing -
``rev-parse`` for the commit, ``ls-tree`` for the entries, ``cat-file --batch`` for each blob's
exact bytes - with no filter, no attribute and no hook between the object store and the job.
:meth:`Tree.materialize` writes those bytes out as the build's pristine context, and ``sign``
compares an image with them.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field

from terp.cli.release._common import ReleaseError, commit_id, require, run

#: The modes ``ls-tree`` prints for what a tree can hold.
_FILE_MODES = frozenset({"100644", "100755"})
_LINK_MODE = "120000"
_SUBMODULE_MODE = "160000"


@dataclass(frozen=True)
class Entry:
    """One path of the tree: its git mode and the object that holds its bytes."""

    mode: str
    oid: str

    @property
    def executable(self) -> bool:
        return self.mode == "100755"

    @property
    def link(self) -> bool:
        return self.mode == _LINK_MODE


@dataclass(frozen=True)
class Tree:
    """The tree of one commit: every path, and the exact bytes of every file."""

    commit: str
    tree: str
    #: The committer time, seconds since the epoch: the build's ``SOURCE_DATE_EPOCH``.
    time: int
    entries: dict[str, Entry]
    blobs: dict[str, bytes] = field(repr=False)
    #: Paths that are submodules: a commit of another repository, no bytes of this one.
    submodules: tuple[str, ...] = ()

    @classmethod
    def read(cls, repo: str | os.PathLike[str], sha: str) -> Tree:
        """The tree of commit *sha* in the repository at *repo*."""
        commit_id(sha)
        git = ["git", "-C", str(repo), "-c", "core.quotepath=off"]
        resolved = require(
            run([*git, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{sha}^{{commit}}"]),
            f"finding commit {sha} in {repo}",
        ).decode().strip()
        if resolved != sha:
            raise ReleaseError(f"{sha} resolves to {resolved}, not to itself")
        header = require(
            run([*git, "show", "-s", "--format=%T %ct", sha]), f"reading commit {sha}"
        ).decode().split()
        listing = require(
            run([*git, "ls-tree", "-r", "-z", "--full-tree", sha]), f"listing the tree of {sha}"
        )
        entries: dict[str, Entry] = {}
        submodules: list[str] = []
        for record in listing.decode("utf-8").split("\0"):
            if not record:
                continue
            meta, path = record.split("\t", 1)
            mode, kind, oid = meta.split(" ")
            if mode == _SUBMODULE_MODE:
                submodules.append(path)
            elif kind == "blob" and (mode in _FILE_MODES or mode == _LINK_MODE):
                entries[path] = Entry(mode, oid)
        blobs = _blobs(git, sorted({entry.oid for entry in entries.values()}))
        return cls(sha, header[0], int(header[1]), entries, blobs, tuple(sorted(submodules)))

    def has(self, path: str) -> bool:
        return path in self.entries

    def bytes(self, path: str) -> bytes:
        """The committed bytes at *path*."""
        return self.blobs[self.entries[path].oid]

    def read_text(self, path: str) -> str:
        return self.bytes(path).decode("utf-8")

    def paths(self, prefix: str = "") -> list[str]:
        """Every file path under *prefix* (a directory with its ``/``), sorted."""
        return sorted(path for path in self.entries if path.startswith(prefix))

    def materialize(self, destination: pathlib.Path) -> None:
        """Write the tree under *destination*, byte for byte, with git's executable bit.

        A link is written as a link. On a host that cannot make one it is refused, never
        written as a file holding its target, which a build would read as something else.
        """
        for path, entry in sorted(self.entries.items()):
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            data = self.blobs[entry.oid]
            if entry.link:
                try:
                    os.symlink(data.decode("utf-8"), target)
                except OSError as exc:
                    raise ReleaseError(
                        f"{path} is a symbolic link this host cannot create", cause=str(exc)
                    ) from exc
                continue
            target.write_bytes(data)
            if entry.executable:
                target.chmod(0o755)


def _blobs(git: list[str], oids: list[str]) -> dict[str, bytes]:
    """Every object in *oids*, read in one ``cat-file --batch`` exactly as stored."""
    if not oids:
        return {}
    out = require(
        run([*git, "cat-file", "--batch"], stdin=("\n".join(oids) + "\n").encode()),
        "reading the tree's files",
    )
    found: dict[str, bytes] = {}
    position = 0
    for oid in oids:
        end = out.index(b"\n", position)
        name, kind, size = out[position:end].decode().split(" ")
        if name != oid or kind != "blob":
            raise ReleaseError(f"git answered {name} {kind} where blob {oid} was asked for")
        start = end + 1
        found[oid] = out[start : start + int(size)]
        position = start + int(size) + 1
    return found


def head(repo: str | os.PathLike[str]) -> tuple[str, bool]:
    """The commit a checkout has out, and whether its working tree matches it exactly."""
    git = ["git", "-C", str(repo), "-c", "core.fsmonitor=false"]
    commit = require(run([*git, "rev-parse", "--verify", "HEAD"]), "reading HEAD").decode().strip()
    status = require(
        run([*git, "status", "--porcelain", "--untracked-files=all"]), "reading the status"
    )
    return commit, not status.strip()


__all__ = ["Entry", "Tree", "head"]
