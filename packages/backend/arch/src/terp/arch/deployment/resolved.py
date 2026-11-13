"""The resolved deployment a generated release runs (terp-spec ``resolved-deployment``).

``sign`` writes it into the signed release manifest at ``outputs.deployment``, and a deploy
executor runs it instead of reading the profile: the services, each image by digest, each
command as an argv, the source of each variable, the mounts, the probes and the start order.
It holds nothing an executor or an environment owns: no restart policy, network, published
port, label, logging setting, hardening, resource or instance count.

It is built from the plan the profile is written from (:mod:`._compose`), never by reading
the profile, and the start conditions and probes come from the very helpers the profile is
written with, so the two cannot say different things about what runs. A test holds every
generator golden's profile and resolved deployment together field by field.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from terp.arch.deployment._compose import (
    DEFAULT_COMMANDS,
    _Plan,
    _plan,
    condition_of,
    probe_of,
)
from terp.arch.deployment._generator_text import (
    API_PORT,
    APP_ROOT,
    CORS_ORIGINS,
    KEY_SEAM,
    MOUNT_PATH,
    WEB_PORT,
)
from terp.arch.deployment._static_site import SITE_HEALTH_PATH
from terp.arch.deployment.model import Declaration, Unit
from terp.arch.deployment.tables import Tables

#: The version of the vocabulary this module writes.
SCHEMA_VERSION = 1

#: The port each tier listens on inside its container: the right half of the profile's port
#: scalar, which publishes it (a test holds the two together).
API_CONTAINER_PORT = int(API_PORT.rsplit(":", 1)[1])
WEB_CONTAINER_PORT = int(WEB_PORT.rsplit(":", 1)[1])

#: Where a declared volume is mounted, the files capability's storage root.
FILES_ROOT = f"{APP_ROOT}/{MOUNT_PATH}"

_TIMING_LINE = re.compile(r"(interval|timeout|retries|start_period): (\d+)s?")
_TIMING_FIELDS = {
    "interval": "intervalSeconds",
    "timeout": "timeoutSeconds",
    "retries": "retries",
    "start_period": "startPeriodSeconds",
}


class ResolvedDeploymentError(ValueError):
    """The plan holds something version 1 of the resolved deployment cannot say."""


def resolved_deployment(
    declaration: Declaration,
    project: str,
    *,
    tables: Tables,
    images: Mapping[str, str],
    frontend_lock: bool,
    image_volumes: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """The resolved deployment of a generated *declaration*, as one JSON-ready object.

    *images* maps each service the release builds an image for to that image, by digest, as
    ``sign`` verified it and records it in ``outputs.services``: ``<repository>@sha256:<64
    hex>``. A datastore's image is the datastore table's, and an entry *images* holds for it
    must be the same. *image_volumes* maps an image reference to the paths its configuration
    declares as volumes: each path no named volume covers becomes an anonymous mount, which no
    backup covers. *declaration* must be one :func:`terp.arch.deployment.generator.generate`
    renders without a refusal: the caller checks that first.
    """
    plan = _plan(declaration, project, tables, frontend_lock)
    for unit in declaration.units:
        if unit.kind is not None and unit.role == "store":
            raise ResolvedDeploymentError(
                f"{unit.id} is a bundled store, and version 1 of the resolved deployment has no "
                "reference for a store's address (allowed: no store unit, until the contract "
                "carries one)"
            )
    volumes_by_image = image_volumes or {}
    services = [
        _service(plan, unit, images, volumes_by_image) for unit in declaration.units
    ]
    document: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "services": services,
        "volumes": sorted(
            {mount["source"] for service in services for mount in service["mounts"] if mount["type"] == "volume"}
        ),
    }
    if plan.migration_step is not None:
        document["migration"] = plan.migration_step
    return document


def _service(
    plan: _Plan,
    unit: Unit,
    images: Mapping[str, str],
    volumes_by_image: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    kind = plan.kind_of(unit.id)
    backend = unit.id in plan.backend
    service: dict[str, Any] = {
        "id": unit.id,
        "role": unit.role,
        "lifecycle": "one-shot" if kind == "one-shot" else "long-running",
    }
    if kind == "kind":
        service["datastore"] = {"kind": str(unit.kind), "version": str(unit.version)}
    image = _image_of(plan, unit, kind, images)
    service["image"] = image
    command = _command_of(plan, unit, kind)
    if command is not None:
        service["command"] = list(command)
    service["init"] = backend and kind not in ("api", "one-shot")
    service["environment"] = _environment(plan, unit, kind)
    service["appEnvironment"] = backend
    mounts = _named_mounts(plan, unit, kind)
    covered = {mount["target"] for mount in mounts}
    mounts += [
        {"type": "anonymous", "target": path}
        for path in sorted(set(volumes_by_image.get(image, ())))
        if path not in covered
    ]
    service["mounts"] = sorted(mounts, key=lambda mount: mount["target"])
    serves = _serves(unit, kind)
    if serves is not None:
        service["serves"] = serves
    probe = probe_of(plan, unit)
    if probe is not None:
        service["healthcheck"] = _healthcheck(probe)
    service["after"] = sorted(
        ({"unit": ident, "condition": condition_of(plan, ident)} for ident in unit.depends_on or ()),
        key=lambda entry: entry["unit"],
    )
    return service


def _image_of(plan: _Plan, unit: Unit, kind: str, images: Mapping[str, str]) -> str:
    if kind == "kind":
        entry = plan.tables.datastores.find(str(unit.kind), str(unit.version))
        if entry is None:  # the generator refuses it first; a caller that skipped that is told
            raise ResolvedDeploymentError(f"{unit.id}: no datastore table entry for {unit.kind} {unit.version}")
        if images.get(unit.id, entry.image) != entry.image:
            raise ResolvedDeploymentError(
                f"{unit.id} runs {images[unit.id]}, and the datastore table pins {entry.image} for "
                f"{unit.kind} {unit.version} (allowed: the table's image only)"
            )
        return entry.image
    if unit.id not in images:
        raise ResolvedDeploymentError(
            f"{unit.id} runs an image the release builds, and none was given for it (allowed: the "
            "image sign verified for each built service, by digest, as outputs.services records it)"
        )
    return images[unit.id]


def _command_of(plan: _Plan, unit: Unit, kind: str) -> tuple[str, ...] | None:
    """The argv a service runs, or ``None`` for its image's own.

    The migration step carries none: the executor runs ``terp migrate`` there itself, with
    its own argv and the connection that may change the schema.
    """
    if kind in ("web", "site"):
        return None
    if kind == "kind":
        return unit.command
    if unit.id == plan.migration_step:
        return None
    return unit.command if unit.command is not None else DEFAULT_COMMANDS.get(kind)


def _environment(plan: _Plan, unit: Unit, kind: str) -> list[dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}
    if kind == "kind":
        for name, text in plan.kinds[unit.id].environment:
            entries[name] = _reference(unit.id, name, text)
    elif kind == "web":
        if plan.upstream not in (None, "api"):
            entries["API_UPSTREAM"] = {"source": "value", "value": f"{plan.upstream}:{API_CONTAINER_PORT}"}
    elif unit.id in plan.backend:
        if unit.id != plan.migration_step:
            # The migration step gets the connection that may change the schema from the
            # executor, never from the document.
            entries["DATABASE_URL"] = {"source": "database", "key": "runtime"}
        entries["SECRET_KEY"] = _reference(unit.id, "SECRET_KEY", KEY_SEAM)
        entries["ENVIRONMENT"] = {"source": "value", "value": "production"}
        entries["BACKEND_CORS_ORIGINS"] = _reference(unit.id, "BACKEND_CORS_ORIGINS", CORS_ORIGINS)
    return [{"name": name, **entries[name]} for name in sorted(entries)]


#: The profile's seams the resolved deployment names a source for, each by its variable.
_SEAMS = {
    ("SECRET_KEY", KEY_SEAM): {"source": "secret", "key": "SECRET_KEY"},
    ("BACKEND_CORS_ORIGINS", CORS_ORIGINS): {"source": "config", "key": "BACKEND_CORS_ORIGINS"},
}

_REQUIRED_SEAM = re.compile(r"\$\{([A-Z][A-Z0-9_]*):\?[^}]*\}")


def _reference(unit: str, name: str, text: str) -> dict[str, str]:
    """Where *name*'s value comes from, read from the profile's text for it.

    A plain value is a literal; a seam the table above names is that reference; a required
    variable of the same name (``${NAME:?...}``) is that secret. Anything else holding a ``$``
    is refused rather than signed as a literal the executor would never expand.
    """
    known = _SEAMS.get((name, text))
    if known is not None:
        return dict(known)
    required = _REQUIRED_SEAM.fullmatch(text)
    if required is not None and required.group(1) == name:
        return {"source": "secret", "key": name}
    if "$" in text:
        raise ResolvedDeploymentError(
            f"{unit}: {name} is {text!r}, a seam version 1 of the resolved deployment has no "
            "source for (allowed: a literal, a declared secret written ${NAME:?...}, or a seam "
            "the resolved deployment names)"
        )
    return {"source": "value", "value": text}


def _named_mounts(plan: _Plan, unit: Unit, kind: str) -> list[dict[str, Any]]:
    if kind == "kind":
        recipe = plan.kinds[unit.id]
        return [{"type": "volume", "source": f"{unit.id}-data", "target": recipe.data_path, "readOnly": False}]
    if unit.id not in plan.backend:
        return []
    return [
        {"type": "volume", "source": volume.id, "target": FILES_ROOT, "readOnly": False}
        for volume in plan.declaration.volumes
        if volume.mount is not None and unit.id in volume.mount.units
    ]


def _serves(unit: Unit, kind: str) -> dict[str, Any] | None:
    if kind == "api":
        return {"port": API_CONTAINER_PORT, "healthPath": str(unit.health_path)}
    if kind == "web":
        return {"port": WEB_CONTAINER_PORT, "healthPath": unit.health_path or "/"}
    if kind == "site":
        return {"port": WEB_CONTAINER_PORT, "healthPath": SITE_HEALTH_PATH}
    return None


def _healthcheck(probe: tuple[tuple[str, ...], tuple[str, ...]]) -> dict[str, Any]:
    test, timing = probe
    check: dict[str, Any]
    if test[0] == "CMD":
        check = {"form": "exec", "argv": list(test[1:])}
    elif test[0] == "CMD-SHELL" and len(test) == 2:
        check = {"form": "shell", "script": test[1]}
    else:
        raise ResolvedDeploymentError(f"a probe of an unknown form: {test!r}")
    for line in timing:
        matched = _TIMING_LINE.fullmatch(line)
        if matched is None:
            raise ResolvedDeploymentError(f"a probe timing line it cannot read: {line!r}")
        check[_TIMING_FIELDS[matched.group(1)]] = int(matched.group(2))
    return check


__all__ = [
    "API_CONTAINER_PORT",
    "FILES_ROOT",
    "SCHEMA_VERSION",
    "WEB_CONTAINER_PORT",
    "ResolvedDeploymentError",
    "resolved_deployment",
]
