"""``deployment.json`` — the app's deploy declaration, and the typed reader for it.

A tool that deploys a Terp app has to know which units exist, which one serves the API,
how to tell each is healthy, which migration histories each owns, what holds state and
how it is backed up, and what a rollback is. Assuming the template's four service names
answers that until the day an app adds a worker. ``deployment.json`` at the project root
says it instead (ADR 0184).

**The words are the Terp Standard's.** The schema is
``deployment-declaration.schema.json`` in terp-spec, and this package ships a
byte-for-byte mirror of it beside this module. The reader applies that mirror
(:mod:`terp.arch.deployment._jsonschema`) rather than restating its rules, so the two
cannot drift, and adds only what a schema cannot state: the vocabularies the schema
names in ``$defs``, the datastore table, unique ids, a ``size`` that points into
``sizes``, and the paths.

**Fail closed on the whole file.** A key this vocabulary does not have is refused at any
level, because a misspelt ``stateful`` would otherwise be a policy that silently does
nothing; a ``$``-prefixed key is an annotation and is exempt. A deploy-policy key gets
its own message. A file in no state or in two (``units`` without ``build``,
``unmanaged`` beside ``build``) is refused, never guessed into one. An absent file is
undeclared and passes.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import pathlib
from typing import Any

from terp.arch.deployment import _jsonschema, _words
from terp.arch.deployment.model import (
    DEPLOYMENT_FILE,
    Backup,
    Declaration,
    Finding,
    Mount,
    Unit,
    Unmanaged,
    Volume,
)
from terp.arch.deployment.datastores import DatastoreTable
from terp.arch.deployment.tables import SystemPackageTable, published_system_packages

#: The schema mirror, beside this module in the wheel.
SCHEMA_FILE = "deployment-declaration.schema.json"

#: The terp-spec release whose ``deployment-declaration.schema.json`` this mirror must
#: equal byte for byte once that release is pinned
#: (``tests/architecture/test_deployment_schema_mirror.py``).
SPEC_RELEASE = "0.46.0"

#: Versions this reader understands. A later file means the toolchain is behind, and
#: saying so beats reading it with an earlier vocabulary.
SUPPORTED_VERSIONS = frozenset({1})

#: The development compose file of an app whose ``workbench.json`` names none.
DEV_COMPOSE_FILE = "docker-compose.yml"

#: The health path the image each recipe builds answers itself, by the recipe ``generator.recipes``
#: names (ADR 0198). A recipe takes no parameters, so its server answers there and nowhere
#: else, and the profile probes it there; a deploy tool waits on the ``healthPath`` the unit
#: declares, so a unit that names the recipe declares that path or none. Every recipe the
#: schema allows has an entry (``test_deployment_static_site``).
RECIPE_HEALTH_PATHS = {"static-site": "/healthz"}

#: Keys that put a file in a declared state; any of them beside ``unmanaged`` is two.
_DECLARED_KEYS = (
    "build",
    "compose",
    "units",
    "volumes",
    "sizes",
    "externalDatabase",
    "rollback",
    "generator",
)

#: The message every reader gives a deploy-policy key, from the schema's own ``$defs``.
POLICY_MESSAGE = (
    "{path} is deploy policy: it belongs to the deploying tool's environment policy, "
    "not to this file"
)


#: A unit field's name in the file -> its attribute on :class:`Unit`. Held to the
#: schema's unit properties by the mirror's parity test, so a field the schema adds
#: cannot be read as absent here.
UNIT_FIELDS = {
    "id": "id",
    "role": "role",
    "kind": "kind",
    "version": "version",
    "command": "command",
    "healthPath": "health_path",
    "livenessPath": "liveness_path",
    "migrations": "migrations",
    "env": "env",
    "dependsOn": "depends_on",
    "instances": "instances",
    "size": "size",
    "stateful": "stateful",
    "backup": "backup",
}


@functools.cache
def schema() -> dict[str, Any]:
    """The mirrored schema, refused outright if it asks for what the reader cannot apply."""
    loaded = json.loads(pathlib.Path(__file__).with_name(SCHEMA_FILE).read_text("utf-8"))
    _jsonschema.check_schema(loaded)
    return loaded


def _vocabulary(name: str) -> tuple[str, ...]:
    return tuple(schema()["$defs"][name]["enum"])


def deploy_policy_keys() -> tuple[str, ...]:
    """Keys refused with their own message: deploy policy never lives in a commit."""
    return _vocabulary("deployPolicyKeys")


def known_roles() -> tuple[str, ...]:
    """The role words the vocabulary knows; any other role is information."""
    return _vocabulary("knownRoles")


def role_resolved_fields() -> tuple[str, ...]:
    """Unit fields a reader resolves by role, which an unknown role leaves unread."""
    return _vocabulary("roleResolvedFields")


def _entries(raw: dict[str, Any], key: str) -> list[tuple[str, dict[str, Any]]]:
    value = raw.get(key)
    if not isinstance(value, list):
        return []
    return [
        (f"{key}[{index}]", entry) for index, entry in enumerate(value) if isinstance(entry, dict)
    ]


def _state_findings(raw: dict[str, Any]) -> list[tuple[str, Finding]]:
    """A file in no state or in two: refused as a whole, never guessed into one."""
    if "unmanaged" in raw and raw["unmanaged"] is not True:
        return [
            (
                "",
                Finding(
                    f"unmanaged is {json.dumps(raw['unmanaged'])} (allowed: true, or leave the key out)"
                ),
            )
        ]
    if "unmanaged" in raw and any(key in raw for key in _DECLARED_KEYS):
        beside = ", ".join(key for key in _DECLARED_KEYS if key in raw)
        message = (
            f"unmanaged stands beside {beside}: a file is in exactly one state "
            "(allowed: beside unmanaged, only reason and schemaVersion)"
        )
        return [
            (
                "",
                Finding(
                    message,
                    'Either {"unmanaged": true, "reason": "..."} and nothing else, or a build with its units.',
                ),
            )
        ]
    if "units" in raw and "build" not in raw:
        return [
            (
                "build",
                Finding("build is required when units are declared (allowed: generated or own)"),
            )
        ]
    return []


def _shape_findings(raw: dict[str, Any], table: DatastoreTable) -> list[tuple[str, Finding]]:
    """The refusals that deserve their own words, each with the path it covers."""
    found = [
        (
            path,
            Finding(
                f"{POLICY_MESSAGE.format(path=path)} (allowed: nothing - "
                f"{POLICY_MESSAGE.format(path=_words.steps(path)[-1])})",
                "Remove the key: who may publish, how many approvals a deploy needs, who may reach a deployed app and which gate policy applies are set per environment, where a commit cannot lower them.",
            ),
        )
        for path in _words.policy_key_paths(raw, deploy_policy_keys())
    ]
    found.extend(_state_findings(raw))
    if raw.get("build") == "own" and "generator" in raw and "unmanaged" not in raw:
        found.append(
            (
                "generator",
                Finding(
                    'generator stands beside build "own": the generator\'s words are read only '
                    f'where build is "generated" (allowed: {_words.GENERATOR_BESIDE_OWN})',
                    'Drop the block, or declare "build": "generated" to have the framework '
                    "render the build files from this declaration.",
                ),
            )
        )
    for path, entry in [*_entries(raw, "units"), *_entries(raw, "volumes")]:
        if entry.get("backup") == "client":
            message = f'{path}.backup is "client", which is valid only on externalDatabase (allowed: {_words.FORMS["units[].backup"]})'
            found.append((f"{path}.backup", Finding(message)))
    for path, entry in _entries(raw, "units"):
        if "image" in entry:
            keys = ", ".join(sorted(UNIT_FIELDS))
            message = f"{path}.image is not a field of a unit (allowed: a unit's keys: {keys} - {_words.NO_SUCH_KEY['units[]', 'image']})"
            found.append(
                (
                    f"{path}.image",
                    Finding(
                        message, f"The datastore table offers: {table.describe() or 'nothing'}."
                    ),
                )
            )
        if isinstance(entry.get("command"), str):
            message = f"{path}.command is a shell string (allowed: an argument list of strings, never a shell string)"
            found.append(
                (
                    f"{path}.command",
                    Finding(
                        message,
                        'Write it as a list, ["terp", "jobs", "worker"]: each element is data, never shell.',
                    ),
                )
            )
    return found


def _version_finding(raw: dict[str, Any]) -> Finding | None:
    if "schemaVersion" not in raw:
        return None
    version = raw["schemaVersion"]
    if isinstance(version, int) and not isinstance(version, bool) and version in SUPPORTED_VERSIONS:
        return None
    allowed = ", ".join(map(str, sorted(SUPPORTED_VERSIONS)))
    return Finding(
        f"schemaVersion is {json.dumps(version)}, which this toolchain does not read (allowed: {allowed})",
        "Upgrade the Terp toolchain, or write the file in a version it knows.",
    )


def _covered(path: str, taken: list[str]) -> bool:
    return any(
        not prefix or path == prefix or path.startswith((f"{prefix}.", f"{prefix}["))
        for prefix in taken
    )


def read(
    raw: object, table: DatastoreTable, packages: SystemPackageTable | None = None
) -> tuple[Declaration | Unmanaged | None, list[Finding]]:
    """Read a parsed declaration as data: no filesystem, no app, no profile.

    ``(None, findings)`` when it cannot be read. A tool that must never execute the
    app's code needs nothing more than this to refuse a file. *packages* is the
    system-package table ``generator.systemPackages`` resolves against: this framework
    release's when none is given.
    """
    if not isinstance(raw, dict):
        return None, [
            Finding(
                f"{DEPLOYMENT_FILE} must contain one JSON object (allowed: one JSON object, not {_words.json_kind(raw)})"
            )
        ]
    version = _version_finding(raw)
    if version is not None:
        return None, [version]
    special = _shape_findings(raw, table)
    taken = [path for path, _ in special]
    if "generator" in taken:
        # The schema states the same refusal at build (a generator block asks for build
        # generated); the reader names the block, which is what the person removes.
        taken.append("build")
    problems = [
        Finding(_words.say(problem, raw, table.versions()))
        for problem in _jsonschema.validate(raw, schema())
        if not _covered(problem.path, taken)
    ]
    findings = [finding for _, finding in special] + problems
    if findings:
        return None, findings
    if "unmanaged" in raw:
        return Unmanaged(reason=raw["reason"].strip()), []
    declaration = _declaration(raw)
    offered = packages if packages is not None else published_system_packages()
    findings = _meaning_findings(declaration, table, offered)
    return (None, findings) if findings else (declaration, [])


def _backup(raw: object) -> Backup | None:
    return Backup(raw["every"], raw["keep"]) if isinstance(raw, dict) else None


def _mount(raw: object) -> Mount | None:
    return Mount(raw["path"], tuple(raw["units"])) if isinstance(raw, dict) else None


def _unit(raw: dict[str, Any]) -> Unit:
    return Unit(
        id=raw["id"],
        role=raw["role"],
        kind=raw.get("kind"),
        version=raw.get("version"),
        command=tuple(raw["command"]) if "command" in raw else None,
        health_path=raw.get("healthPath"),
        liveness_path=raw.get("livenessPath"),
        migrations=tuple(raw.get("migrations", ())),
        env=tuple(raw.get("env", ())),
        depends_on=tuple(raw["dependsOn"]) if "dependsOn" in raw else None,
        instances=raw.get("instances", "one"),
        size=raw.get("size"),
        stateful=raw.get("stateful", False),
        backup=_backup(raw.get("backup")),
    )


def _declaration(raw: dict[str, Any]) -> Declaration:
    compose = raw["compose"]
    return Declaration(
        build=raw["build"],
        compose_file=compose["file"],
        compose_overrides=tuple(compose.get("overrides", ())),
        units=tuple(_unit(entry) for entry in raw["units"]),
        volumes=tuple(
            Volume(entry["id"], _backup(entry.get("backup")), _mount(entry.get("mount")))
            for entry in raw.get("volumes", ())
        ),
        sizes=tuple(
            (name, float(size["cpu"]), int(size["memoryMiB"]))
            for name, size in sorted(raw.get("sizes", {}).items())
        ),
        rollback=raw.get("rollback", {}).get("strategy"),
        external_database="externalDatabase" in raw,
        system_packages=tuple(raw.get("generator", {}).get("systemPackages", ())),
        recipes=tuple(
            (ident, recipe)
            for ident, recipe in raw.get("generator", {}).get("recipes", {}).items()
            if not ident.startswith("$")
        ),
    )


def _duplicates(where: str, ids: list[str]) -> list[Finding]:
    seen: set[str] = set()
    found: list[Finding] = []
    noun = "unit" if where == "units" else "volume"
    for index, name in enumerate(ids):
        if name in seen:
            found.append(
                Finding(
                    f'{where}[{index}].id "{name}" is the id of an earlier {noun} (allowed: an id no other {noun} has)'
                )
            )
        seen.add(name)
    return found


def _meaning_findings(
    declaration: Declaration, table: DatastoreTable, packages: SystemPackageTable
) -> list[Finding]:
    """What the schema cannot state: the tables, and references within the file."""
    findings: list[Finding] = []
    findings.extend(_duplicates("units", [unit.id for unit in declaration.units]))
    findings.extend(_duplicates("volumes", [volume.id for volume in declaration.volumes]))
    sizes = [name for name, _cpu, _memory in declaration.sizes]
    offered = table.versions()
    for index, unit in enumerate(declaration.units):
        where = f"units[{index}]"
        if unit.size is not None and unit.size not in sizes:
            findings.append(
                Finding(
                    f'{where}.size is "{unit.size}", which sizes does not declare (allowed: a key of sizes: {", ".join(sizes) or "none"})'
                )
            )
        if unit.kind is not None and unit.kind not in offered:
            findings.append(
                Finding(
                    f'{where}.kind is "{unit.kind}", which the datastore table does not carry (allowed: a datastore kind of the table: {_words.or_join(sorted(offered)) or "none"})'
                )
            )
        elif unit.kind is not None and table.find(unit.kind, str(unit.version)) is None:
            findings.append(
                Finding(
                    f'{where}.version is "{unit.version}" for kind {unit.kind}, which the datastore table does not carry (allowed: a version the datastore table carries for {unit.kind}: {_words.or_join(sorted(offered[unit.kind]))})'
                )
            )
    ids = [unit.id for unit in declaration.units]
    for index, volume in enumerate(declaration.volumes):
        for position, ident in enumerate(volume.mount.units if volume.mount else ()):
            if ident not in ids:
                findings.append(
                    Finding(
                        f'volumes[{index}].mount.units[{position}] "{ident}" is no declared unit '
                        f"(allowed: a declared unit's id: {', '.join(sorted(ids))})"
                    )
                )
    listed = packages.packages
    for index, name in enumerate(declaration.system_packages):
        if name not in listed:
            findings.append(
                Finding(
                    f'generator.systemPackages[{index}] "{name}" is not in the system-package '
                    "table (allowed: a package of the system-package table: "
                    f"{', '.join(sorted(listed)) or 'none - this table carries no package'})",
                    "A system package waits for a measured need and a pinned source the table "
                    'records; until then, build this unit under "build": "own".',
                )
            )
    roles = {unit.id: unit.role for unit in declaration.units}
    webs = ", ".join(sorted(ident for ident, role in roles.items() if role == "web")) or "none"
    for ident, recipe in declaration.recipes:
        if roles.get(ident) != "web":
            found = f"unit {ident} has role {roles[ident]}" if ident in roles else f"no unit is {ident}"
            findings.append(
                Finding(
                    f'{_jsonschema._join("generator.recipes", ident)} names the recipe "{recipe}", '
                    f"which builds a web unit, and {found} (allowed: a declared web unit's id: {webs})"
                )
            )
    findings.extend(_recipe_health_findings(declaration))
    return findings


def _recipe_health_findings(declaration: Declaration) -> list[Finding]:
    """A web unit built from a recipe that declares a health path its image does not answer."""
    found: list[Finding] = []
    for index, unit in enumerate(declaration.units):
        recipe = declaration.recipe(unit.id)
        answered = RECIPE_HEALTH_PATHS.get(recipe or "")
        if unit.role != "web" or answered is None or unit.health_path in (None, answered):
            continue
        found.append(
            Finding(
                f'units[{index}].healthPath is "{unit.health_path}", and generator.recipes.{unit.id} '
                f'builds the unit with "{recipe}", whose image answers its health at {answered} '
                f"alone (allowed: {answered}, or no healthPath)",
                f'Declare "healthPath": "{answered}" or leave it out: a deploy tool waits on the '
                "path a unit declares, and the recipe's server answers no other.",
            )
        )
    return found


def _carries(unit: Unit, name: str) -> bool:
    attribute = UNIT_FIELDS[name]
    default = next(item.default for item in dataclasses.fields(Unit) if item.name == attribute)
    return getattr(unit, attribute) != default


def role_findings(declaration: Declaration) -> list[Finding]:
    """Rule 1's boundary: a field read by role, under a role nothing looks up."""
    return [
        Finding(
            f'units[{index}].{name} is declared under role "{unit.role}", which no reader '
            f"resolves (allowed: a role that resolves it: {_words.or_join(known_roles())})",
            "These fields are read by role, so under a role nobody looks up they are never read.",
        )
        for index, unit in enumerate(declaration.units)
        if unit.role not in known_roles()
        for name in role_resolved_fields()
        if _carries(unit, name)
    ]


__all__ = [
    "DEPLOYMENT_FILE",
    "RECIPE_HEALTH_PATHS",
    "SCHEMA_FILE",
    "SPEC_RELEASE",
    "Backup",
    "Declaration",
    "Finding",
    "Mount",
    "Unit",
    "Unmanaged",
    "Volume",
    "read",
    "role_findings",
]
