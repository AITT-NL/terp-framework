"""An image's filesystem, read from its layers as data, and the facts ``sign`` compares.

The layers are tar archives applied in order, the way an engine unpacks them: a ``.wh.<name>``
entry removes ``<name>`` from the layers below, a ``.wh..wh..opq`` entry empties its directory
of what the layers below put there, and a hard link takes the bytes of the file it names. An
entry whose way passes through a symbolic link is refused: an engine follows the link and writes
the entry where it points, and this reading files each entry under its own name. No
entry is ever written to disk: each kept path becomes a :class:`Node` with the SHA-256 of its
bytes, and only the few files ``sign`` reads (a distribution's ``METADATA`` and ``RECORD``, and
the environment's ``pyvenv.cfg``) keep their text. The reading of the migration histories
(:mod:`._migrations`) is handed the bytes of the files it reads apart from those texts, from
anywhere in the image (:func:`migration_inputs`). Nothing here runs anything; the archives are attacker-built data, read through
:mod:`tarfile` in memory and held to their digests by :mod:`terp.cli.release._registry`.
"""

from __future__ import annotations

import base64
import binascii
import csv
import gzip
import hashlib
import io
import posixpath
import re
import tarfile
from dataclasses import dataclass
from typing import Any

from terp.cli.release._common import ReleaseError
from terp.cli.release._registry import LAYER_LIMIT, Registry

_GZIP = frozenset(
    {
        "application/vnd.oci.image.layer.v1.tar+gzip",
        "application/vnd.docker.image.rootfs.diff.tar.gzip",
    }
)
_TAR = frozenset({"application/vnd.oci.image.layer.v1.tar"})
_WHITEOUT = ".wh."
_OPAQUE = ".wh..wh..opq"

#: The files whose text a comparison reads: a distribution's name, version and file list, and
#: the environment's own configuration.
_TEXT = re.compile(r".*/site-packages/[^/]+\.dist-info/(?:METADATA|RECORD)|srv/\.venv/pyvenv\.cfg")

#: The files whose bytes the reading of the migration histories reads, wherever they lie: every
#: ``entry_points.txt``, where an installed distribution declares the histories it owns, and every
#: file directly in a ``migrations/versions/`` directory below a ``site-packages`` or
#: ``dist-packages`` directory, where an installed package keeps its revisions.
_KEPT = re.compile(r"(?:.+/)?entry_points\.txt|(?:.+/)?(?:site|dist)-packages/(?:.+/)?migrations/versions/[^/]+")


@dataclass(frozen=True)
class Node:
    """One path of the image: what it is, and the SHA-256 of a file's bytes."""

    kind: str  # "file" | "link" | "dir" | "other"
    sha256: str = ""
    size: int = 0
    target: str = ""

    def as_data(self) -> list[Any]:
        return [self.kind, self.sha256, self.size, self.target]

    @classmethod
    def from_data(cls, data: list[Any]) -> Node:
        return cls(str(data[0]), str(data[1]), int(data[2]), str(data[3]))


def _name(member: tarfile.TarInfo) -> str:
    return posixpath.normpath("/" + member.name).lstrip("/")


def _open(blob: bytes, kind: str) -> tarfile.TarFile:
    if kind in _GZIP:
        return tarfile.open(fileobj=io.BytesIO(gzip.decompress(blob)), mode="r:")
    if kind in _TAR:
        return tarfile.open(fileobj=io.BytesIO(blob), mode="r:")
    raise ReleaseError(f"a layer of type {kind!r} cannot be read by this signer (allowed: tar, tar+gzip)")


def _link_on_the_way(path: str, added: dict[str, Node], state: dict[str, Node]) -> str | None:
    """The first directory on the way to *path* that is a symbolic link, in this layer or below."""
    parts = path.split("/")
    for end in range(1, len(parts)):
        prefix = "/".join(parts[:end])
        node = added.get(prefix, state.get(prefix))
        if node is not None and node.kind == "link":
            return prefix
    return None


def _linked_bytes(archive: tarfile.TarFile, member: tarfile.TarInfo, source: str, kept: dict[str, bytes]) -> bytes:
    """The bytes of the file hard link *member* names, read again from this layer or kept below.

    A hard link names a file archived before it, whose bytes were hashed and let go unless its
    own path is one whose bytes are kept, so they are read again from the archive. A file of a
    layer below is not in this archive: its bytes are the ones kept for it, and a link to one
    whose bytes were not kept is refused, rather than kept as no bytes, which would leave the
    file out of what the reading sees.
    """
    try:
        handle = archive.extractfile(member)
    except KeyError as exc:  # the file it names lies in a layer below
        if source in kept:
            return kept[source]
        raise ReleaseError(
            f"the layer links {_name(member)} to {source}, a file of a layer below whose bytes sign "
            "did not keep, so the file cannot be read: build the image so that the file is copied, "
            "not hard-linked across layers"
        ) from exc
    return handle.read() if handle is not None else b""


def apply_layer(
    state: dict[str, Node], texts: dict[str, str], archive: tarfile.TarFile, kept: dict[str, bytes] | None = None
) -> None:
    """Apply one layer to *state* (and *texts*), as an engine unpacks it over the ones below.

    With *kept*, the bytes of each file :data:`_KEPT` names are kept there too, and a path the
    layer replaces or removes loses the bytes a layer below kept for it.
    """
    removed: list[tuple[bool, str]] = []
    added: dict[str, Node] = {}
    added_texts: dict[str, str] = {}
    added_kept: dict[str, bytes] = {}
    for member in archive:
        path = _name(member)
        link = _link_on_the_way(path, added, state)
        if link is not None:
            raise ReleaseError(
                f"the layer writes {path} through {link}, a symbolic link: an engine follows the link "
                "and puts the entry where it points, and sign files every entry under its own name, "
                "so the image would hold a file sign never read: build the image so that no layer "
                "writes through a link (copy to the directory the link names, not to the link)"
            )
        directory, base = posixpath.split(path)
        if base == _OPAQUE:
            removed.append((True, directory))
        elif base.startswith(_WHITEOUT):
            removed.append((False, posixpath.join(directory, base[len(_WHITEOUT) :])))
        elif member.isdir():
            added[path] = Node("dir")
        elif member.issym():
            added[path] = Node("link", target=member.linkname)
        elif member.islnk():
            source = posixpath.normpath("/" + member.linkname).lstrip("/")
            node = added.get(source) or state.get(source)
            if node is None:
                raise ReleaseError(f"the layer links {path} to {source}, which no layer holds")
            added[path] = node
            if source in added_texts or source in texts:
                added_texts[path] = added_texts.get(source, texts.get(source, ""))
            if kept is not None and node.kind == "file" and _KEPT.fullmatch(path):
                added_kept[path] = _linked_bytes(archive, member, source, kept)
        elif member.isfile():
            handle = archive.extractfile(member)
            data = handle.read() if handle is not None else b""
            added[path] = Node("file", hashlib.sha256(data).hexdigest(), len(data))
            if _TEXT.fullmatch(path):
                added_texts[path] = data.decode("utf-8", errors="replace")
            if kept is not None and _KEPT.fullmatch(path):
                added_kept[path] = data
        else:
            added[path] = Node("other")
    for opaque, gone in removed:
        if opaque:
            # The directory stays; what the layers below put in it goes.
            doomed = [path for path in state if not gone or path.startswith(gone + "/")]
        else:
            doomed = [path for path in state if path == gone or path.startswith(gone + "/")]
        for path in doomed:
            state.pop(path)
            texts.pop(path, None)
            if kept is not None:
                kept.pop(path, None)
    state.update(added)
    texts.update(added_texts)
    if kept is not None:
        for path in added:
            kept.pop(path, None)
        kept.update(added_kept)


def read_filesystem(
    registry: Registry, repository: str, manifest: dict[str, Any], *, kept: dict[str, bytes] | None = None
) -> tuple[dict[str, Node], dict[str, str]]:
    """Every path of the image *manifest* describes, after all its layers, and the texts.

    With *kept*, the bytes of each file :data:`_KEPT` names are kept there as well.
    """
    state: dict[str, Node] = {}
    texts: dict[str, str] = {}
    for layer in manifest.get("layers", []):
        blob = registry.blob(repository, layer["digest"], LAYER_LIMIT)
        with _open(blob, str(layer.get("mediaType", ""))) as archive:
            apply_layer(state, texts, archive, kept)
    return state, texts


def migration_inputs(state: dict[str, Node], kept: dict[str, bytes]) -> dict[str, Any]:
    """What the reading of the migration histories reads of the whole image, as data.

    ``nodes``: every path that is no regular file, each directory, each link and anything else,
    and each directory only the paths below it make, which an archive need not hold as an entry
    of its own and an engine makes all the same. ``files``: the bytes of every file :data:`_KEPT`
    names, in base64. What a path holds and where it sits is the reading's to judge.
    """
    nodes = {path: node.as_data() for path, node in state.items() if node.kind != "file"}
    for path in state:
        parent = posixpath.dirname(path)
        while parent and parent not in nodes and parent not in state:
            nodes[parent] = Node("dir").as_data()
            parent = posixpath.dirname(parent)
    return {
        "nodes": dict(sorted(nodes.items())),
        "files": {path: base64.b64encode(data).decode("ascii") for path, data in sorted(kept.items())},
    }


def metadata(text: str) -> tuple[str, str]:
    """``(Name, Version)`` from a distribution's ``METADATA``."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            break
        key, _, value = line.partition(":")
        fields.setdefault(key.strip().lower(), value.strip())
    return fields.get("name", ""), fields.get("version", "")


def record(text: str) -> list[tuple[str, str]]:
    """``(path, sha256 hex)`` of every row of a ``RECORD``; a row without a readable hash gives ``""``.

    A ``RECORD`` is a CSV file the build wrote, so a hash it cannot decode is no hash, never a
    crash. A row without a hash holds its file to nothing, and the comparison accepts one only
    for the ``RECORD`` itself and for bytecode.
    """
    rows: list[tuple[str, str]] = []
    for row in csv.reader(text.splitlines()):
        if not row or not row[0].strip():
            continue
        path = row[0]
        algorithm, _, digest = (row[1] if len(row) > 1 else "").partition("=")
        try:
            raw = base64.urlsafe_b64decode(digest + "=" * (-len(digest) % 4)) if algorithm == "sha256" else b""
        except binascii.Error:
            raw = b""
        rows.append((path, raw.hex()))
    return rows


_FROM = re.compile(r"FROM\s+(?:--platform=\S+\s+)?(?P<image>\S+)(?:\s+AS\s+(?P<stage>\S+))?\s*$", re.IGNORECASE)


def final_base(dockerfile: str) -> str | None:
    """The image the Dockerfile's last stage is built from, through its stage names, if pinned.

    ``None`` when it cannot be named from the text: a variable in a ``FROM``, or a base given by
    a tag alone, whose bytes can move.
    """
    logical: list[str] = []
    current = ""
    for raw in dockerfile.splitlines():
        line = raw.strip()
        if not current and (not line or line.startswith("#")):
            continue
        if line.endswith("\\"):
            current += line[:-1] + " "
            continue
        logical.append(current + line)
        current = ""
    stages: dict[str, str] = {}
    last: str | None = None
    for line in logical:
        found = _FROM.match(line)
        if found is None:
            continue
        image = found.group("image")
        image = stages.get(image.lower(), image)
        if found.group("stage"):
            stages[found.group("stage").lower()] = image
        last = image
    if last is None or "$" in last or "@sha256:" not in last:
        return None
    return last


__all__ = ["Node", "apply_layer", "final_base", "metadata", "migration_inputs", "read_filesystem", "record"]
