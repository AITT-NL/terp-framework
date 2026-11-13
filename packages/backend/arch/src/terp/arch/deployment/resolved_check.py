"""What a reader refuses in a resolved deployment: its schema, and what the schema cannot state.

``sign`` runs :func:`refusals_for` on the document the commit's own ``terp-arch`` wrote, with
its own ``terp-arch``, and signs nothing it refuses. ``resolved-deployment.schema.json`` ships
here byte for byte, read by the small validator (:mod:`._jsonschema`), so the schema's words
are applied rather than restated, and the lists the checks below use are read from its
``$defs``. terp-spec's ``resolved-deployment`` fixtures are the cases every reader runs: this
repository's tests carry them and run every one through :func:`refusals`.

What the schema's keyword subset cannot state is checked against the release that carries
the document: ids, names, targets and units each once and in their order, every reference
resolving, and agreement with the declared units, the built images and the datastore table.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Mapping, Sequence
from typing import Any

from terp.arch.deployment import _jsonschema
from terp.arch.deployment.datastores import DatastoreTable
from terp.arch.deployment.model import Declaration

#: The schema, beside this module in the wheel.
SCHEMA_FILE = "resolved-deployment.schema.json"

#: The terp-spec release whose ``resolved-deployment.schema.json`` this copy must equal byte
#: for byte once that release is pinned.
SPEC_RELEASE = "0.48.0"


def _load() -> dict[str, Any]:
    raw = json.loads(pathlib.Path(__file__).with_name(SCHEMA_FILE).read_text(encoding="utf-8"))
    _jsonschema.check_schema(raw)
    return raw


#: The schema, parsed once and checked against the validator's keyword subset on load, so a
#: later schema with a constraint this reader cannot apply fails here, loudly.
SCHEMA: dict[str, Any] = _load()

#: Variable names a release never sets, and prefixes it never starts one with: the executor
#: owns them. The schema's lists, never restated.
REFUSED_NAMES: frozenset[str] = frozenset(SCHEMA["$defs"]["refusedEnvironmentNames"]["enum"])
REFUSED_PREFIXES: tuple[str, ...] = tuple(SCHEMA["$defs"]["refusedEnvironmentPrefixes"]["enum"])


def _field(problem: _jsonschema.Problem) -> str:
    """The field a schema problem is about, written as the fixtures write one (``$`` first).

    A repeated item is named at its own index, the second time it occurs.
    """
    path = problem.path
    if problem.keyword == "uniqueItems" and problem.values:
        path = _jsonschema._join(path, problem.values[0])
    return "$" if not path else f"$.{path}" if not path.startswith("[") else f"${path}"


def refusals(
    document: object,
    *,
    units: Sequence[tuple[str, str, str | None, str | None]],
    images: Sequence[str],
    datastores: Mapping[tuple[str, str], str],
) -> list[tuple[str, str]]:
    """``(field, why)`` for every refusal of *document*: the schema's, then :func:`consistency`'s."""
    found = [(_field(problem), problem.detail) for problem in _jsonschema.validate(document, SCHEMA)]
    return found + consistency(document, units=units, images=images, datastores=datastores)


def refusals_for(
    document: object, declaration: Declaration, *, table: DatastoreTable, images: Sequence[str]
) -> list[tuple[str, str]]:
    """:func:`refusals` against the release that carries *document*: its declared units, its
    datastore table and the images it built, by digest."""
    return refusals(
        document,
        units=[(unit.id, unit.role, unit.kind, unit.version) for unit in declaration.units],
        images=images,
        datastores={(entry.kind, entry.version): entry.image for entry in table.entries},
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _items(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def consistency(
    document: object,
    *,
    units: Sequence[tuple[str, str, str | None, str | None]],
    images: Sequence[str],
    datastores: Mapping[tuple[str, str], str],
) -> list[tuple[str, str]]:
    """``(field, what it allows)`` for every refusal of *document* beyond its schema.

    What a schema cannot state, read against the release that carries the document: ids,
    names, targets and units each once and in their order, every reference resolving, and the
    document agreeing with the declared *units* (``(id, role, kind, version)``), the built
    *images* and the *datastores* table (``(kind, version)`` to image). terp-spec's fixtures
    name the same fields. A document of any shape is read, each check looking only at what it
    can read, so a value of the wrong type is refused by the schema and never raises here.
    """
    if not isinstance(document, dict):
        return []
    found: list[tuple[str, str]] = []
    services = [(i, s) for i, s in enumerate(_items(document.get("services"))) if isinstance(s, dict)]
    declared = {ident: (role, kind, version) for ident, role, kind, version in units}
    order = [ident for ident, _, _, _ in units]
    by_id: dict[str, dict[str, Any]] = {}
    for index, service in services:
        ident = _text(service.get("id"))
        if ident is None:
            continue
        if ident in by_id:
            found.append((f"$.services[{index}].id", "each declared unit once"))
        elif ident not in declared:
            found.append((f"$.services[{index}].id", f"a declared unit: {', '.join(order)}"))
        by_id.setdefault(ident, service)
    missing = [ident for ident in order if ident not in by_id]
    if missing:
        found.append(("$.services", f"one service per declared unit - {', '.join(missing)} has none"))
    placed = [(i, ident) for i, s in services if (ident := _text(s.get("id"))) in declared]
    for (_, before), (index, ident) in zip(placed, placed[1:]):
        if order.index(ident) <= order.index(before):
            found.append((f"$.services[{index}].id", f"the declared units in the declaration's order: {', '.join(order)}"))
            break
    volumes = [name for name in _items(document.get("volumes")) if isinstance(name, str)]
    for position in range(1, len(volumes)):
        if volumes[position] <= volumes[position - 1]:
            found.append((f"$.volumes[{position}]", "each named volume once, in ascending order"))
    mounted: set[str] = set()
    for index, service in services:
        found += _service_findings(index, service, declared, images, datastores, volumes, mounted, by_id)
    for position, name in enumerate(volumes):
        if name not in mounted:
            found.append((f"$.volumes[{position}]", "only the named volumes a service mounts"))
    found += _cycle_findings(services, by_id)
    migration = document.get("migration")
    if isinstance(migration, str):
        target = by_id.get(migration)
        if target is None or target.get("lifecycle") != "one-shot":
            one_shots = [ident for ident, s in by_id.items() if s.get("lifecycle") == "one-shot"]
            found.append(("$.migration", f"a one-shot service of this document: {', '.join(one_shots) or 'none'}"))
        else:
            index = next(i for i, s in services if s is target)
            if "command" in target:
                found.append((f"$.services[{index}].command", "no command: the executor owns the migration step's argv"))
            for position, entry in enumerate(_items(target.get("environment"))):
                if isinstance(entry, dict) and entry.get("source") == "database":
                    found.append(
                        (f"$.services[{index}].environment[{position}].source",
                         "config, secret or value: the executor gives the migration step its connection itself")
                    )
    return found


def _service_findings(
    index: int,
    service: dict[str, Any],
    declared: Mapping[str, tuple[str, str | None, str | None]],
    images: Sequence[str],
    datastores: Mapping[tuple[str, str], str],
    volumes: Sequence[str],
    mounted: set[str],
    by_id: Mapping[str, dict[str, Any]],
) -> list[tuple[str, str]]:
    at = f"$.services[{index}]"
    found: list[tuple[str, str]] = []
    unit = declared.get(_text(service.get("id")) or "")
    if unit is not None:
        role, declared_kind, declared_version = unit
        if "role" in service and service["role"] != role:
            found.append((f"{at}.role", f"{role}, the declared unit's role"))
        wanted = (
            {"kind": declared_kind, "version": declared_version} if declared_kind is not None else None
        )
        if service.get("datastore") != wanted:
            allowed = f"{declared_kind} {declared_version}, the unit's kind and version"
            found.append((f"{at}.datastore", allowed if wanted else "no datastore: the unit declares no kind"))
    image, store = _text(service.get("image")), service.get("datastore")
    if image is not None:
        if isinstance(store, dict):
            kind, version = _text(store.get("kind")), _text(store.get("version"))
            if kind is not None and version is not None and datastores.get((kind, version)) != image:
                found.append((f"{at}.image", f"the datastore table's reference for {kind} {version}"))
        elif image not in images:
            found.append((f"{at}.image", "one of the release's built images, by digest"))
    names: list[str] = []
    for position, entry in enumerate(_items(service.get("environment"))):
        name = _text(entry.get("name")) if isinstance(entry, dict) else None
        if name is None:
            continue
        field = f"{at}.environment[{position}].name"
        if names and name <= names[-1]:
            found.append((field, "names in ascending order, each once"))
        names.append(name)
        if name in REFUSED_NAMES:
            found.append((field, "a name the executor does not own (refusedEnvironmentNames)"))
        elif name.startswith(REFUSED_PREFIXES):
            found.append((field, "a name with no refused prefix (refusedEnvironmentPrefixes)"))
    targets: list[str] = []
    for position, mount in enumerate(_items(service.get("mounts"))):
        if not isinstance(mount, dict):
            continue
        target = _text(mount.get("target"))
        if target is not None:
            if targets and target <= targets[-1]:
                found.append((f"{at}.mounts[{position}].target", "targets in ascending order, each once"))
            targets.append(target)
        source = _text(mount.get("source"))
        if mount.get("type") == "volume" and source is not None:
            mounted.add(source)
            if source not in volumes:
                found.append((f"{at}.mounts[{position}].source", "a named volume listed in volumes"))
    after: list[str] = []
    for position, entry in enumerate(_items(service.get("after"))):
        other = _text(entry.get("unit")) if isinstance(entry, dict) else None
        if other is None:
            continue
        field = f"{at}.after[{position}]"
        if after and other <= after[-1]:
            found.append((f"{field}.unit", "units in ascending order, each once"))
        after.append(other)
        if other == service.get("id") or other not in by_id:
            found.append((f"{field}.unit", "a service of this document other than this one"))
            continue
        target = by_id[other]
        if entry.get("condition") == "completed" and target.get("lifecycle") != "one-shot":
            found.append((f"{field}.condition", "started or healthy: completed waits for a one-shot unit"))
        if entry.get("condition") == "healthy" and "healthcheck" not in target:
            found.append((f"{field}.condition", "started or completed: healthy waits for a unit with a healthcheck"))
    return found


def _cycle_findings(
    services: Sequence[tuple[int, dict[str, Any]]], by_id: Mapping[str, dict[str, Any]]
) -> list[tuple[str, str]]:
    def waits_for(service: dict[str, Any]) -> list[str]:
        return [
            unit for entry in _items(service.get("after"))
            if isinstance(entry, dict) and (unit := _text(entry.get("unit"))) in by_id
        ]

    def reaches(start: str, goal: str) -> bool:
        stack, seen = [start], set()
        while stack:
            current = stack.pop()
            if current == goal:
                return True
            if current not in seen:
                seen.add(current)
                stack.extend(waits_for(by_id[current]))
        return False

    found = []
    for index, service in services:
        ident = _text(service.get("id"))
        if ident is None or by_id.get(ident) is not service:
            continue
        for position, entry in enumerate(_items(service.get("after"))):
            other = _text(entry.get("unit")) if isinstance(entry, dict) else None
            if other is not None and other in by_id and other != ident and reaches(other, ident):
                found.append(
                    (f"$.services[{index}].after[{position}].unit",
                     "a unit that does not wait, directly or through others, for this service")
                )
    return found


__all__ = [
    "REFUSED_NAMES",
    "REFUSED_PREFIXES",
    "SCHEMA",
    "SCHEMA_FILE",
    "SPEC_RELEASE",
    "consistency",
    "refusals",
    "refusals_for",
]
