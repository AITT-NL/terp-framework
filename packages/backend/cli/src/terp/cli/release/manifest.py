"""The release manifest: one JSON object, ``"schemaVersion": 1``, and who vouches for what.

ADR 0187 decision 6. Serialised canonically (sorted keys, no whitespace, UTF-8, no floats) and
signed as a DSSE envelope (:mod:`terp.cli.release.dsse`). Three sections:

* ``inputs``, recomputed by ``sign`` from the commit's tree, so two cold builds of one commit
  with one tag give the same bytes: the commit, the tag, the toolchain, the Terp Standard
  release the declaration was written against and its schema's SHA-256, the build state, the
  generator's files, the project root's place in the checkout, the development profile a deploy
  tool keeps apart, the declaration and every profile file with its content, the base images, the datastore table
  entries the kind units resolve to, the locks, the build arguments, the platform and what the
  build fetches from, derived statically;
* ``outputs``, checked by ``sign``: each image by repository and digest, with its installed
  package list, its SBOM and their scans, the secret scan, and the image of every service and
  unit the release runs;
* ``collected``, other jobs' word, recorded as such: the gate's assurance and schedules, the
  build's own account of itself, and the operator's statement of whether the jobs ran on
  separate hosts. Nothing here decides whether a rollback is restore-free: the target's own
  ``terp migrate check`` does (ADR 0185 decision 6).

:func:`parse` is what ``terp promote`` reads a verified payload with.
"""

from __future__ import annotations

import json
import tomllib
from typing import Any

from terp.arch.deployment import DEPLOYMENT_FILE
from terp.cli.api_contract import CONTRACT_ARTIFACT
from terp.arch.deployment.datastores import parse_image
from terp.arch.deployment.reader import DEV_COMPOSE_FILE

#: The development loop's declaration (ADR 0186), which names the development compose file.
WORKBENCH_FILE = "workbench.json"
from terp.cli.release._common import RELEASE_TAG, ReleaseError, canonical, sha256
from terp.cli.release._git import Tree
from terp.cli.release._locks import UV_LOCK, normalise, npm_hosts, python_sources, read_npm_lock, read_uv_lock
from terp.cli.release._plan import Plan

SCHEMA_VERSION = 1
HOSTS = ("separated", "shared")
DEFAULT_INDEX = "https://pypi.org/simple"


def _file(tree: Tree, path: str) -> dict[str, str]:
    data = tree.bytes(path)
    return {"path": path, "sha256": sha256(data), "content": data.decode("utf-8")}


def carried_contract(tree: Tree) -> dict[str, dict[str, str]]:
    """``{"contract": <carried file>}`` when the commit holds an API contract, else nothing.

    ADR 0194: the committed ``openapi.json`` rides in the signed manifest, so a release names
    the contract its commit holds under the same signature as its images, and a client in
    another repository pins a release to read it. The ``api-contract`` check holds the file to
    the app, and it is a check of the release profile, so ``sign`` signs a commit pinning
    0.36.1 or later only from a gate where it passed (ADR 0200); an earlier pin's gate is held
    to its claim alone, which no lane of reads that check. An app
    that has not adopted the contract carries none, and its manifest is unchanged. A contract
    committed as a symbolic link is refused: the commit holds only the link's text, which is
    not a contract, and the check reads the file it points to instead.
    """
    if not tree.has(CONTRACT_ARTIFACT):
        return {}
    if tree.entries[CONTRACT_ARTIFACT].link:
        raise ReleaseError(
            f"{CONTRACT_ARTIFACT} is committed as a symbolic link, so the release would carry "
            "the link's own text in place of the API contract (ADR 0194): commit the contract "
            f"itself - remove the link, then uv run terp openapi, then commit {CONTRACT_ARTIFACT}"
        )
    return {"contract": _file(tree, CONTRACT_ARTIFACT)}


def _base_images(tree: Tree, plan: Plan) -> list[dict[str, str]]:
    found: set[tuple[str, str]] = set()
    for image in plan.images:
        stages: set[str] = set()
        for line in tree.read_text(image.dockerfile).splitlines():
            words = line.split()
            if len(words) >= 2 and words[0].upper() == "FROM":
                ref = next(word for word in words[1:] if not word.startswith("--"))
                if ref.lower() not in stages:
                    found.add((image.dockerfile, ref))
                if len(words) >= 4 and words[-2].upper() == "AS":
                    stages.add(words[-1].lower())
    return [{"dockerfile": dockerfile, "image": ref} for dockerfile, ref in sorted(found)]


def _build_backend_indexes(tree: Tree) -> list[str]:
    project = tomllib.loads(tree.read_text("pyproject.toml"))
    indexes = project.get("tool", {}).get("uv", {}).get("index", [])
    urls = [str(entry["url"]) for entry in indexes if isinstance(entry, dict) and "url" in entry]
    if not any(isinstance(entry, dict) and entry.get("default") for entry in indexes):
        urls.append(DEFAULT_INDEX)
    return sorted(set(urls))


#: Where the project lies in the checkout: the release jobs read a project at the root of its
#: repository, where ``deployment.json`` is, so the place is always the root.
PROJECT_ROOT = "."


def development_profile(tree: Tree) -> str:
    """The development compose file ``workbench.json`` names, else the template's.

    A deploy tool holds every path the release names apart from it (ADR 0184 decision 6), so
    the manifest says which file that is rather than leaving the tool to assume one.
    """
    try:
        workbench = json.loads(tree.read_text(WORKBENCH_FILE)) if tree.has(WORKBENCH_FILE) else None
    except ValueError:
        workbench = None
    compose = workbench.get("compose") if isinstance(workbench, dict) else None
    named = compose.get("file") if isinstance(compose, dict) else None
    return named if isinstance(named, str) and named else DEV_COMPOSE_FILE


def _datastores(plan: Plan, table: dict[str, Any]) -> dict[str, Any]:
    kinds: dict[str, Any] = {}
    for unit in plan.declaration.units:
        if unit.kind is None:
            continue
        entry = table["kinds"][unit.kind]
        kinds.setdefault(unit.kind, {"role": entry["role"], "versions": {}})
        kinds[unit.kind]["versions"][str(unit.version)] = entry["versions"][str(unit.version)]
    return {"kinds": kinds}


def inputs(
    tree: Tree,
    plan: Plan,
    *,
    tag: str,
    toolchain: dict[str, str],
    spec: dict[str, str],
    generator: dict[str, Any] | None,
    datastore_table: dict[str, Any],
    platform: str,
) -> dict[str, Any]:
    """The ``inputs`` section, from the tree, the plan and what ``sign`` established."""
    lock = read_uv_lock(tree.read_text(UV_LOCK))
    locks = [{"path": UV_LOCK, "sha256": sha256(tree.bytes(UV_LOCK))}]
    hosts: set[str] = set()
    # Exactly the npm locks the planned images are built from, never every lock the tree holds:
    # a lock no image installs says nothing about the release (ADR 0198).
    for npm_lock in plan.npm_locks:
        locks.append({"path": npm_lock, "sha256": sha256(tree.bytes(npm_lock))})
        hosts.update(npm_hosts(read_npm_lock(tree.read_text(npm_lock), npm_lock)))
    npm = sorted(hosts)
    bases = _base_images(tree, plan)
    registries = sorted(
        {(parse_image(base["image"]).repository.split("/", 1)[0]) for base in bases if parse_image(base["image"])}
    )
    section: dict[str, Any] = {
        "commit": {"sha": tree.commit, "tree": tree.tree},
        "releaseTag": tag,
        "toolchain": toolchain,
        "spec": spec,
        "build": plan.declaration.build,
        "projectRoot": PROJECT_ROOT,
        "developmentProfile": development_profile(tree),
        "declaration": _file(tree, DEPLOYMENT_FILE),
        "profiles": [_file(tree, path) for path in plan.declaration.profile_files],
        "baseImages": bases,
        "datastores": _datastores(plan, datastore_table),
        "locks": locks,
        "buildArgs": {"SOURCE_DATE_EPOCH": tree.time},
        "platform": platform,
        "fetches": {
            "baseImageRegistries": registries,
            "python": python_sources(lock),
            "npm": npm,
            "buildBackend": _build_backend_indexes(tree),
        },
    }
    section.update(carried_contract(tree))
    if generator is not None:
        section["generator"] = generator
    return section


def sbom(name: str, tag: str, packages: list[tuple[str, str]], ecosystem: str) -> dict[str, Any]:
    """A CycloneDX 1.5 SBOM of *packages*, with no timestamp, so one set is one byte string."""
    def purl(package: str, version: str) -> str:
        if ecosystem == "npm":
            return f"pkg:npm/{package.replace('@', '%40', 1)}@{version}"
        return f"pkg:pypi/{normalise(package)}@{version}"

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {"component": {"type": "container", "name": name, "version": tag}},
        "components": [
            {"type": "library", "name": package, "version": version, "purl": purl(package, version)}
            for package, version in packages
        ],
    }


def purls(document: dict[str, Any]) -> list[str]:
    return [component["purl"] for component in document["components"]]


def assemble(inputs_: dict[str, Any], outputs: dict[str, Any], collected: dict[str, Any]) -> bytes:
    """The manifest's bytes, as they are signed."""
    return canonical({"schemaVersion": SCHEMA_VERSION, "inputs": inputs_, "outputs": outputs, "collected": collected})


def _need(value: Any, kind: type | tuple[type, ...], where: str) -> Any:
    if not isinstance(value, kind):
        raise ReleaseError(f"the manifest's {where} is missing or not what a manifest holds there")
    return value


def parse(payload: bytes) -> dict[str, Any]:
    """A verified payload as a manifest, every field ``terp promote`` reads held to its shape."""
    try:
        manifest = json.loads(payload)
    except ValueError as exc:
        raise ReleaseError("the signed payload is not JSON") from exc
    _need(manifest, dict, "top level")
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise ReleaseError(
            f"the manifest is schemaVersion {manifest.get('schemaVersion')!r}, which this terp "
            f"promote does not read (allowed: {SCHEMA_VERSION})"
        )
    given = _need(manifest.get("inputs"), dict, "inputs")
    out = _need(manifest.get("outputs"), dict, "outputs")
    tag = _need(given.get("releaseTag"), str, "inputs.releaseTag")
    if RELEASE_TAG.fullmatch(tag) is None:
        raise ReleaseError(f"the manifest's release tag {tag!r} is not a Docker tag")
    if given.get("build") not in ("own", "generated"):
        raise ReleaseError("the manifest's inputs.build is neither own nor generated")
    _need(_need(given.get("spec"), dict, "inputs.spec").get("release"), str, "inputs.spec.release")
    carried = [_need(given.get("declaration"), dict, "inputs.declaration"), *_need(given.get("profiles"), list, "inputs.profiles")]
    if "contract" in given:
        carried.append(_need(given["contract"], dict, "inputs.contract"))
    for item in carried:
        _need(item, dict, "inputs.profiles[]")
        for key in ("path", "sha256", "content"):
            _need(item.get(key), str, f"carried file {key}")
        if sha256(item["content"].encode("utf-8")) != item["sha256"]:
            raise ReleaseError(f"the carried {item['path']} is not the content its SHA-256 names")
    _need(given.get("datastores"), dict, "inputs.datastores")
    for name, image in _need(out.get("images"), dict, "outputs.images").items():
        for key in ("repository", "digest", "imageId"):
            _need(_need(image, dict, f"outputs.images.{name}").get(key), str, f"outputs.images.{name}.{key}")
    _need(out.get("services"), dict, "outputs.services")
    return manifest


__all__ = ["HOSTS", "PROJECT_ROOT", "SCHEMA_VERSION", "assemble", "carried_contract", "development_profile", "inputs", "parse", "purls", "sbom"]
