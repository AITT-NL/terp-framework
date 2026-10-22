"""``deployment.json`` written from the production profile an undeclared app already has.

ADR 0184 decision 1 keeps every app rendered before the declaration existed undeclared
through every framework update; it is declared only by a deliberate step. This is that
step's reading half (ADR 0187 decision 4, ``terp deployment adopt --build own``): it reads
``docker-compose.prod.yml`` and writes down what the profile itself says, so the truth rule
holds the result by construction, and the person reviews the diff before committing it.

What a service becomes, read from the profile and nothing else:

* a service on an image the datastore table carries (by repository) is a ``kind`` unit of
  the table's role and the version its tag names. A tag moves, and the truth rule requires
  exactly the table's digest, so its ``image:`` is pinned to the table's image in the same
  change. A version the table does not carry, or a digest that names none, is refused.
* a service built from the checkout, or on an image another service builds, is a unit:
  ``web`` when its build reads ``frontend/``; ``one-shot`` when it does not restart;
  ``worker`` and ``scheduler`` when it runs ``terp jobs worker`` or ``terp jobs
  scheduler``; ``api`` when it runs the backend image's own command, with the framework's
  own health routes (ADR 0024); and otherwise its own name as the role, which no tool
  looks up. A command is restated unless it is what the generator renders for that role
  by default, so the same declaration also renders; ``dependsOn`` is restated, restricted
  to the declared units.
* a service on an image neither built here nor in the table is refused by name: no
  declaration may name a registry, and ``--unmanaged "<reason>"`` is the way out.
* a named volume a declared unit mounts that no stateful unit owns is a volume, with its
  mount restated where every declared unit mounts it at one path inside ``var/``.

What a profile cannot say is left out and noted: a backup policy, ``env``, sizes, the
rollback strategy. A service that runs only under a compose profile is not declared.
"""

from __future__ import annotations

import pathlib
import posixpath
import re
import shlex
from dataclasses import dataclass, field
from typing import Any

from terp.arch.deployment import (
    DEPLOYMENT_FILE,
    Declaration,
    DatastoreTable,
    Finding,
    compose_literal,
    mounters,
    read,
    resolve_profile,
    services_of,
)
from terp.arch.deployment.datastores import Datastore, parse_image
from terp.arch.deployment.generator import APP_ROOT, DEFAULT_COMMANDS, MIGRATION_STEP, PROFILE
from terp.arch.deployment.profile import (
    as_mapping,
    build_path_findings,
    profile_from_text,
    truth_findings,
)

#: The framework's own health routes (ADR 0024), which every Terp API serves.
HEALTH_PATH = "/health/ready"
LIVENESS_PATH = "/health/live"

#: A role word the schema admits; a service name that is not one cannot stand as a role.
_ROLE = re.compile(r"[a-z][a-z0-9-]{0,31}")

#: An ``image:`` line, as a compose file writes one.
_IMAGE_LINE = re.compile(
    r"^(?P<lead>[ \t]*image:[ \t]*)(?P<quote>[\"']?)(?P<image>[^\s\"'#]+)(?P=quote)"
    r"(?P<tail>[ \t]*(?:#.*)?)$",
    re.MULTILINE,
)

#: The comment the written declaration carries.
COMMENT = (
    "How this app is deployed, for the tools that deploy it (ADR 0184). Written by `terp "
    "deployment adopt --build own` from docker-compose.prod.yml, which owns every fact "
    "restated here: change the profile, then this file, and `terp verify --only deployment` "
    "holds the two to each other. A backup policy, env names, sizes and a rollback strategy "
    "are not in a profile, so they are yours to add. See `terp guide deployment`."
)


class DeclareRefused(Exception):
    """The profile says something no declaration can write down truthfully."""


@dataclass
class Declared:
    """What adoption would write for an undeclared app."""

    raw: dict[str, Any]
    #: The profile's text with a datastore pinned to the table, or ``None`` when unchanged.
    profile: str | None
    notes: list[str] = field(default_factory=list)


def _argv(command: Any) -> tuple[str, ...] | None:
    """The command compose runs as literal arguments, or ``None`` when it interpolates."""
    if isinstance(command, list):
        parts = [compose_literal(str(part)) for part in command]
        literal = [part for part in parts if part is not None]
        return tuple(literal) if len(literal) == len(parts) else None
    text = compose_literal(str(command))
    return None if text is None else tuple(shlex.split(text))


def _datastore(name: str, image: Any, entries: list[Datastore]) -> Datastore:
    """The table entry a service's image names, or refused by name."""
    pinned = [entry for entry in entries if entry.pinned_by(image)]
    if pinned:
        return pinned[0]
    parsed = parse_image(str(image))
    tag = (parsed.tag if parsed is not None else None) or ""
    for entry in entries:
        if tag == entry.version or tag.startswith((f"{entry.version}-", f"{entry.version}.")):
            return entry
    offered = ", ".join(f"{entry.kind} {entry.version}" for entry in entries)
    raise DeclareRefused(
        f'service "{name}" runs {image}, whose version the datastore table does not carry '
        f"(allowed: {offered}, by a tag naming the version or by the table's digest)"
    )


def _reads_frontend(root: pathlib.Path, build: Any) -> bool:
    context = build if isinstance(build, str) else str(build.get("context", "."))
    dockerfile = None if isinstance(build, str) else build.get("dockerfile")
    frontend = (root / "frontend").resolve()
    paths = [(root / context).resolve()]
    if isinstance(dockerfile, str):
        paths.append((root / context / dockerfile).resolve())
    return any(path == frontend or path.is_relative_to(frontend) for path in paths)


def _built_unit(
    root: pathlib.Path, name: str, service: dict[str, Any], build: Any, notes: list[str]
) -> dict[str, Any] | None:
    """A unit built from the checkout, its role read from what the profile says it does."""
    command = service.get("command")
    argv = None if command is None else _argv(command)
    default: tuple[str, ...] | None = None
    if _reads_frontend(root, build):
        role = "web"
    elif service.get("restart") in ("no", False):
        role, default = "one-shot", MIGRATION_STEP
    elif argv is not None and argv[:2] == ("terp", "jobs") and argv[2:3] in (
        ("worker",),
        ("scheduler",),
    ):
        role = argv[2]
        default = DEFAULT_COMMANDS[role]
    elif command is None:
        role = "api"
    elif _ROLE.fullmatch(name):
        role = name
    else:
        notes.append(
            f"{name} is not declared: what it does cannot be read from the profile, and its "
            "name is not a role word (lower-case letters, digits and -); declare it yourself"
        )
        return None
    unit: dict[str, Any] = {"id": name, "role": role}
    if command is not None and argv is None:
        notes.append(f"{name}'s command interpolates a variable, so it is not restated")
    elif argv is not None and argv != default:
        unit["command"] = list(argv)
    if role == "api":
        unit["healthPath"], unit["livenessPath"] = HEALTH_PATH, LIVENESS_PATH
    return unit


def _builders(services: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Image name -> the build that makes it, from the service that declares the build."""
    return {
        service["image"]: service["build"]
        for service in services.values()
        if "build" in service and isinstance(service.get("image"), str)
    }


def _relative(target: str) -> str:
    normal = posixpath.normpath(target)
    return normal.removeprefix(f"{APP_ROOT}/")


def _volumes(
    profile: dict[str, Any],
    services: dict[str, dict[str, Any]],
    units: list[dict[str, Any]],
    notes: list[str],
) -> list[dict[str, Any]]:
    named = profile.get("volumes") if isinstance(profile.get("volumes"), dict) else {}
    ids = [unit["id"] for unit in units]
    stateful = {unit["id"] for unit in units if unit.get("stateful")}
    mounted = mounters(services)
    volumes: list[dict[str, Any]] = []
    for volume in named:
        users = [(name, target) for name, target in mounted.get(volume, ()) if name in ids]
        if not users or {service for service, _target in users} <= stateful:
            continue
        entry: dict[str, Any] = {"id": volume}
        paths = {_relative(target) for _service, target in users}
        (path,) = paths if len(paths) == 1 else (None,)
        if path is not None and re.fullmatch(r"var(/[A-Za-z0-9][A-Za-z0-9._-]*)+", path):
            order = sorted({service for service, _target in users}, key=ids.index)
            entry["mount"] = {"path": path, "units": order}
        else:
            notes.append(
                f"volume {volume}'s mount is not restated: the declared units mount it at "
                f"{', '.join(sorted(paths))}, not at one path inside var/"
            )
        notes.append(f"volume {volume} declares no backup policy; add one if it holds state")
        volumes.append(entry)
    return volumes


def _pin(text: str, images: dict[str, str]) -> str:
    """The profile's text with every ``image:`` line in *images* moved to its table image."""

    def replace(match: re.Match[str]) -> str:
        image = match.group("image")
        if image not in images:
            return match.group(0)
        return f"{match.group('lead')}{images[image]}{match.group('tail')}"

    return _IMAGE_LINE.sub(replace, text)


def derive(project_root: pathlib.Path, table: DatastoreTable) -> Declared:
    """The declaration the profile at *project_root* states, or :class:`DeclareRefused`."""
    shell = Declaration(build="own", compose_file=PROFILE, compose_overrides=(), units=())
    profile, problems = resolve_profile(project_root, shell)
    if problems:
        raise DeclareRefused(
            f"{problems[0].message.replace('compose.file ', '', 1)}. Adoption writes "
            f"{DEPLOYMENT_FILE} from the production profile, {PROFILE}: write the file by hand "
            "for a profile of another name, or declare the app unmanaged."
        )
    services = services_of(profile)
    builders = _builders(services)
    notes: list[str] = []
    units: list[dict[str, Any]] = []
    refused: list[str] = []
    pins: dict[str, str] = {}
    for name, service in services.items():
        if service.get("profiles"):
            notes.append(f"{name} is not declared: it runs only under a compose profile")
            continue
        image = service.get("image")
        entries = [entry for entry in table.entries if entry.runs_its_repository(image)]
        if entries:
            entry = _datastore(name, image, entries)
            if not entry.pinned_by(image):
                pins[str(image)] = entry.image
            units.append(
                {"id": name, "role": entry.role, "kind": entry.kind, "version": entry.version,
                 "stateful": True}
            )
            notes.append(f"{name} is stateful and declares no backup policy; add one")
            continue
        build = service["build"] if "build" in service else builders.get(image)
        if build is None:
            refused.append(f'service "{name}" runs {image or "no image"}')
            continue
        unit = _built_unit(project_root, name, service, build, notes)
        if unit is not None:
            units.append(unit)
    if refused:
        raise DeclareRefused(
            f"{'; '.join(refused)}, which no service of {PROFILE} builds from the checkout and "
            f"the datastore table does not carry ({table.describe() or 'nothing'}). A "
            "declaration names no registry: build it here, run a table image, or declare the "
            'app unmanaged with `terp deployment adopt --unmanaged "<reason>"`.'
        )
    if not units:
        raise DeclareRefused(f"{PROFILE} runs no service a declaration could name.")
    ids = [unit["id"] for unit in units]
    for unit in units:
        started = as_mapping(services[unit["id"]].get("depends_on"))
        order = [name for name in started if name in ids]
        if order:
            unit["dependsOn"] = order
    raw: dict[str, Any] = {
        "$comment": COMMENT,
        "schemaVersion": 1,
        "build": "own",
        "compose": {"file": PROFILE},
        "units": units,
    }
    volumes = _volumes(profile, services, units, notes)
    if volumes:
        raw["volumes"] = volumes
    text = (project_root / PROFILE).read_text(encoding="utf-8")
    pinned = _pin(text, pins) if pins else None
    _hold(project_root, raw, profile, pinned, table)
    return Declared(raw, pinned, notes)


def _hold(
    project_root: pathlib.Path,
    raw: dict[str, Any],
    profile: dict[str, Any],
    pinned: str | None,
    table: DatastoreTable,
) -> None:
    """Refuse a declaration its own checks would refuse: adoption never writes a red file."""
    declared, findings = read(raw, table)
    if isinstance(declared, Declaration):
        if pinned is not None:
            profile, findings = profile_from_text(pinned, PROFILE)
        findings = findings or [
            *build_path_findings(project_root, declared, profile),
            *truth_findings(project_root, declared, table, profile),
        ]
    if findings:
        raise DeclareRefused(
            "the declaration read from the profile would not hold against it, so nothing is "
            "written:\n  " + "\n  ".join(_line(finding) for finding in findings)
        )


def _line(finding: Finding) -> str:
    return f"{finding.message} {finding.remedy}".strip()


__all__ = ["COMMENT", "Declared", "DeclareRefused", "HEALTH_PATH", "LIVENESS_PATH", "derive"]
