"""Which packages a target holds: from its locks, or from a signed release's SBOMs (ADR 0214).

The locks are read as data, through the same parser the release jobs use
(:mod:`terp.cli.release._locks`): no resolver runs and no index is asked. The npm locks are
the ones the release plan builds a web image from (:func:`terp.cli.release._plan.web_npm_locks`),
beside the generator's two. Only a package that came from a registry is listed: in
``uv.lock`` one with a ``registry`` source, in an npm lock one npm resolved to a registry
tarball (or left unresolved, for the registry it installs from). One the lock takes from a
path, a git repository or any other URL is the app's own or a private fork and stays here;
so does the project itself. Each package keeps the host it came from, so the caller can send
only a public registry's names unless the person sending says otherwise.

A manifest with no lock beside it is named: its packages cannot be read, and a report that
said nothing about them would read as though they were clean.

A signed release is read from its bundle (``terp release sign``): each image's SBOM, held to
the digest the manifest records for it, and the advisories the manifest recorded per package
when it was signed, so a later report can tell what is new since.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from terp.cli.release._common import ReleaseError
from terp.cli.release._locks import NPM_LOCKS, UV_LOCK, normalise, npm_manifest, read_npm_lock, read_uv_lock

#: The files of a signed release bundle this reads (``terp release sign``'s names).
MANIFEST = "release.manifest.json"

#: The public registries a package's name may be sent from without being asked: PyPI and npm's.
PUBLIC_REGISTRIES = frozenset({"pypi.org", "registry.npmjs.org", "registry.yarnpkg.com"})


@dataclass(frozen=True)
class Package:
    """One package at one version, and where the target holds it."""

    ecosystem: str
    name: str
    version: str
    location: str
    #: For an npm lock: whether the workspace's package.json names it (``False``: something it
    #: depends on brought it in). ``None`` where the question does not arise.
    direct: bool | None = None
    #: The host of the registry the lock took it from; ``None`` where no lock says (an npm entry
    #: left unresolved, or a signed release's SBOM).
    registry: str | None = None

    @property
    def purl(self) -> str:
        if self.ecosystem == "npm":
            return f"pkg:npm/{self.name.replace('@', '%40', 1)}@{self.version}"
        return f"pkg:pypi/{normalise(self.name)}@{self.version}"

    @property
    def public(self) -> bool:
        """Whether a public registry serves it, so its name is no secret of this app."""
        return self.registry in PUBLIC_REGISTRIES


def _host(url: object) -> str | None:
    return urllib.parse.urlsplit(url).hostname if isinstance(url, str) else None


def _uv_packages(lock: Mapping[str, Any]) -> list[Package]:
    found = set()
    for entry in lock["package"]:
        if not isinstance(entry, dict) or "name" not in entry or "version" not in entry:
            continue
        source = entry.get("source")
        if not isinstance(source, dict) or not isinstance(source.get("registry"), str):
            continue
        found.add(
            Package("PyPI", normalise(str(entry["name"])), str(entry["version"]), UV_LOCK, registry=_host(source["registry"]))
        )
    return sorted(found, key=lambda p: (p.name, p.version))


def _from_registry(entry: Mapping[str, Any]) -> bool:
    """Whether npm installs *entry* from a registry: a ``<registry>/<name>/-/<file>.tgz``
    tarball, or no ``resolved`` at all, which npm leaves out for the registry it installs from.
    A link, a path, a git repository or any other URL is not a registry's, and stays here."""
    if entry.get("link") is True:
        return False
    if "resolved" not in entry:
        return True
    parts = urllib.parse.urlsplit(str(entry["resolved"]))
    return parts.scheme in ("https", "http") and "/-/" in parts.path


def _npm_packages(lock: Mapping[str, Any], path: str) -> list[Package]:
    root = lock["packages"].get("")
    root = root if isinstance(root, dict) else {}
    named = {
        str(name)
        for group in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
        if isinstance(root.get(group), dict)
        for name in root[group]
    }
    found = set()
    for key, entry in lock["packages"].items():
        if not key or "node_modules/" not in key or not isinstance(entry, dict) or "version" not in entry:
            continue
        if not _from_registry(entry):
            continue
        name = str(entry.get("name") or key.rsplit("node_modules/", 1)[-1])
        direct = key == f"node_modules/{name}" and name in named
        found.add(Package("npm", name, str(entry["version"]), path, direct, _host(entry.get("resolved"))))
    return sorted(found, key=lambda p: (p.name, p.version))


def _npm_candidates(root: pathlib.Path) -> list[str]:
    """Every npm lock a release of *root* would install: the generator's two, and each lock the
    release plan builds a web image from."""
    from terp.arch.deployment import published_table
    from terp.cli.release._plan import web_npm_locks

    planned = [lock for lock in web_npm_locks(root, published_table()) if lock not in NPM_LOCKS]
    return [*NPM_LOCKS, *planned]


def npm_locks(root: pathlib.Path) -> list[str]:
    """The npm locks at *root* that ``npm ci`` reads: each beside its ``package.json``."""
    return [lock for lock in _npm_candidates(root) if (root / npm_manifest(lock)).is_file() and (root / lock).is_file()]


def _text(root: pathlib.Path, path: str) -> str:
    try:
        return (root / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReleaseError(f"{path} could not be read", cause=str(exc)) from exc


@dataclass(frozen=True)
class Inventory:
    """What the locks at a root hold, and what they leave unread."""

    packages: list[Package]
    #: A ``not_checked`` sentence for each manifest whose lock is missing.
    unlocked: list[str]
    #: Whether the root holds any manifest or lock at all.
    anything: bool


def inventory(root: pathlib.Path) -> Inventory:
    """Every registry package the locks at *root* hold, and each manifest whose lock is missing."""
    packages: list[Package] = []
    unlocked: list[str] = []
    anything = False
    if (root / UV_LOCK).is_file():
        anything = True
        packages += _uv_packages(read_uv_lock(_text(root, UV_LOCK)))
    elif (root / "pyproject.toml").is_file():
        anything = True
        unlocked.append(
            "known-vulnerability: pyproject.toml has no uv.lock beside it, so none of its packages "
            "was asked about (`uv lock` writes one)"
        )
    for lock in _npm_candidates(root):
        manifest = npm_manifest(lock)
        if (root / lock).is_file() and (root / manifest).is_file():
            anything = True
            packages += _npm_packages(read_npm_lock(_text(root, lock), lock), lock)
        elif (root / manifest).is_file():
            anything = True
            workspace = manifest.rsplit("/", 1)[0] if "/" in manifest else "."
            unlocked.append(
                f"known-vulnerability: {manifest} has no package-lock.json beside it, so none of its "
                f"packages was asked about (`npm --prefix {workspace} install` writes one)"
            )
    return Inventory(packages, unlocked, anything)


@dataclass(frozen=True)
class Bundle:
    """What a signed release says it holds."""

    tag: str | None
    packages: list[Package]
    #: The advisory ids the manifest recorded per package URL when the release was signed.
    recorded: dict[str, frozenset[str]]
    #: The vulnerability database ``sign`` asked, as the manifest records it.
    database: str | None


def _from_purl(purl: str, location: str) -> Package | None:
    if not purl.startswith(("pkg:pypi/", "pkg:npm/")) or "@" not in purl.rsplit("/", 1)[-1]:
        return None
    kind, _, rest = purl.removeprefix("pkg:").partition("/")
    name, _, version = rest.rpartition("@")
    return Package("PyPI" if kind == "pypi" else "npm", urllib.parse.unquote(name), version, location)


def _json(data: bytes, what: str) -> Any:
    try:
        return json.loads(data)
    except ValueError as exc:
        raise ReleaseError(f"{what} could not be read as JSON", cause=str(exc)) from exc


def _bytes(path: pathlib.Path, what: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ReleaseError(f"the bundle holds no readable {what}", cause=str(exc)) from exc


def _recorded(image: Mapping[str, Any], name: str) -> dict[str, set[str]]:
    found = image.get("vulnerabilities") or {}
    if not isinstance(found, dict) or not all(
        isinstance(purl, str) and isinstance(ids, list) and all(isinstance(i, str) for i in ids)
        for purl, ids in found.items()
    ):
        raise ReleaseError(f"the manifest's vulnerabilities for the image {name} are not a list of ids per package")
    return {purl: set(ids) for purl, ids in found.items()}


def bundle_packages(bundle: pathlib.Path) -> Bundle:
    """The packages of every image a signed release bundle holds, each SBOM held to its digest.

    Refused, by name, when the bundle is not one: no manifest, a manifest or an SBOM in another
    shape, an image without its SBOM, or an SBOM whose bytes are not the ones the manifest
    recorded. The signature is not checked here; ``terp promote`` checks it before anything
    runs, and a report that read a forged bundle would only report on the forgery.
    """
    manifest = _json(_bytes(bundle / MANIFEST, MANIFEST), MANIFEST)
    outputs = manifest.get("outputs") if isinstance(manifest, dict) else None
    images = outputs.get("images") if isinstance(outputs, dict) else None
    if not isinstance(images, dict) or not images:
        raise ReleaseError(f"{bundle / MANIFEST} records no images, so it is no release bundle")
    packages: set[Package] = set()
    recorded: dict[str, set[str]] = {}
    tags = set()
    for name, image in sorted(images.items()):
        if not isinstance(image, dict) or not isinstance(image.get("sbom"), str):
            raise ReleaseError(f"the manifest records no SBOM digest for the image {name}")
        sbom_name = f"sbom-{str(name).replace('/', '_')}.cdx.json"
        data = _bytes(bundle / sbom_name, f"{sbom_name} for the image {name}")
        if hashlib.sha256(data.rstrip(b"\n")).hexdigest() != image["sbom"]:
            raise ReleaseError(f"{sbom_name} is not the SBOM the manifest recorded for {name}")
        document = _json(data, sbom_name)
        components = document.get("components") if isinstance(document, dict) else None
        if not isinstance(components, list):
            raise ReleaseError(f"{sbom_name} lists no components")
        for component in components:
            purl = component.get("purl") if isinstance(component, dict) else None
            found = _from_purl(purl, f"image {name}") if isinstance(purl, str) else None
            if found is not None:
                packages.add(found)
        for purl, ids in _recorded(image, name).items():
            recorded.setdefault(purl, set()).update(ids)
        if isinstance(image.get("tag"), str) and image["tag"]:
            tags.add(image["tag"])
    database = outputs.get("vulnerabilityDatabase")
    return Bundle(
        tag=", ".join(sorted(tags)) or None,
        packages=sorted(packages, key=lambda p: (p.ecosystem, p.name, p.version, p.location)),
        recorded={purl: frozenset(ids) for purl, ids in recorded.items()},
        database=database if isinstance(database, str) and database else None,
    )


__all__ = ["MANIFEST", "PUBLIC_REGISTRIES", "Bundle", "Inventory", "Package", "bundle_packages", "inventory", "npm_locks"]
