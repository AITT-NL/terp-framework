"""An image's filesystem, read from its layers as data, and the facts ``sign`` compares.

The layers are tar archives applied in order, the way an engine unpacks them: a ``.wh.<name>``
entry removes ``<name>`` from the layers below, a ``.wh..wh..opq`` entry empties its directory
of what the layers below put there, and a hard link takes the bytes of the file it names. No
entry is ever written to disk: each kept path becomes a :class:`Node` with the SHA-256 of its
bytes, and only the few files ``sign`` reads (a distribution's ``METADATA`` and ``RECORD``) keep
their text. Nothing here runs anything; the archives are attacker-built data, read through
:mod:`tarfile` in memory and held to their digests by :mod:`terp.cli.release._registry`.
"""

from __future__ import annotations

import base64
import binascii
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

#: The files whose text a comparison reads: a distribution's name, version and file list.
_TEXT = re.compile(r".*/site-packages/[^/]+\.dist-info/(?:METADATA|RECORD)")


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


def apply_layer(state: dict[str, Node], texts: dict[str, str], archive: tarfile.TarFile) -> None:
    """Apply one layer to *state* (and *texts*), as an engine unpacks it over the ones below."""
    removed: list[tuple[bool, str]] = []
    added: dict[str, Node] = {}
    added_texts: dict[str, str] = {}
    for member in archive:
        path = _name(member)
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
        elif member.isfile():
            handle = archive.extractfile(member)
            data = handle.read() if handle is not None else b""
            added[path] = Node("file", hashlib.sha256(data).hexdigest(), len(data))
            if _TEXT.fullmatch(path):
                added_texts[path] = data.decode("utf-8", errors="replace")
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
    state.update(added)
    texts.update(added_texts)


def read_filesystem(
    registry: Registry, repository: str, manifest: dict[str, Any]
) -> tuple[dict[str, Node], dict[str, str]]:
    """Every path of the image *manifest* describes, after all its layers, and the texts."""
    state: dict[str, Node] = {}
    texts: dict[str, str] = {}
    for layer in manifest.get("layers", []):
        blob = registry.blob(repository, layer["digest"], LAYER_LIMIT)
        with _open(blob, str(layer.get("mediaType", ""))) as archive:
            apply_layer(state, texts, archive)
    return state, texts


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

    A ``RECORD`` is data the build wrote, so a hash it cannot decode is no hash, never a crash;
    nothing is accepted on a ``RECORD``'s word anyway, as each file is held to the tree.
    """
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        path, _, rest = line.partition(",")
        algorithm, _, digest = rest.partition(",")[0].partition("=")
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


__all__ = ["Node", "apply_layer", "final_base", "metadata", "read_filesystem", "record"]
