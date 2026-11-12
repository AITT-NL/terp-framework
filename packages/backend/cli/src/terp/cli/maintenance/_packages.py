"""Which packages a target holds: from its locks, or from a signed release's SBOMs (ADR 0214).

The locks are read as data, through the same parser the release jobs use
(:mod:`terp.cli.release._locks`): no resolver runs and no index is asked. Only a package that
came from a registry is listed. One the lock takes from a path, a git repository or a URL is
the app's own or a private fork, and its name is not sent to a public database; nor is the
project itself.

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

    @property
    def purl(self) -> str:
        if self.ecosystem == "npm":
            return f"pkg:npm/{self.name.replace('@', '%40', 1)}@{self.version}"
        return f"pkg:pypi/{normalise(self.name)}@{self.version}"


def _uv_packages(lock: Mapping[str, Any]) -> list[Package]:
    found = set()
    for entry in lock["package"]:
        if not isinstance(entry, dict) or "name" not in entry or "version" not in entry:
            continue
        if not isinstance(entry.get("source", {}).get("registry"), str):
            continue
        found.add(Package("PyPI", normalise(str(entry["name"])), str(entry["version"]), UV_LOCK))
    return sorted(found, key=lambda p: (p.name, p.version))


def _npm_packages(lock: Mapping[str, Any], path: str) -> list[Package]:
    root = lock["packages"].get("") if isinstance(lock["packages"].get(""), dict) else {}
    named = {
        str(name)
        for group in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
        for name in (root.get(group) or {})
    }
    found = set()
    for key, entry in lock["packages"].items():
        if not key or "node_modules/" not in key or not isinstance(entry, dict) or "version" not in entry:
            continue
        if entry.get("link") is True or str(entry.get("resolved", "")).startswith("file:"):
            continue
        name = str(entry.get("name") or key.rsplit("node_modules/", 1)[-1])
        direct = key == f"node_modules/{name}" and name in named
        found.add(Package("npm", name, str(entry["version"]), path, direct))
    return sorted(found, key=lambda p: (p.name, p.version))


def npm_locks(root: pathlib.Path) -> list[str]:
    """The npm locks the target holds that ``npm ci`` reads: each beside its ``package.json``.

    The generator's two (``frontend/``, ``site/``) and every other lock the release plan builds
    a web image from, the same set ``dependency-audit-npm`` audits.
    """
    from terp.arch.deployment import published_table
    from terp.cli.release._plan import web_npm_locks

    planned = [lock for lock in web_npm_locks(root, published_table()) if lock not in NPM_LOCKS]
    return [
        lock
        for lock in (*NPM_LOCKS, *planned)
        if (root / npm_manifest(lock)).is_file() and (root / lock).is_file()
    ]


def tree_packages(root: pathlib.Path) -> list[Package]:
    """Every registry package the locks at *root* hold: ``uv.lock`` and each npm lock."""
    found: list[Package] = []
    if (root / UV_LOCK).is_file():
        found += _uv_packages(read_uv_lock((root / UV_LOCK).read_text(encoding="utf-8")))
    for lock in npm_locks(root):
        found += _npm_packages(read_npm_lock((root / lock).read_text(encoding="utf-8"), lock), lock)
    return found


@dataclass(frozen=True)
class Bundle:
    """What a signed release says it holds."""

    tag: str | None
    packages: list[Package]
    #: The advisory ids the manifest recorded per package URL when the release was signed.
    recorded: dict[str, frozenset[str]]


def _from_purl(purl: str, location: str) -> Package | None:
    if not purl.startswith(("pkg:pypi/", "pkg:npm/")) or "@" not in purl.rsplit("/", 1)[-1]:
        return None
    kind, _, rest = purl.removeprefix("pkg:").partition("/")
    name, _, version = rest.rpartition("@")
    return Package("PyPI" if kind == "pypi" else "npm", urllib.parse.unquote(name), version, location)


def _json(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ReleaseError(f"{path.name} could not be read as JSON", cause=str(exc)) from exc


def bundle_packages(bundle: pathlib.Path) -> Bundle:
    """The packages of every image a signed release bundle holds, each SBOM held to its digest.

    Refused when the bundle is not one: no manifest, an image without its SBOM, or an SBOM
    whose bytes are not the ones the manifest recorded. The signature is not checked here;
    ``terp promote`` checks it before anything runs, and a report that read a forged bundle
    would only report on the forgery.
    """
    manifest = _json(bundle / MANIFEST)
    images = manifest.get("outputs", {}).get("images") if isinstance(manifest, dict) else None
    if not isinstance(images, dict) or not images:
        raise ReleaseError(f"{bundle / MANIFEST} records no images, so it is no release bundle")
    packages: set[Package] = set()
    recorded: dict[str, set[str]] = {}
    tags = set()
    for name, image in sorted(images.items()):
        sbom_name = f"sbom-{name.replace('/', '_')}.cdx.json"
        try:
            data = (bundle / sbom_name).read_bytes()
        except OSError as exc:
            raise ReleaseError(f"the bundle holds no {sbom_name} for the image {name}") from exc
        if hashlib.sha256(data.rstrip(b"\n")).hexdigest() != image.get("sbom"):
            raise ReleaseError(f"{sbom_name} is not the SBOM the manifest recorded for {name}")
        for component in json.loads(data).get("components", []):
            found = _from_purl(str(component.get("purl", "")), f"image {name}")
            if found is not None:
                packages.add(found)
        for purl, ids in (image.get("vulnerabilities") or {}).items():
            recorded.setdefault(purl, set()).update(str(found) for found in ids)
        if image.get("tag"):
            tags.add(str(image["tag"]))
    return Bundle(
        tag=", ".join(sorted(tags)) or None,
        packages=sorted(packages, key=lambda p: (p.ecosystem, p.name, p.version, p.location)),
        recorded={purl: frozenset(ids) for purl, ids in recorded.items()},
    )


__all__ = ["MANIFEST", "Bundle", "Package", "bundle_packages", "npm_locks", "tree_packages"]
