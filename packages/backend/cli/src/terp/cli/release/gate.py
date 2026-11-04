"""``terp release gate``: the release profile, and the schedules read from the pushed image.

The second job, and the one that runs the app outside a build container: its tests, its
conformance suite, the development stack the suite drives, the install-time code of its
dependencies. So it holds nothing a release is protected by (ADR 0187 decision 6): no push
credential and no key, and nothing it writes reaches an image, which ``build`` already pushed.
What it produces is its word:

* the verdict of one run of ``terp verify --profile release --format json`` in the checkout of
  the SHA, with npm's lifecycle scripts off: every check it ran, by id with whether it passed,
  and the release-assurance claim those same results compose (ADR 0200). Nothing a check
  printed is recorded, because that is the app's own text from a run with the app's environment;
* the schedule catalog, each schedule's name, cron and job, read by running the pushed backend
  image, pulled by digest, as its own non-root user with no network and a read-only filesystem,
  so a deploy tool that never imports the app can trigger every schedule.

``sign`` reads the document in the version the commit's pinned ``terp-cli`` writes, and signs a
version 2 document only when every check passed and the claim holds (:func:`require_passed`); the
manifest files the claim and the schedules under ``collected``.

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
from terp.cli.release._render import version_key
from terp.cli.release.build import DOCUMENT as BUILD_DOCUMENT
from terp.cli.verify import assurance_document

DOCUMENT = "terpReleaseGate"

#: The version this toolchain writes: every check of the release profile beside the claim.
#: Version 1, which the gate wrote before :data:`STRICT_SINCE`, records the claim alone.
VERSION = 2

#: The first ``terp-cli`` release whose gate writes :data:`VERSION`. The gate is the commit's own
#: pinned toolchain (ADR 0187 decision 6), so ``sign`` reads a commit's document in the version
#: this says its gate writes, and in no other (ADR 0200 decision 3).
STRICT_SINCE = "0.36.1"

#: The command the gate runs, once: the whole release profile, with every check's verdict.
VERIFY = ("verify", "--profile", "release", "--format", "json")

#: How the pushed image is run to read it: its own user, no network, nothing writable.
_SEALED = (
    "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges", "--tmpfs", "/tmp", "--pull", "never",  # noqa: S108 - in the container
)


def _is_verdict(check: object) -> bool:
    """Whether *check* is one check's verdict: its id, and whether it passed."""
    return isinstance(check, dict) and isinstance(check.get("id"), str) and isinstance(check.get("ok"), bool)


def _verify(checkout: pathlib.Path) -> list[dict[str, Any]]:
    """Every check the release profile ran in *checkout*, with npm scripts off: its id and verdict."""
    completed = run(
        [sys.executable, "-c", "from terp.cli import main; main()", *VERIFY],
        cwd=checkout,
        env={**os.environ, "npm_config_ignore_scripts": "true"},
    )
    try:
        document = json.loads(completed.stdout.decode("utf-8"))
    except ValueError as exc:
        raise ReleaseError(
            "terp verify --profile release wrote no verdict document",
            cause=completed.stderr.decode("utf-8", errors="replace")[-4000:],
        ) from exc
    checks = document.get("checks") if isinstance(document, dict) else None
    if (
        not isinstance(checks, list) or not checks
        or document.get("terp_verify") != 1 or document.get("profile") != "release"
        or not all(_is_verdict(check) for check in checks)
        or document.get("ok") is not all(check["ok"] for check in checks)
    ):
        raise ReleaseError("terp verify --profile release wrote no verdict of each check it ran")
    return [{"id": check["id"], "ok": check["ok"]} for check in checks]


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
    checks = _verify(pathlib.Path(repo))
    profile = {"name": "release", "ok": all(check["ok"] for check in checks), "checks": checks}
    assurance = assurance_document(checks)  # the same run's results, never a second run's
    backend = _backend(build)
    reference = f"{backend['repository']}@{backend['digest']}"
    with tempfile.TemporaryDirectory(prefix="terp-gate-") as config_dir:
        if pull_credentials is not None:
            shutil.copyfile(pull_credentials, pathlib.Path(config_dir) / "config.json")
        schedules = _schedules(reference, pathlib.Path(config_dir))
    return {
        DOCUMENT: VERSION,
        "commit": sha,
        "profile": profile,
        "assurance": assurance,
        "schedules": schedules,
        "image": reference,
    }


def red(document: dict[str, Any]) -> list[str]:
    """Every check a version 2 gate *document* records as failed, by id, in the order it ran."""
    return [check["id"] for check in document["profile"]["checks"] if not check["ok"]]


def _green(document: dict[str, Any]) -> None:
    """Refused unless a version 2 *document* holds a verdict of each check of the release profile,
    agrees with it, and every check passed."""
    profile = document.get("profile")
    checks = profile.get("checks") if isinstance(profile, dict) else None
    if (
        not isinstance(checks, list) or not checks or profile.get("name") != "release"
        or not isinstance(profile.get("ok"), bool) or not all(_is_verdict(check) for check in checks)
    ):
        raise ReleaseError(
            "the gate document holds no verdict of the release profile's checks: sign reads only "
            "what `terp release gate` writes, so run it again"
        )
    failed = red(document)
    if profile["ok"] == bool(failed):  # green over a red check, or red over none
        raise ReleaseError(
            "the gate document contradicts itself: it records the release profile as "
            + (f"green and {', '.join(failed)} red" if failed else "red and every check of it green")
            + ". sign signs only what one run of `terp release gate` wrote, so run it again"
        )
    if failed:
        raise ReleaseError(
            f"the release profile the gate ran is red ({', '.join(failed)}), and sign signs only a "
            "release whose every check passed: `terp verify --only <check>` in a checkout of the "
            "commit says why. Gate the commit again once its profile is green, or cut the release "
            "from the commit that makes it green"
        )


def require_passed(document: dict[str, Any], terp_cli: str) -> None:
    """Refused unless *document*, the gate of a commit pinning ``terp-cli`` *terp_cli*, passed.

    The gate is the commit's own pinned toolchain, so its document is read in the version that
    toolchain writes (ADR 0200): version 1 below :data:`STRICT_SINCE`, held to its
    release-assurance claim alone, as it always was; version 2 from it up, held to every check
    the release profile ran, to itself, and to the claim.
    """
    strict = version_key(terp_cli) >= version_key(STRICT_SINCE)
    expected = VERSION if strict else 1
    if document[DOCUMENT] != expected:
        raise ReleaseError(
            f"the gate document is version {document[DOCUMENT]}, and the commit pins terp-cli "
            f"{terp_cli}, whose gate writes version {expected}: sign reads a commit's gate only as "
            "its own toolchain wrote it. Run `uv run terp release gate` in the commit's checkout, "
            "and sign what it writes"
        )
    if strict:
        _green(document)
    claim = document.get("assurance")
    if not isinstance(claim, dict) or claim.get("ok") is not True:
        raise ReleaseError(
            "the gate's release-assurance claim does not hold: sign signs only a release the gate "
            "passed, and `terp verify --profile release --format assurance` in a checkout of the "
            "commit names the lane that failed"
        )


__all__ = ["DOCUMENT", "STRICT_SINCE", "VERIFY", "VERSION", "gate", "red", "require_passed"]
