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
  or a target is a part of the image nobody signs;
* a web image with no npm lock beside its Dockerfile or in its build context: its SBOM is read
  from the lock it installs, and one read from nothing would list no package.

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
from terp.cli.release import _npm_lock
from terp.cli.release._common import ReleaseError
from terp.cli.release._git import Tree
from terp.cli.release._locks import (
    NPM_LOCKS,
    UV_LOCK,
    npm_packages,
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
    #: The npm lock a web image installs, which its SBOM reads: the one its Dockerfile
    #: copies, else the one beside it or at the root of its context (:func:`npm_lock_of`);
    #: none for any other image.
    npm_lock: str | None = None


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

    @property
    def npm_locks(self) -> tuple[str, ...]:
        """Every npm lock a planned image is built from, each once, sorted: what the manifest records."""
        return tuple(sorted({image.npm_lock for image in self.images if image.npm_lock is not None}))


def argv(command: Any) -> tuple[str | None, ...] | None:
    """A profile command, element by element as compose runs it; ``None`` marks interpolation."""
    if isinstance(command, list):
        return tuple(compose_literal(str(part)) for part in command)
    if isinstance(command, str):
        literal = compose_literal(command)
        return (None,) if literal is None else tuple(shlex.split(literal))
    return None


def _relative(root: pathlib.Path, base: pathlib.Path, written: str) -> str | None:
    """*written*, relative to *base*, as a path relative to *root*, or ``None`` outside it.

    Being readable refuses a declared unit's build path that resolves outside the checkout, but
    it reads no service the declaration does not name, so the plan asks again for every build.
    """
    try:
        return (base / written).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


class _WorkingTree:
    """A project's files on disk, asked what the plan asks a commit's tree: whether a path is a file."""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root

    def has(self, path: str) -> bool:
        return (self.root / path).is_file()

    def read_text(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")


def npm_lock_of(tree: Tree | _WorkingTree, context: str, dockerfile: str) -> str | None:
    """The npm lock a web image installs, or ``None`` when none can be named.

    The one its Dockerfile copies from the build context; when the Dockerfile names none,
    the one beside it or at the root of its context, and never a choice between two
    (:func:`terp.cli.release._npm_lock.choose`). Read from where the image is built, never
    from a recipe, which only the generated state declares: under ``"build": "own"`` an app
    names none, and the image it builds a site from still installs a lock of its own. The
    generator's two web Dockerfiles copy the locks beside them (``frontend/`` and ``site/``,
    ADR 0198), so a generated app's images are planned with the locks they always were.
    """
    return _npm_lock.choose(tree, context, dockerfile)[0]


def web_packages(tree: Tree, image: Image) -> list[tuple[str, str]]:
    """``(name, version)`` of every package web *image* installs, read from its npm lock.

    Refused when the commit holds no such lock: an SBOM read from nothing lists no package,
    and ``sign`` would vouch that the image holds none.
    """
    if image.npm_lock is None or not tree.has(image.npm_lock):
        raise ReleaseError(
            f"the web image {image.name} has no npm lock in this commit, so its SBOM would list "
            "no package, and sign does not vouch for an image it cannot describe: commit the "
            "package-lock.json the image installs, beside its Dockerfile or at the root of its "
            "build context"
        )
    return npm_packages(read_npm_lock(tree.read_text(image.npm_lock), image.npm_lock))


def _npm_path_refusals(tree: Tree, npm_lock: str) -> list[str]:
    return [
        f"{npm_lock} takes {source} from a path, which a pristine context does not hold"
        for source in npm_path_sources(read_npm_lock(tree.read_text(npm_lock), npm_lock))
    ]


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
    for npm_lock in NPM_LOCKS:
        if tree.has(npm_lock):
            refused.extend(_npm_path_refusals(tree, npm_lock))
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
    written = str(build.get("context", ".")), str(build.get("dockerfile", "Dockerfile"))
    context = _relative(root, base, written[0])
    # Against the context, as compose resolves it. *context* is already relative to the
    # checkout, so it is joined to that and not to the profile's own directory again: for a
    # profile in a subdirectory the two differ, and the plan named a Dockerfile compose would
    # never build from.
    dockerfile = _relative(root, root / context, written[1]) if context is not None else None
    if context is None or dockerfile is None:
        outside = "context" if context is None else "Dockerfile"
        refused.append(
            f"service {name} builds from {written[0]!r} with the Dockerfile {written[1]!r}, and its "
            f"{outside} resolves outside the checkout: a release builds from the commit's own files "
            "alone (allowed: a build context and a Dockerfile inside the checkout)"
        )
        return None
    return tagged.group("name"), context, dockerfile


def _images(
    tree: Tree | _WorkingTree,
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
    images = []
    for image, (_builder, context, dockerfile) in sorted(builds.items()):
        run = runners.get(image, [])
        web = bool(webs & set(run))
        lock, why = _npm_lock.choose(tree, context, dockerfile) if web else (None, None)
        if why is not None:
            refused.append(f"the web image {image} has no npm lock a release can read: {why}")
        images.append(Image(image, context, dockerfile, tuple(run), web, lock))
    return tuple(images), datastores


def planned_images(root: pathlib.Path, table: DatastoreTable) -> tuple[Image, ...] | None:
    """The images the release plan builds for the declared app at *root*, asked of the files on disk.

    The plan's own images and rule, so ``terp verify``'s locks check, npm audit and ``terp
    maintenance`` hold the Dockerfiles and the locks a release reads rather than a list of
    their own. ``None`` for an app that is undeclared, unmanaged or unreadable, or whose
    profile cannot be read: a release refuses it, and each caller says what it holds instead.
    """
    declared, findings = readable(root, table)
    if findings or not isinstance(declared, Declaration):
        return None
    profile, problems = resolve_profile(root, declared)
    if problems:
        return None
    services = {
        name: service for name, service in services_of(profile).items() if not service.get("profiles")
    }
    images, _datastores = _images(_WorkingTree(root), root, declared, services, table, [])
    return tuple(images)


def web_npm_locks(root: pathlib.Path, table: DatastoreTable) -> tuple[str, ...]:
    """The npm locks the release plan reads for the web images of the declared app at *root*.

    :func:`planned_images`' locks. Nothing for an app whose plan cannot be read: the gate
    then holds the generator's two locks (:data:`~terp.cli.release._locks.NPM_LOCKS`) where
    their manifest is, as before.
    """
    images = planned_images(root, table) or ()
    return tuple(sorted({image.npm_lock for image in images if image.npm_lock is not None}))


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
    images, datastores = _images(tree, root, declared, services, table, refused)
    # The tree's refusals read the two locks the generator knows; a lock an image is built from
    # anywhere else is held to the same rule here.
    for lock in sorted({image.npm_lock for image in images if image.npm_lock is not None} - set(NPM_LOCKS)):
        refused.extend(_npm_path_refusals(tree, lock))
    step, api = _steps(declared, services, refused)
    _health(declared, services, refused)
    if refused:
        raise ReleaseError("terp release refuses this commit:\n" + "\n".join(f"- {r}" for r in refused))
    return Plan(declared, profile, services, images, step, api, datastores)


__all__ = ["Image", "Plan", "argv", "npm_lock_of", "planned_images", "release_plan", "web_npm_locks", "web_packages"]
