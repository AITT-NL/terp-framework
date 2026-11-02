"""The closed datastore table: the only images a deployment declaration may name.

A unit in ``deployment.json`` is either built from the checkout or a database or shared
store named by ``kind`` and ``version`` from this table, one digest per entry (ADR 0184
decision 3). There is no ``image`` key, so a declaration cannot name a registry, and a
``kind`` unit whose profile service runs anything but the table's image (a tag, a
foreign registry, another digest) is refused.

The table ships in this package as ``datastore-table.json``, in the format the Terp
Standard's corpus uses for the table a case resolves against: ``{"kinds": {kind:
{"role": "database" | "store", "versions": {version: "repository@sha256:..."}}}}``. So
a tool that reads a checkout as data, and a corpus case, read the same shape. Which
digests a particular environment accepts is that environment's allowlist, never this
table: the framework version that selects the table is itself pinned in an
agent-editable ``pyproject.toml``.
"""

from __future__ import annotations

import functools
import json
import pathlib
from dataclasses import dataclass
from typing import Any

#: The table, beside this module in the wheel.
TABLE_FILE = "datastore-table.json"

#: Where each digest in the published table came from, so the next release can move it
#: the same way. Not part of the table's format, which carries the images only.
SOURCES: dict[tuple[str, str], str] = {
    ("postgres", "17"): (
        "docker buildx imagetools inspect postgres:17-alpine, read 2026-10-20: the OCI "
        "image index for PostgreSQL 17.11 on Alpine 3.24, built 2026-09-17 from "
        "docker-library/postgres at 2603e26e245e558218728ee14e0a42dcb020dc7f, for "
        "linux/386, amd64, arm/v6, arm/v7, arm64/v8, ppc64le, riscv64 and s390x"
    ),
}

#: The registry an image reference names when it names none.
_DEFAULT_REGISTRY = "docker.io"

#: What a kind may be: a database an app's data lives in, or a broker or shared store.
ROLES = frozenset({"database", "store"})


class DatastoreTableError(ValueError):
    """The table is not in the shape every reader of it expects."""


@dataclass(frozen=True)
class ImageReference:
    """An image reference taken apart: ``postgres@sha256:...``."""

    repository: str
    tag: str | None
    digest: str | None


def parse_image(reference: str) -> ImageReference | None:
    """Take an image reference apart, normalising the registry Docker assumes.

    ``postgres``, ``library/postgres`` and ``docker.io/library/postgres`` are one
    repository, so they compare equal here; anything this cannot read is ``None``.
    """
    name, at, digest = reference.strip().partition("@")
    head, _, last = name.rpartition("/")
    last, _, tag = last.partition(":")
    if not last or (at and not digest):
        return None
    path = f"{head}/{last}" if head else last
    first, _, rest = path.partition("/")
    if rest and ("." in first or ":" in first or first == "localhost"):
        registry, path = first, rest
    else:
        registry = _DEFAULT_REGISTRY
    if registry == _DEFAULT_REGISTRY and "/" not in path:
        path = f"library/{path}"
    return ImageReference(f"{registry}/{path}", tag or None, digest or None)


@dataclass(frozen=True)
class Datastore:
    """One entry: a kind at a version, pinned to exactly one image."""

    kind: str
    version: str
    role: str
    image: str

    def pinned_by(self, image: object) -> bool:
        """Does *image* (a profile service's ``image:``) run exactly this entry?

        Exactly: the same repository, the same digest, and no tag beside it, because
        a tag can move and a tag beside a digest can say a version the digest is not.
        """
        if not isinstance(image, str):
            return False
        return parse_image(image) == parse_image(self.image)

    def runs_its_repository(self, image: object) -> bool:
        """Does *image* run this entry's repository at any tag or digest?"""
        parsed = parse_image(image) if isinstance(image, str) else None
        expected = parse_image(self.image)
        return (
            parsed is not None
            and expected is not None
            and (parsed.repository == expected.repository)
        )


@dataclass(frozen=True)
class DatastoreTable:
    """Every entry a stack accepts."""

    entries: tuple[Datastore, ...]

    def find(self, kind: str, version: str) -> Datastore | None:
        """The entry for *kind* at *version*, or ``None`` when the table has none."""
        return next(
            (entry for entry in self.entries if (entry.kind, entry.version) == (kind, version)),
            None,
        )

    def versions(self) -> dict[str, tuple[str, ...]]:
        """What the table offers, kind by kind, for a message naming what is allowed."""
        offered: dict[str, list[str]] = {}
        for entry in self.entries:
            offered.setdefault(entry.kind, []).append(entry.version)
        return {kind: tuple(sorted(found)) for kind, found in sorted(offered.items())}

    def describe(self) -> str:
        """``postgres 17; redis 7``: the table in a sentence."""
        return "; ".join(f"{kind} {', '.join(found)}" for kind, found in self.versions().items())


def read_table(raw: Any) -> DatastoreTable:
    """A table from its parsed JSON, refused outright when it is not the shape."""
    kinds = raw.get("kinds") if isinstance(raw, dict) else None
    if not isinstance(kinds, dict) or set(raw) != {"kinds"}:
        raise DatastoreTableError('a datastore table is {"kinds": {...}} and nothing else')
    entries: list[Datastore] = []
    for kind, entry in sorted(kinds.items()):
        if not isinstance(entry, dict) or set(entry) != {"role", "versions"}:
            raise DatastoreTableError(f"kind {kind!r} needs exactly a role and versions")
        if entry["role"] not in ROLES or not isinstance(entry["versions"], dict):
            raise DatastoreTableError(f"kind {kind!r} has an unknown role or no versions")
        for version, image in sorted(entry["versions"].items()):
            parsed = parse_image(image) if isinstance(image, str) else None
            if parsed is None or parsed.digest is None or parsed.tag is not None:
                raise DatastoreTableError(f"{kind} {version} is not pinned by digest alone")
            entries.append(Datastore(kind, version, entry["role"], image))
    return DatastoreTable(tuple(entries))


@functools.cache
def published_table() -> DatastoreTable:
    """The table this framework release publishes."""
    path = pathlib.Path(__file__).with_name(TABLE_FILE)
    return read_table(json.loads(path.read_text(encoding="utf-8")))


def load_table(path: str | pathlib.Path | None = None) -> DatastoreTable:
    """The table at *path*, or the published one when there is no file there."""
    if path is None or not pathlib.Path(path).is_file():
        return published_table()
    return read_table(json.loads(pathlib.Path(path).read_text(encoding="utf-8")))
