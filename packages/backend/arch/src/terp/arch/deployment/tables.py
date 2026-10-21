"""The tables a framework release renders a generated app's build files from (ADR 0187).

The generator (:mod:`terp.arch.deployment.generator`) is a pure function of the declaration,
the project name and these tables, so a framework release decides what every generated app
builds from by shipping them, and moving one is a release like any other:

* **the datastore table** (``datastore-table.json``, ADR 0184): one digest per kind and
  version, the only images a ``kind`` unit runs;
* **the base-image table** (``base-images.json``): the digest of each base the generated
  Dockerfiles build from. A tag can move between two builds of one commit; a digest cannot.
  The template pins the same digests, because its Dockerfiles are the generator's render;
* **the system-package table** (``system-packages.json``): the operating-system packages a
  declaration may ask for in ``generator.systemPackages``. Empty in this release, so every
  name is refused, and the first entry waits for a measured need and a pinned source two
  cold builds read alike;
* **a kind recipe** per datastore kind: what a ``kind`` unit's service carries beyond its
  image - where its data lives, how it says it is healthy, its own environment, and the
  variable the backend units reach it through. Framework-internal, so it is Python here
  rather than a published format.
"""

from __future__ import annotations

import functools
import json
import pathlib
from dataclasses import dataclass
from typing import Any

from terp.arch.deployment.datastores import DatastoreTable, parse_image, published_table

BASE_IMAGES_FILE = "base-images.json"
SYSTEM_PACKAGES_FILE = "system-packages.json"

#: The bases the generated Dockerfiles name, each once: the backend's interpreter, the uv
#: binary its build stages mount, the frontend's build toolchain and its web server.
BASE_IMAGE_NAMES = ("nginx", "node", "python", "uv")

#: Where each base digest came from, so the next release can move it the same way. Not part
#: of the table's format, which carries the image and the tag it was read from.
BASE_IMAGE_SOURCES: dict[str, str] = {
    "nginx": (
        "docker buildx imagetools inspect nginxinc/nginx-unprivileged:alpine, read "
        "2026-10-21: the OCI image index for nginx 1.31.7 on Alpine, built 2026-10-19, for "
        "linux/386, amd64, arm/v6, arm/v7, arm64, ppc64le, riscv64 and s390x"
    ),
    "node": (
        "docker buildx imagetools inspect node:26-slim, read 2026-10-21: the OCI image index "
        "for Node.js 26.12.0 on Debian slim, built 2026-10-21, for linux/amd64, arm64/v8, "
        "ppc64le and s390x"
    ),
    "python": (
        "docker buildx imagetools inspect python:3.14-slim, read 2026-10-21: the OCI image "
        "index for Python 3.14.8 on Debian slim, built 2026-10-21, for linux/386, amd64, "
        "arm/v5, arm/v7, arm64/v8, ppc64le, riscv64 and s390x"
    ),
    "uv": (
        "docker buildx imagetools inspect ghcr.io/astral-sh/uv:0.13.4, read 2026-10-21: the "
        "OCI image index for uv 0.13.4 (the digest :latest named that day), built 2026-10-20, "
        "for linux/amd64 and arm64"
    ),
}


class TableError(ValueError):
    """A table is not in the shape the generator reads."""


@dataclass(frozen=True)
class BaseImage:
    """One base: the image by digest, and the tag the digest was read from."""

    name: str
    image: str
    tag: str


@dataclass(frozen=True)
class BaseImageTable:
    """Every base the generated Dockerfiles build from."""

    images: tuple[BaseImage, ...]

    def get(self, name: str) -> BaseImage:
        """The base called *name*; the table always carries all of them."""
        return next(image for image in self.images if image.name == name)


def read_base_images(raw: Any) -> BaseImageTable:
    """The base-image table from its parsed JSON, refused outright in any other shape."""
    images = raw.get("images") if isinstance(raw, dict) else None
    if not isinstance(images, dict) or set(raw) != {"images"}:
        raise TableError('a base-image table is {"images": {...}} and nothing else')
    if sorted(images) != sorted(BASE_IMAGE_NAMES):
        raise TableError(f"a base-image table names exactly {', '.join(BASE_IMAGE_NAMES)}")
    read: list[BaseImage] = []
    for name in BASE_IMAGE_NAMES:
        entry = images[name]
        if not isinstance(entry, dict) or set(entry) != {"image", "tag"}:
            raise TableError(f"base {name!r} needs exactly an image and the tag it came from")
        parsed = parse_image(entry["image"]) if isinstance(entry["image"], str) else None
        if parsed is None or parsed.digest is None or parsed.tag is not None:
            raise TableError(f"base {name!r} is not pinned by digest alone")
        if not isinstance(entry["tag"], str) or ":" not in entry["tag"]:
            raise TableError(f"base {name!r} names no tag it was read from")
        read.append(BaseImage(name, entry["image"], entry["tag"]))
    return BaseImageTable(tuple(read))


@dataclass(frozen=True)
class SystemPackageTable:
    """The packages a declaration may name; an entry's own shape waits for its first use."""

    packages: tuple[str, ...]


def read_system_packages(raw: Any) -> SystemPackageTable:
    """The system-package table from its parsed JSON: ``{"packages": {name: {...}}}``."""
    packages = raw.get("packages") if isinstance(raw, dict) else None
    if not isinstance(packages, dict) or set(raw) != {"packages"}:
        raise TableError('a system-package table is {"packages": {...}} and nothing else')
    if not all(isinstance(entry, dict) for entry in packages.values()):
        raise TableError("a system package's entry is an object: its pinned source")
    return SystemPackageTable(tuple(sorted(packages)))


@dataclass(frozen=True)
class KindRecipe:
    """What a ``kind`` unit's service carries beyond its image.

    *environment* and *url* are fixed text the generator writes as they stand: the
    datastore's own variables, and the default of *variable*, the one the backend units
    reach it through, with ``{host}`` for the unit's id. *title* names the datastore in a
    comment.
    """

    kind: str
    title: str
    data_path: str
    healthcheck: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]
    variable: str
    url: str


POSTGRES = KindRecipe(
    kind="postgres",
    title="PostgreSQL",
    data_path="/var/lib/postgresql/data",
    healthcheck=("CMD-SHELL", "pg_isready -U app -d app"),
    environment=(
        ("POSTGRES_USER", "app"),
        ("POSTGRES_PASSWORD", "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"),
        ("POSTGRES_DB", "app"),
    ),
    variable="DATABASE_URL",
    url="postgresql+psycopg://app:${POSTGRES_PASSWORD}@{host}:5432/app",
)

#: One recipe per kind the published datastore table carries.
RECIPES = (POSTGRES,)


@dataclass(frozen=True)
class Tables:
    """Everything a framework release renders from, beside the declaration and the name."""

    datastores: DatastoreTable
    base_images: BaseImageTable
    system_packages: SystemPackageTable
    recipes: tuple[KindRecipe, ...]

    def recipe(self, kind: str) -> KindRecipe | None:
        """The recipe for *kind*, or ``None`` when this release has none."""
        return next((recipe for recipe in self.recipes if recipe.kind == kind), None)


def _load(name: str) -> Any:
    return json.loads(pathlib.Path(__file__).with_name(name).read_text(encoding="utf-8"))


@functools.cache
def published_tables() -> Tables:
    """The tables this framework release publishes."""
    return Tables(
        datastores=published_table(),
        base_images=read_base_images(_load(BASE_IMAGES_FILE)),
        system_packages=read_system_packages(_load(SYSTEM_PACKAGES_FILE)),
        recipes=RECIPES,
    )
