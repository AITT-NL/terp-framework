"""What a commit releases, and every reason ``terp release`` refuses it (ADR 0184 d9, 0187 d6).

``build`` and ``sign`` both ask this, from data alone: the commit's tree, written out as a
pristine directory, and the datastore table the declaration is read against. Neither trusts
the other's answer, so ``sign`` repeats every refusal ``build`` makes (ADR 0187 decision 6,
step 1). The answer is the plan: the declaration, the resolved profile, the images built from
the checkout and the services each one runs, the migration step and the datastores.

Refused, every one named and listed together:

* an undeclared app, an ``unmanaged`` one, and a declaration that cannot be read or is untrue;
* a tree holding ``.terp-dist/`` or a submodule, and a lock naming a package by a path: a
  pristine context of the commit holds neither the vendored wheels nor the other checkout;
* a profile service on an image neither built from the checkout nor a datastore table digest;
* a ``kind`` unit whose service has no healthcheck, which could never be shown ready;
* more than one migration step, or one passing ``--revision`` or ``--sql``; no migration step
  and other than exactly one ``api`` unit, so no one image runs the upgrade;
* a built image whose name does not read the per-release tag, ``TERP_RELEASE_TAG`` (ADR 0185),
  and a build that says more than its context and its Dockerfile: a build argument, a secret
  or a target is a part of the image nobody signs.

A service under a compose ``profiles:`` key is not part of the release: nothing starts it.
"""

from __future__ import annotations

import pathlib
import re
import shlex
from dataclasses import dataclass
from typing import Any

from terp.arch.deployment import (
    DEPLOYMENT_FILE,
    Declaration,
    DatastoreTable,
    Unmanaged,
    compose_literal,
    readable,
    resolve_profile,
    services_of,
)
from terp.arch.deployment.generator import RELEASE_TAG_VARIABLE
from terp.arch.deployment.profile import truth_findings
from terp.cli.release._common import ReleaseError
from terp.cli.release._git import Tree
from terp.cli.release._locks import (
    NPM_LOCK,
    UV_LOCK,
    npm_path_sources,
    path_sources,
    read_npm_lock,
    read_uv_lock,
)

#: An image a release builds: a name, then exactly the per-release tag.
_TAGGED = re.compile(
    r"(?P<name>[a-z0-9]+(?:[._/-]+[a-z0-9]+)*):\$\{"
    + RELEASE_TAG_VARIABLE
    + r"(?::\?[^}]*)?\}"
)

#: What a release builds a service from, and nothing else.
_BUILD_KEYS = frozenset({"context", "dockerfile"})

_STEP = ("terp", "migrate", "upgrade")


@dataclass(frozen=True)
class Image:
    """One image the release builds from the checkout, and the profile services that run it."""

    name: str
    context: str
    dockerfile: str
    services: tuple[str, ...]
    #: The web tier's image: its bundle cannot be compared with the tree (ADR 0187).
    web: bool


@dataclass(frozen=True)
class Plan:
    """What one commit releases."""

    declaration: Declaration
    profile: dict[str, Any]
    services: dict[str, dict[str, Any]]
    images: tuple[Image, ...]
    #: The service that is the migration step, or ``None`` when the profile has none.
    migration_step: str | None
    #: The one ``api`` unit the upgrade runs in when there is no migration step.
    api: str | None
    #: Every service on a datastore table digest, by its image.
    datastores: dict[str, str]

    def image_of(self, service: str) -> Image | None:
        return next((image for image in self.images if service in image.services), None)


def argv(command: Any) -> tuple[str | None, ...] | None:
    """A profile command, element by element as compose runs it; ``None`` marks interpolation."""
    if isinstance(command, list):
        return tuple(compose_literal(str(part)) for part in command)
    if isinstance(command, str):
        literal = compose_literal(command)
        return (None,) if literal is None else tuple(shlex.split(literal))
    return None


def _relative(root: pathlib.Path, base: pathlib.Path, written: str) -> str:
    """*written*, relative to *base*, as a path relative to *root*.

    Being readable already refused a build path that resolves outside the checkout, and a
    pristine tree is its own checkout, so this always lands inside *root*.
    """
    return (base / written).resolve().relative_to(root.resolve()).as_posix()


def _tree_refusals(tree: Tree) -> list[str]:
    refused: list[str] = []
    if tree.paths(".terp-dist/"):
        refused.append(
            ".terp-dist/ is committed: a release builds from the commit alone, and vendored "
            "pre-release packages are no published release (publish them, or release on a "
            "published version)"
        )
    refused.extend(
        f"{path} is a submodule, which a pristine context of this commit does not hold"
        for path in tree.submodules
    )
    if not tree.has(UV_LOCK):
        refused.append(f"{UV_LOCK} is not committed, and the backend image installs exactly it")
    else:
        refused.extend(
            f"{UV_LOCK} takes {source} from a path, which a pristine context does not hold"
            for source in path_sources(read_uv_lock(tree.read_text(UV_LOCK)))
        )
    if tree.has(NPM_LOCK):
        refused.extend(
            f"{NPM_LOCK} takes {source} from a path, which a pristine context does not hold"
            for source in npm_path_sources(read_npm_lock(tree.read_text(NPM_LOCK)))
        )
    return refused


def _declaration(root: pathlib.Path, tree: Tree, table: DatastoreTable) -> tuple[Declaration | None, list[str]]:
    if not tree.has(DEPLOYMENT_FILE):
        return None, [
            f"this commit has no {DEPLOYMENT_FILE}: terp release drives a declared app only "
            "(ADR 0184 decision 9); `uv run terp deployment adopt --build own` declares one"
        ]
    declared, findings = readable(root, table)
    if findings:
        return None, [f"{DEPLOYMENT_FILE} cannot be read: {finding.message}" for finding in findings]
    if isinstance(declared, Unmanaged):
        return None, [
            f"{DEPLOYMENT_FILE} declares this app unmanaged ({declared.reason}): no tool drives "
            "its deploy, so terp release does not either"
        ]
    assert isinstance(declared, Declaration)
    untrue = truth_findings(root, declared, table)
    return declared, [f"{DEPLOYMENT_FILE} is not true: {finding.message}" for finding in untrue]


def _built(
    root: pathlib.Path, base: pathlib.Path, name: str, service: dict[str, Any], refused: list[str]
) -> tuple[str, str, str] | None:
    """``(image name, context, dockerfile)`` of a service that builds, or ``None`` refused."""
    build = service["build"]
    build = {"context": build} if isinstance(build, str) else build
    if not isinstance(build, dict) or set(build) - _BUILD_KEYS:
        extra = sorted(set(build) - _BUILD_KEYS) if isinstance(build, dict) else [type(build).__name__]
        refused.append(
            f"service {name} builds with {', '.join(extra)}: a release builds a service from its "
            "context and Dockerfile only (allowed: build.context and build.dockerfile)"
        )
        return None
    tagged = _TAGGED.fullmatch(str(service.get("image", "")))
    if tagged is None:
        refused.append(
            f"service {name} builds the image {service.get('image')!r}, which does not read the "
            f"per-release tag (allowed: <name>:${{{RELEASE_TAG_VARIABLE}:?...}}, ADR 0185)"
        )
        return None
    context = _relative(root, base, str(build.get("context", ".")))
    dockerfile = _relative(root, base / context, str(build.get("dockerfile", "Dockerfile")))
    return tagged.group("name"), context, dockerfile


def _images(
    root: pathlib.Path,
    declared: Declaration,
    services: dict[str, dict[str, Any]],
    table: DatastoreTable,
    refused: list[str],
) -> tuple[tuple[Image, ...], dict[str, str]]:
    base = (root / declared.compose_file).parent
    builds: dict[str, tuple[str, str, str]] = {}
    by_image: dict[str, str] = {}
    for name, service in sorted(services.items()):
        if "build" in service and (made := _built(root, base, name, service, refused)):
            if made[0] in builds and builds[made[0]][1:] != made[1:]:
                refused.append(f"the image {made[0]} is built twice, from two different builds")
            builds[made[0]] = (name, made[1], made[2])
            by_image[str(service["image"])] = made[0]
    runners: dict[str, list[str]] = {}
    datastores: dict[str, str] = {}
    for name, service in sorted(services.items()):
        image = service.get("image")
        if image in by_image:
            runners.setdefault(by_image[str(image)], []).append(name)
        elif any(entry.pinned_by(image) for entry in table.entries):
            datastores[name] = str(image)
        elif "build" not in service:
            refused.append(
                f"service {name} runs {image or 'no image'}, which is neither built from the "
                "checkout nor a datastore table digest (allowed: one of the two, ADR 0184 "
                "decision 9; deploy anything else by your own means, or declare unmanaged)"
            )
    webs = {unit.id for unit in declared.units if unit.role == "web" and unit.kind is None}
    images = tuple(
        Image(image, context, dockerfile, tuple(runners.get(image, [])), bool(webs & set(runners.get(image, []))))
        for image, (_builder, context, dockerfile) in sorted(builds.items())
    )
    return images, datastores


def _steps(
    declared: Declaration, services: dict[str, dict[str, Any]], refused: list[str]
) -> tuple[str | None, str | None]:
    steps = []
    for name, service in sorted(services.items()):
        parts = argv(service.get("command"))
        if parts is None or parts[:3] != _STEP:
            continue
        steps.append(name)
        for option in ("--revision", "--sql"):
            if any(part is not None and (part == option or part.startswith(f"{option}=")) for part in parts):
                refused.append(
                    f"service {name} runs the migration step with {option}, which does not bring "
                    "every package to head (allowed: terp migrate upgrade without it)"
                )
    if len(steps) > 1:
        refused.append(
            f"services {', '.join(steps)} each run terp migrate upgrade: a promotion runs the "
            "upgrade exactly once (allowed: one migration step, or none)"
        )
    apis = [unit.id for unit in declared.units if unit.role == "api" and unit.kind is None]
    if not steps and len(apis) != 1:
        refused.append(
            f"the profile has no migration step and {len(apis)} api units, so no one image runs "
            "the upgrade (allowed: a migration step, or exactly one api unit)"
        )
    return (steps[0] if steps else None), (apis[0] if len(apis) == 1 else None)


def _health(declared: Declaration, services: dict[str, dict[str, Any]], refused: list[str]) -> None:
    for unit in declared.units:
        check = services.get(unit.id, {}).get("healthcheck")
        if unit.kind is not None and not (isinstance(check, dict) and check.get("test") and not check.get("disable")):
            refused.append(
                f"{unit.kind} unit {unit.id} has no healthcheck, so it could never be shown "
                "ready before the migration step runs (allowed: a healthcheck with a test)"
            )


def release_plan(tree: Tree, root: pathlib.Path, table: DatastoreTable) -> Plan:
    """The plan for the tree written out at *root*, or every refusal at once."""
    refused = _tree_refusals(tree)
    declared, found = _declaration(root, tree, table)
    refused.extend(found)
    if declared is None:
        raise ReleaseError("terp release refuses this commit:\n" + "\n".join(f"- {r}" for r in refused))
    profile, problems = resolve_profile(root, declared)
    refused.extend(problem.message for problem in problems)
    services = {
        name: service for name, service in services_of(profile).items() if not service.get("profiles")
    }
    images, datastores = _images(root, declared, services, table, refused)
    step, api = _steps(declared, services, refused)
    _health(declared, services, refused)
    if refused:
        raise ReleaseError("terp release refuses this commit:\n" + "\n".join(f"- {r}" for r in refused))
    return Plan(declared, profile, services, images, step, api, datastores)


__all__ = ["Image", "Plan", "argv", "release_plan"]
