"""``terp release sign``: check what ``build`` pushed against the commit, then sign the manifest.

The third job (ADR 0187 decision 6). It is the operator's own toolchain at its newest version,
never the commit's, and it runs nothing of the app: it reads the commit's tree and history from
git and the images from the registry as data, and it judges what a sandbox computes.

1. It repeats ``build``'s refusals, and takes the release tag and the registry from the driving
   tool, never from another job.
2. It validates the declaration with its own reader, against the datastore table of the
   ``terp-arch`` the commit pins, fetched by hash (:mod:`._render`), and refuses a Terp Standard
   release newer than its own.
3. In the generated state it renders the generator's files with that pinned ``terp-arch``, in a
   process of its own, and refuses a committed file that differs.
4. It checks each digest from ``build``'s document in the registry, and that the release tag
   names it there.
5. It reads the backend image in the sandbox and holds it to the tree and the lock
   (:mod:`._compare`); it computes each image's SBOM (the backend's from its filesystem, the web
   image's from the frontend lock), asks the vulnerability database about them, and scans the
   history reachable from the SHA for secrets, which it refuses to sign over.
6. It signs the manifest as a DSSE envelope, with ``--signer <argv>`` (the production path, whose
   key never enters this process) or ``--sign-key <file>``, which it refuses without
   ``--test-key``.

It refuses a gate whose release-assurance claim does not hold, and it writes, beside the
envelope, the manifest's bytes, each SBOM and each installed-package list.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import pathlib
import tempfile
import tomllib
from collections.abc import Sequence
from typing import Any

from terp.arch.deployment.datastores import read_table
from terp.arch.deployment.reader import SPEC_RELEASE
from terp.cli.release import dsse
from terp.cli.release._common import (
    ReleaseError,
    canonical,
    commit_id,
    read_document,
    release_tag,
    sha256,
)
from terp.cli.release._compare import compare_backend, wheel_shape
from terp.cli.release._git import Tree
from terp.cli.release._image import final_base
from terp.cli.release._locks import NPM_LOCK, UV_LOCK, npm_packages, pinned, read_npm_lock, read_uv_lock
from terp.cli.release._plan import Plan, release_plan
from terp.cli.release._registry import Registry, egress_getter
from terp.cli.release._render import DEFAULT_INDEX, DEFAULT_TABLE, Pinned, fetch, render, version_key
from terp.cli.release._sandbox import sandboxed
from terp.cli.release.build import DOCUMENT as BUILD_DOCUMENT
from terp.cli.release.build import loopback, registry
from terp.cli.release.gate import DOCUMENT as GATE_DOCUMENT
from terp.cli.release.manifest import HOSTS, assemble, inputs, purls, sbom

DEFAULT_OSV = "https://api.osv.dev"
ENVELOPE = "release.dsse.json"
MANIFEST = "release.manifest.json"


def _signer_version() -> str:
    try:
        return importlib.metadata.version("terp-cli")
    except importlib.metadata.PackageNotFoundError:  # a source checkout of the framework
        return "0"


def _signing(
    signer: Sequence[str] | None, public_key: str | os.PathLike[str] | None,
    sign_key: str | os.PathLike[str] | None, test_key: bool,
) -> tuple[Any, Any]:
    """``(private key or None, public key or None)``, refused unless one honest way to sign."""
    dsse.require_cryptography()
    if (signer is None) == (sign_key is None):
        raise ReleaseError("sign with exactly one of --signer <argv> (production) or --sign-key <file> --test-key")
    if sign_key is not None:
        if not test_key:
            raise ReleaseError(
                "--sign-key puts a private key in this process, which a release signer never "
                "holds: use --signer <argv>, or say --test-key for a throwaway key in a test"
            )
        return dsse.load_private_key(pathlib.Path(sign_key).read_bytes()), None
    if public_key is None:
        raise ReleaseError("--signer needs --public-key, so the signature is checked before it is written")
    return None, dsse.load_public_key(pathlib.Path(public_key).read_bytes())


def _project(tree: Tree) -> tuple[str, str]:
    project = tomllib.loads(tree.read_text("pyproject.toml")).get("project", {})
    name, version = project.get("name"), project.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise ReleaseError("pyproject.toml names no [project] name and version")
    return name, version


def _generated(pinned_arch: Pinned, tree: Tree, root: pathlib.Path, scratch: pathlib.Path, name: str) -> dict[str, Any]:
    files, owned, refused = render(pinned_arch, root, scratch)
    if refused:
        raise ReleaseError(
            f"terp-arch {pinned_arch.version} cannot render this commit's declaration:\n"
            + "\n".join(f"- {message}" for message in refused)
        )
    differ = [
        path for path in owned
        if (path in files and (not tree.has(path) or tree.bytes(path) != files[path]))
        or (path not in files and tree.has(path))
    ]
    if differ:
        raise ReleaseError(
            f"the committed {', '.join(differ)} is not the render of deployment.json by terp-arch "
            f"{pinned_arch.version}: run `uv run terp deployment render` and commit what it writes"
        )
    return {"version": pinned_arch.version, "project": name, "files": {path: sha256(files[path]) for path in sorted(files)}}


def _images(plan: Plan, build: dict[str, Any], prefix: str, tag: str, platform: str, reg: Registry) -> dict[str, dict[str, Any]]:
    pushed = {image["name"]: image for image in build["images"]}
    if sorted(pushed) != sorted(image.name for image in plan.images):
        raise ReleaseError(
            f"the build pushed {', '.join(sorted(pushed)) or 'nothing'}, and this commit builds "
            f"{', '.join(image.name for image in plan.images)}"
        )
    checked: dict[str, dict[str, Any]] = {}
    for image in plan.images:
        entry = pushed[image.name]
        repository = f"{prefix}/{image.name}"
        if entry["repository"] != repository or entry["tag"] != tag:
            raise ReleaseError(f"the build pushed {image.name} as {entry['repository']}:{entry['tag']}, not {repository}:{tag}")
        digest, manifest, config = reg.image(repository, entry["digest"], platform)
        if digest != entry["digest"]:
            raise ReleaseError(f"{repository}@{entry['digest']} is an index, and a release pushes one image per name")
        if manifest["config"]["digest"] != entry["configDigest"]:
            raise ReleaseError(f"{repository}@{digest} has another configuration than the build recorded")
        if f"{config.get('os')}/{config.get('architecture')}" != platform:
            raise ReleaseError(f"{repository}@{digest} is built for {config.get('os')}/{config.get('architecture')}, not {platform}")
        if reg.manifest(repository, tag)[0] != digest:
            raise ReleaseError(f"{repository}:{tag} no longer names {digest}, the image the build pushed")
        checked[image.name] = {**entry, "image": image}
    return checked


def _running(plan: Plan, images: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    """The image, by digest, of every profile service the release runs and of every unit."""
    services = dict(plan.datastores)
    for image in plan.images:
        for service in image.services:
            services[service] = f"{images[image.name]['repository']}@{images[image.name]['digest']}"
    units = {unit.id: services[unit.id] for unit in plan.declaration.units if unit.id in services}
    return {"services": services, "units": units}


def sign(
    repo: str | os.PathLike[str],
    sha: str,
    tag: str,
    target: str,
    build_document: str | os.PathLike[str],
    gate_document: str | os.PathLike[str],
    out_dir: str | os.PathLike[str],
    *,
    hosts: str,
    signer: Sequence[str] | None = None,
    public_key: str | os.PathLike[str] | None = None,
    sign_key: str | os.PathLike[str] | None = None,
    test_key: bool = False,
    releases: str | os.PathLike[str] = DEFAULT_TABLE,
    index: str = DEFAULT_INDEX,
    registry_http: bool = False,
    registry_credentials: str | os.PathLike[str] | None = None,
    osv: str = DEFAULT_OSV,
    gitleaks: str = "gitleaks",
) -> dict[str, Any]:
    """Check commit *sha*'s release and sign its manifest; what was written, and where."""
    private, public = _signing(signer, public_key, sign_key, test_key)
    commit_id(sha)
    release_tag(tag)
    host, prefix = registry(target)
    if registry_http and not loopback(host):
        raise ReleaseError(f"--registry-http is for a registry on this machine's loopback, and {host} is not one")
    if hosts not in HOSTS:
        raise ReleaseError(f"--hosts is {hosts!r} (allowed: {', '.join(HOSTS)})")
    build = read_document(build_document, BUILD_DOCUMENT)
    gate = read_document(gate_document, GATE_DOCUMENT)
    for name, document in (("build", build), ("gate", gate)):
        if document["commit"] != sha:
            raise ReleaseError(f"the {name} document is of {document['commit']}, not of {sha}")
    if gate["assurance"].get("ok") is not True:
        raise ReleaseError("the gate's release-assurance claim does not hold: sign signs only a release the gate passed")
    credentials = None
    if registry_credentials is not None:
        loaded = json.loads(pathlib.Path(registry_credentials).read_text(encoding="utf-8"))
        credentials = (str(loaded["username"]), str(loaded["password"]))
    tree = Tree.read(repo, sha)
    lock = read_uv_lock(tree.read_text(UV_LOCK)) if tree.has(UV_LOCK) else {"package": []}
    platform = str(build["platform"])
    with tempfile.TemporaryDirectory(prefix="terp-sign-") as scratch_dir:
        scratch = pathlib.Path(scratch_dir)
        root = scratch / "tree"
        tree.materialize(root)
        cli_pin, arch_pin = pinned(lock, "terp-cli"), pinned(lock, "terp-arch")
        if cli_pin is None or arch_pin is None:
            raise ReleaseError(f"{UV_LOCK} pins no single terp-cli and terp-arch, so the commit's toolchain is unknown")
        arch = fetch(releases, index, arch_pin, scratch)
        if version_key(arch.spec) > version_key(SPEC_RELEASE):
            raise ReleaseError(
                f"the commit's declaration was written against Terp Standard {arch.spec}, newer than "
                f"{SPEC_RELEASE}, the release this signer reads: update the signer image first"
            )
        plan = release_plan(tree, root, read_table(arch.datastores))
        wheel_shape(tree)
        name, version = _project(tree)
        generator = _generated(arch, tree, root, scratch, name) if plan.declaration.build == "generated" else None
        reg = Registry(egress_getter(host, http=registry_http), http=registry_http, credentials=credentials)
        images = _images(plan, build, prefix, tag, platform, reg)
        outputs_images: dict[str, Any] = {}
        documents: dict[str, bytes] = {}
        all_purls: dict[str, list[str]] = {}
        for image_name, entry in sorted(images.items()):
            if entry["image"].web:  # the plan says which image is the web tier, never the build
                packages = npm_packages(read_npm_lock(tree.read_text(NPM_LOCK))) if tree.has(NPM_LOCK) else []
                bom = sbom(image_name, tag, packages, "npm")
            else:
                answer = sandboxed("image", {
                    "repository": entry["repository"], "digest": entry["digest"], "platform": platform,
                    "http": registry_http, "credentials": list(credentials) if credentials else None,
                    "tree": str(root), "base": final_base(tree.read_text(entry["image"].dockerfile)),
                })
                if answer.get("configDigest") != entry["configDigest"]:
                    raise ReleaseError(f"the sandbox read another image than {entry['repository']}@{entry['digest']}")
                findings, packages = compare_backend(tree, answer, name, version, lock)
                if findings:
                    raise ReleaseError(
                        f"the image {entry['repository']}@{entry['digest']} is not this commit's build:\n"
                        + "\n".join(f"- {finding}" for finding in findings)
                    )
                bom = sbom(image_name, tag, packages, "pypi")
            safe = image_name.replace("/", "_")
            documents[f"packages-{safe}.json"] = canonical([list(item) for item in packages])
            documents[f"sbom-{safe}.cdx.json"] = canonical(bom)
            all_purls[image_name] = purls(bom)
            outputs_images[image_name] = {
                "repository": entry["repository"], "tag": tag, "digest": entry["digest"],
                "imageId": entry["configDigest"], "web": entry["image"].web,
                "packages": sha256(documents[f"packages-{safe}.json"]),
                "sbom": sha256(documents[f"sbom-{safe}.cdx.json"]),
            }
        scan = sandboxed("scan", {"osv": osv, "purls": sorted({p for found in all_purls.values() for p in found})})
        for image_name, found in all_purls.items():
            outputs_images[image_name]["vulnerabilities"] = {
                purl: ids for purl, ids in scan["vulnerable"].items() if purl in found
            }
        ignore = tree.read_text(".gitleaksignore") if tree.has(".gitleaksignore") else None
        secrets = sandboxed("secrets", {"gitleaks": gitleaks, "repo": str(repo), "sha": sha, "ignore": ignore})
        if secrets["findings"]:
            raise ReleaseError(
                f"gitleaks finds {len(secrets['findings'])} secrets in the history reachable from {sha}, "
                "and sign does not sign over a leaked secret: rotate it, then acknowledge its "
                "fingerprint in .gitleaksignore"
            )
        manifest = assemble(
            inputs(
                tree, plan, tag=tag,
                toolchain={"signer": _signer_version(), "terpCli": cli_pin, "terpArch": arch_pin},
                spec={"release": arch.spec, "schemaSha256": arch.schema_sha256},
                generator=generator, datastore_table=arch.datastores, platform=platform,
            ),
            {
                "images": outputs_images,
                "secretScan": {"tool": secrets["tool"], "version": secrets["version"], "findings": 0},
                "vulnerabilityDatabase": scan["database"],
                **_running(plan, images),
            },
            {
                "schedules": gate["schedules"],
                "assurance": gate["assurance"],
                "build": {
                    "builder": build["builder"],
                    "images": [{"name": i["name"], "digest": i["digest"], "configDigest": i["configDigest"]} for i in build["images"]],
                },
                "hosts": hosts,
            },
        )
    signature = dsse.sign_with_key(private, manifest) if private is not None else dsse.sign_with_command(signer or [], manifest)
    envelope = dsse.envelope(manifest, [signature])
    dsse.verify(canonical(envelope), [public if public is not None else private.public_key()])
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / ENVELOPE).write_bytes(canonical(envelope) + b"\n")
    (out / MANIFEST).write_bytes(manifest + b"\n")
    for file_name, data in documents.items():
        (out / file_name).write_bytes(data + b"\n")
    return {"envelope": str(out / ENVELOPE), "keyid": signature["keyid"], "images": sorted(outputs_images)}


__all__ = ["DEFAULT_OSV", "ENVELOPE", "MANIFEST", "sign"]
