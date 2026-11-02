"""``terp release gate``: the release profile, and the schedules read from the pushed image.

The second job, and the one that runs the app outside a build container: its tests, its
conformance suite, the development stack the suite drives, the install-time code of its
dependencies. So it holds nothing a release is protected by (ADR 0187 decision 6): no push
credential and no key, and nothing it writes reaches an image, which ``build`` already pushed.
What it produces is its word, and the manifest files it under ``collected``:

* the assurance document of ``terp verify --profile release --format assurance``, run in the
  checkout of the SHA with npm's lifecycle scripts off;
* the schedule catalog, each schedule's name, cron and job, read by running the pushed backend
  image, pulled by digest, as its own non-root user with no network and a read-only filesystem,
  so a deploy tool that never imports the app can trigger every schedule.

The checkout must be the SHA, clean. Its docker client gets a configuration directory of its
own, holding nothing or the pull credential it is given, so the operator's push credential is
never the one an image is pulled with here.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile
from typing import Any

from terp.cli.release._common import (
    ReleaseError,
    commit_id,
    os_environment,
    read_document,
    require,
    run,
)
from terp.cli.release._git import head
from terp.cli.release.build import DOCUMENT as BUILD_DOCUMENT

DOCUMENT = "terpReleaseGate"

#: The command the gate runs: the whole release profile, as its assurance claim.
VERIFY = ("verify", "--profile", "release", "--format", "assurance")

#: How the pushed image is run to read it: its own user, no network, nothing writable.
_SEALED = (
    "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges", "--tmpfs", "/tmp", "--pull", "never",  # noqa: S108 - in the container
)


def _verify(checkout: pathlib.Path) -> dict[str, Any]:
    """The release profile's assurance claim, run in *checkout* with npm scripts off."""
    completed = run(
        [sys.executable, "-c", "from terp.cli import main; main()", *VERIFY],
        cwd=checkout,
        env={**os.environ, "npm_config_ignore_scripts": "true"},
    )
    try:
        document = json.loads(completed.stdout.decode("utf-8"))
    except ValueError as exc:
        raise ReleaseError(
            "terp verify --profile release wrote no assurance document",
            cause=completed.stderr.decode("utf-8", errors="replace")[-4000:],
        ) from exc
    if not isinstance(document, dict) or not isinstance(document.get("ok"), bool):
        raise ReleaseError("terp verify --profile release wrote no assurance claim")
    return document


def _backend(build: dict[str, Any]) -> dict[str, Any]:
    backends = [image for image in build["images"] if not image.get("web")]
    if len(backends) != 1:
        raise ReleaseError(
            f"the build pushed {len(backends)} backend images, and the gate reads the schedules "
            "from exactly one"
        )
    return backends[0]


def _schedules(reference: str, config: pathlib.Path) -> list[dict[str, str]]:
    """The schedule catalog, read by running *reference* sealed, as its own non-root user."""
    env = os_environment({"DOCKER_CONFIG": str(config)}, names=("DOCKER_HOST", "DOCKER_CONTEXT"))
    require(run(["docker", "pull", reference], env=env), f"pulling {reference}")
    user = json.loads(
        require(
            run(["docker", "image", "inspect", "--format", "{{json .Config.User}}", reference], env=env),
            f"inspecting {reference}",
        )
    )
    if str(user).split(":", 1)[0] in ("", "0", "root"):
        raise ReleaseError(f"{reference} runs as root, and the gate runs it only as a non-root user")
    shown = require(
        run(
            ["docker", "run", *_SEALED, "--entrypoint", "terp", reference,
             "inspect", "control-plane", "--format", "json"],
            env=env,
        ),
        "reading the schedule catalog from the image",
    )
    try:
        schedules = json.loads(shown.decode("utf-8"))["schedules"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ReleaseError("the image printed no schedule catalog", cause=str(exc)) from exc
    return [
        {"name": str(item["name"]), "cron": str(item["cron"]), "job": str(item["job"])}
        for item in schedules
    ]


def gate(
    repo: str | os.PathLike[str],
    sha: str,
    build_document: str | os.PathLike[str],
    *,
    pull_credentials: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """The gate document for commit *sha*, checked out clean at *repo*."""
    commit_id(sha)
    build = read_document(build_document, BUILD_DOCUMENT)
    if build["commit"] != sha:
        raise ReleaseError(f"{build_document} is the build of {build['commit']}, not of {sha}")
    current, clean = head(repo)
    if current != sha or not clean:
        raise ReleaseError(
            f"the gate runs in a clean checkout of {sha}, and {repo} has "
            f"{current}{'' if clean else ' with changes'} checked out"
        )
    assurance = _verify(pathlib.Path(repo))
    backend = _backend(build)
    reference = f"{backend['repository']}@{backend['digest']}"
    with tempfile.TemporaryDirectory(prefix="terp-gate-") as config_dir:
        if pull_credentials is not None:
            shutil.copyfile(pull_credentials, pathlib.Path(config_dir) / "config.json")
        schedules = _schedules(reference, pathlib.Path(config_dir))
    return {
        DOCUMENT: 1,
        "commit": sha,
        "assurance": assurance,
        "schedules": schedules,
        "image": reference,
    }


__all__ = ["DOCUMENT", "VERIFY", "gate"]
