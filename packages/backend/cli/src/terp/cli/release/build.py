"""``terp release build``: the images of one commit, built from its pristine tree (ADR 0187 d6).

The first of the three release jobs, and the only one that runs the app's build: its code runs
inside BuildKit's build containers alone, which hold no credential and no secret mount. The job
itself reads the commit as data and never installs the app's environment on its host:

1. it reads the tree of the exact SHA from git's object store and writes it out, byte for byte,
   as the build context, so nothing a working copy holds (an edit, a generated file, a secret
   git ignores) can reach an image;
2. it refuses, from data, what ``terp release`` refuses (:mod:`terp.cli.release._plan`);
3. it creates a BuildKit builder for this job alone, from a pinned image, and removes it after;
4. it builds every image the profile builds from the checkout with ``--pull`` and no cache,
   import or export, and pushes each under ``<registry>/<name>:<tag>`` with the credential the
   operator's docker configuration holds for this release;
5. it writes BuildKit's own metadata, the pushed digests, into the build document ``sign`` reads.

The build arguments are ``SOURCE_DATE_EPOCH`` alone, the commit's own time, so two cold builds of
one commit read the same inputs; whether they give the same image bytes is measured, never
promised (ADR 0187).
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import secrets
import tempfile
from typing import Any

from terp.arch.deployment import published_table
from terp.cli.release._common import (
    DOCKER_NAMES,
    ReleaseError,
    commit_id,
    os_environment,
    release_tag,
    output_of,
    require,
    run,
)
from terp.cli.release._git import Tree
from terp.cli.release._plan import Plan, release_plan

#: The BuildKit a release builds with, by digest: v0.34.1, the image index
#: ``docker buildx imagetools inspect moby/buildkit:v0.34.1`` named on 2026-10-22 (linux/amd64,
#: arm64, arm/v7, s390x, ppc64le, riscv64). A tag can move between two builds of one commit.
BUILDKIT_IMAGE = (
    "moby/buildkit@sha256:99368f3e46177c6405b9740e4461d91cee004128daeecca78d4ceac50ec1da5c"
)

#: The one platform a release is built for (ADR 0187: one platform per release).
DEFAULT_PLATFORM = "linux/amd64"

#: A registry and the path under it the release's repositories live at, never a scheme, a tag
#: or a digest: ``registry.example/team`` or ``localhost:5000/rel``.
_REGISTRY = re.compile(
    r"(?P<host>[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[0-9]{1,5})?)(?P<path>(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*)"
)
_LOOPBACK = frozenset({"localhost", "127.0.0.1"})

DOCUMENT = "terpReleaseBuild"

#: What the builder created for one job is named, before its random part: a lane that runs on a
#: shared engine names everything it creates under a prefix of its own.
BUILDER_PREFIX = "rel-"


def registry(value: str) -> tuple[str, str]:
    """``(host, prefix)`` of a release registry, refused when it is not one."""
    found = _REGISTRY.fullmatch(value)
    if found is None:
        raise ReleaseError(
            f"{value!r} is not a registry and path (allowed: host[:port][/path], lower case, "
            "with no scheme, tag or digest)"
        )
    return found.group("host"), value


def loopback(host: str) -> bool:
    """Whether *host* is this machine, the one place a plain-HTTP registry is accepted."""
    return host.rsplit(":", 1)[0] in _LOOPBACK


def docker_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    """What a docker client this job runs may see: the OS, the engine, the operator's config."""
    return os_environment(extra, names=(*DOCKER_NAMES, "DOCKER_CONFIG"))


def _builder(name: str, host: str, http: bool, scratch: pathlib.Path) -> None:
    argv = [
        "docker", "buildx", "create", "--name", name, "--driver", "docker-container",
        "--driver-opt", f"image={BUILDKIT_IMAGE}", "--bootstrap",
    ]
    if http:
        config = scratch / "buildkitd.toml"
        config.write_text(f'[registry."{host}"]\n  http = true\n  insecure = true\n', encoding="utf-8")
        argv += ["--driver-opt", "network=host", "--buildkitd-config", str(config)]
    require(run(argv, env=docker_environment()), f"creating the builder {name}")


def _versions(name: str) -> dict[str, str]:
    shown = require(
        run(["docker", "buildx", "inspect", name], env=docker_environment()), "inspecting the builder"
    ).decode("utf-8", errors="replace")
    found = re.search(r"BuildKit version:\s*(\S+)", shown)
    buildx = require(run(["docker", "buildx", "version"], env=docker_environment()), "reading buildx's version")
    return {
        "buildkit": found.group(1) if found else "",
        "buildx": buildx.decode("utf-8", errors="replace").strip(),
        "image": BUILDKIT_IMAGE,
    }


def _build_one(
    builder: str, root: pathlib.Path, image: Any, repository: str, tag: str, platform: str,
    epoch: int, scratch: pathlib.Path,
) -> dict[str, Any]:
    metadata = scratch / f"metadata-{image.name.replace('/', '_')}.json"
    argv = [
        "docker", "buildx", "build", "--builder", builder, "--pull", "--no-cache",
        "--platform", platform, "--provenance=false", "--sbom=false", "--progress=plain",
        "--file", str(root / image.dockerfile),
        "--build-arg", f"SOURCE_DATE_EPOCH={epoch}",
        "--output", f"type=image,name={repository}:{tag},push=true,rewrite-timestamp=true",
        "--metadata-file", str(metadata),
        str(root / image.context),
    ]
    require(run(argv, env=docker_environment()), f"building {image.name}")
    try:
        written = json.loads(metadata.read_text(encoding="utf-8"))
        digest, config = written["containerimage.digest"], written["containerimage.config.digest"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ReleaseError(
            f"BuildKit wrote no digest for {image.name}", cause=f"{type(exc).__name__}: {exc}"
        ) from exc
    return {
        "name": image.name,
        "repository": repository,
        "tag": tag,
        "digest": digest,
        "configDigest": config,
        "context": image.context,
        "dockerfile": image.dockerfile,
        "services": list(image.services),
        "web": image.web,
    }


def build(
    repo: str | os.PathLike[str],
    sha: str,
    tag: str,
    target: str,
    *,
    platform: str = DEFAULT_PLATFORM,
    registry_http: bool = False,
) -> dict[str, Any]:
    """Build and push every image commit *sha* builds; the build document ``sign`` reads."""
    commit_id(sha)
    release_tag(tag)
    host, prefix = registry(target)
    if registry_http and not loopback(host):
        raise ReleaseError(
            f"--registry-http is for a registry on this machine's loopback, and {host} is not one"
        )
    tree = Tree.read(repo, sha)
    with tempfile.TemporaryDirectory(prefix="terp-release-") as scratch_dir:
        scratch = pathlib.Path(scratch_dir)
        root = scratch / "context"
        tree.materialize(root)
        plan: Plan = release_plan(tree, root, published_table())
        name = f"{BUILDER_PREFIX}{secrets.token_hex(6)}"
        _builder(name, host, registry_http, scratch)
        try:
            versions = _versions(name)
            images = [
                _build_one(name, root, image, f"{prefix}/{image.name}", tag, platform, tree.time, scratch)
                for image in plan.images
            ]
        finally:
            removed = run(["docker", "buildx", "rm", "--force", name], env=docker_environment())
        if removed.returncode != 0:
            raise ReleaseError(f"the builder {name} could not be removed", cause=output_of(removed))
    return {
        DOCUMENT: 1,
        "commit": sha,
        "tree": tree.tree,
        "releaseTag": tag,
        "platform": platform,
        "sourceDateEpoch": tree.time,
        "builder": versions,
        "images": images,
    }


__all__ = ["BUILDKIT_IMAGE", "DEFAULT_PLATFORM", "DOCUMENT", "build", "docker_environment", "loopback", "registry"]
