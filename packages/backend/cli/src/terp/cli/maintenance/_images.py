"""Base images an app pins itself, against the digest each one's tag names now (ADR 0214).

Under ``"build": "generated"`` the framework's generator writes every ``FROM`` from terp-arch's
base-image table, and a framework release moves them (ADR 0187): ``platform-behind`` already
says when that is due, so nothing is asked here. Under ``"build": "own"`` the Dockerfiles are
the app's, and so is keeping their bases current.

The convention the template's Dockerfiles follow, and this reads: each base is pinned by
digest, and the tag the digest was read from stands in a comment on the line above its
``FROM``::

    # python:3.14-slim
    FROM python@sha256:9aaa... AS deps

A ``FROM`` with no such comment has no tag to compare with, and is left alone. The registry
is read the way ``sign`` reads one (:mod:`terp.cli.release._registry`): the OCI distribution
API through the declared egress client, Docker Hub's own token flow included.
"""

from __future__ import annotations

import json
import pathlib
import re

from terp.arch.deployment.datastores import parse_image
from terp.cli.maintenance._report import Finding, Report
from terp.cli.release._common import ReleaseError
from terp.cli.release._registry import Getter, Registry, egress_getter

#: The Dockerfiles the generator writes, read when the release plan itself cannot be.
DOCKERFILES = ("Dockerfile.prod", "frontend/Dockerfile.prod", "site/Dockerfile.prod")

_FROM = re.compile(r"\s*FROM\s+(?:--\S+\s+)*(?P<image>\S+@sha256:[0-9a-f]{64})(?:\s+AS\s+\S+)?\s*", re.IGNORECASE)
_TAG_COMMENT = re.compile(r"\s*#\s*(?P<ref>[^\s@]+:[^\s@]+)\s*")

#: Docker Hub's API host: ``docker.io`` is the name images carry, not where the API answers.
_DOCKER_HUB = ("docker.io", "registry-1.docker.io")


def own_build(root: pathlib.Path) -> bool:
    """Whether ``deployment.json`` says the app writes its own build files."""
    try:
        declared = json.loads((root / "deployment.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(declared, dict) and declared.get("build") == "own"


def _dockerfiles(root: pathlib.Path) -> tuple[list[str], str | None]:
    """The Dockerfiles a release of *root* builds from, and a sentence when that cannot be read.

    The release plan's own images (:func:`terp.cli.release._plan.planned_images`), so an app that
    builds from ``www/Dockerfile`` is read where its release reads it. When the plan cannot be
    read, the generator's three are, and the report says that is all it read.
    """
    from terp.arch.deployment import published_table
    from terp.cli.release._plan import planned_images

    try:
        images = planned_images(root, published_table())
    except (ReleaseError, OSError, ValueError) as exc:
        images, why = None, f": {exc}"
    else:
        why = ""
    if images is None:
        return list(DOCKERFILES), (
            f"base-image-behind: the release plan could not be read{why}, so only the Dockerfiles at "
            f"{', '.join(DOCKERFILES)} were compared"
        )
    return sorted({image.dockerfile for image in images}), None


def pinned_bases(root: pathlib.Path, dockerfiles: list[str]) -> tuple[list[tuple[str, str, str, str]], list[str]]:
    """``(Dockerfile, repository, pinned digest, tag)`` of every base pinned under a tag comment,
    once each, and a sentence for each base pinned by digest with no such comment, which has no
    tag to compare with."""
    found: list[tuple[str, str, str, str]] = []
    untagged: list[str] = []
    for dockerfile in dockerfiles:
        try:
            lines = (root / dockerfile).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for above, line in zip(["", *lines], lines, strict=False):
            pinned = _FROM.fullmatch(line)
            if pinned is None:
                continue
            comment = _TAG_COMMENT.fullmatch(above)
            image = parse_image(pinned.group("image"))
            tagged = parse_image(comment.group("ref")) if comment is not None else None
            if image is None or tagged is None or tagged.tag is None or image.repository != tagged.repository:
                sentence = (
                    f"base-image-behind: the FROM {pinned.group('image')} in {dockerfile} has no `# image:tag` "
                    "line naming its own image above it, so there is no tag to compare its digest with"
                )
                if sentence not in untagged:
                    untagged.append(sentence)
                continue
            base = (dockerfile, image.repository, str(image.digest), tagged.tag)
            if base not in found:
                found.append(base)
    return found, untagged


def _api(repository: str) -> str:
    host, _, path = repository.partition("/")
    return f"{_DOCKER_HUB[1]}/{path}" if host == _DOCKER_HUB[0] else repository


def base_image_findings(root: pathlib.Path, report: Report, *, getter: Getter | None = None) -> None:
    """Under ``"build": "own"``, a finding for every pinned base its tag has moved away from."""
    if not own_build(root):
        return
    dockerfiles, unplanned = _dockerfiles(root)
    if unplanned is not None:
        report.not_made(unplanned)
    bases, untagged = pinned_bases(root, dockerfiles)
    for sentence in untagged:
        report.not_made(sentence)
    if not bases:
        return
    current: dict[tuple[str, str], str] = {}
    try:
        for _dockerfile, repository, _digest, tag in bases:
            if (repository, tag) not in current:
                api = _api(repository)
                registry = Registry(getter or egress_getter(api.split("/", 1)[0], http=False))
                current[(repository, tag)] = registry.manifest(api, tag)[0]
    except ReleaseError as exc:
        report.unreachable(
            "registry",
            f"{exc.message}: {exc.cause}" if exc.cause else exc.message,
            "Check that the base images' registries are reachable from here, then run it again.",
        )
        return
    report.answered("registry")
    for dockerfile, repository, digest, tag in bases:
        now = current[(repository, tag)]
        if now == digest:
            continue
        name = repository.removeprefix("docker.io/library/").removeprefix("docker.io/")
        report.findings.append(
            Finding(
                "base-image-behind",
                f"{name}:{tag}",
                f"The tag {name}:{tag} names {now} now. Pin that digest in the FROM of {dockerfile}, "
                f"keep the `# {name}:{tag}` line above it, rebuild and run the gate.",
                location=dockerfile,
                installed=digest,
                latest=now,
            )
        )


__all__ = ["DOCKERFILES", "base_image_findings", "own_build", "pinned_bases"]
