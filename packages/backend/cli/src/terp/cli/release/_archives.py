"""What importlib.metadata reads of a zip archive on the interpreter's path, read as data.

importlib.metadata reads the distributions in a zip archive on the interpreter's path, whatever the
archive is called, so the sandbox keeps the ``entry_points.txt`` members of every zip archive in an
image (:mod:`._image`), and the listing of the migration histories refuses one that declares a
history (:mod:`._migrations`). Nothing here runs anything; an archive is attacker-built data.
"""

from __future__ import annotations

import io
import posixpath
import zipfile

from terp.cli.release._common import ReleaseError

ENTRY_POINTS = "entry_points.txt"

#: The members of one archive sign reads at most, where a wheel holds hundreds; one with more is
#: refused by name.
MOST_MEMBERS = 100_000


def _member(path: str, archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    """At most *limit* bytes of the member *info* of the archive at *path*.

    A member sign cannot read is refused: the image's own Python may read it where sign's does
    not, as Python 3.14 reads a member compressed with Zstandard and 3.13 does not, and
    importlib.metadata would then find the histories it declares.
    """
    try:
        with archive.open(info) as handle:
            return handle.read(limit)
    except Exception as exc:
        raise ReleaseError(
            f"{path}: {info.filename} is an entry_points.txt sign cannot read, in an archive whose "
            "central directory it reads: the image's own Python may read it, as a newer one reads a "
            "member compressed with Zstandard, and importlib.metadata would then find the histories "
            "it declares; write the member with deflate or none, or keep the archive out of the image",
            cause=str(exc),
        ) from exc


def zipped(path: str, data: bytes, limit: int) -> dict[str, bytes] | None:
    """At most *limit* bytes of each ``entry_points.txt`` the zip archive *data* at *path* holds,
    or ``None`` for a file that is no zip archive. An archive whose central directory cannot be
    read holds nothing, as for importlib.metadata, since a file can end like a zip archive and be
    none."""
    if not zipfile.is_zipfile(io.BytesIO(data)):
        return None
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
    except Exception:  # importlib.metadata suppresses whatever opening an archive raises
        return {}
    if len(infos) > MOST_MEMBERS:
        raise ReleaseError(
            f"{path} is a zip archive of {len(infos)} members, more than the {MOST_MEMBERS} sign reads "
            "of one archive, where a wheel holds hundreds: keep it out of the image"
        )
    return {info.filename: _member(path, archive, info, limit) for info in infos if posixpath.basename(info.filename) == ENTRY_POINTS}


__all__ = ["ENTRY_POINTS", "MOST_MEMBERS", "zipped"]
