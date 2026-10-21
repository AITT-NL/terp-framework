"""The profile a deployment declaration describes, read the way compose reads it.

``compose.file`` and ``compose.overrides`` are one resolved profile, merged the way
``docker compose -f <file> -f <override>`` merges them, for the fields the declaration
restates or leads a reader to: services, images, builds, commands, start order,
environment, env files, volumes and profiles, including the ``!reset`` and ``!override``
tags an override uses to remove the bundled database.

Two readers use it. :func:`build_path_findings` is part of being readable: the build
contexts and build files of the declared units are paths the declaration leads a reader
to, so they have to stay inside the checkout. :func:`truth_findings` is rule 2 from the
files: every fact the declaration restates from the profile must be the profile's
(ADR 0184 decision 5). Neither ever asks whether a topology is approved: a service no
unit names is not this file's business.
"""

from __future__ import annotations

import json
import pathlib
import posixpath
import re
import shlex
from dataclasses import dataclass
from typing import Any

import yaml

from terp.arch.deployment.datastores import DatastoreTable
from terp.arch.deployment.files import checkout_root, inside
from terp.arch.deployment.reader import Declaration, Finding, Unit, role_findings
from terp.arch.deployment.volumes import _volume_findings


@dataclass(frozen=True)
class _Override:
    value: Any


class _Reset:
    """``!reset``: the key is removed from what the earlier files said."""


_RESET = _Reset()


class _ComposeLoader(yaml.SafeLoader):
    """Safe loading, plus the two tags compose gives override files."""


def _construct_reset(loader: yaml.SafeLoader, node: yaml.Node) -> _Reset:
    return _RESET


def _construct_override(loader: yaml.SafeLoader, node: yaml.Node) -> _Override:
    if isinstance(node, yaml.MappingNode):
        return _Override(loader.construct_mapping(node, deep=True))
    if isinstance(node, yaml.SequenceNode):
        return _Override(loader.construct_sequence(node, deep=True))
    return _Override(loader.construct_scalar(node))


_ComposeLoader.add_constructor("!reset", _construct_reset)
_ComposeLoader.add_constructor("!override", _construct_override)

#: Fields an override replaces outright rather than extends.
_REPLACED = frozenset({"command", "entrypoint"})
#: Fields compose accepts as a list or a mapping and merges as a mapping.
_MAPPINGS = frozenset({"depends_on", "environment", "labels"})


def _clean(value: Any) -> Any:
    if isinstance(value, _Override):
        return _clean(value.value)
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items() if item is not _RESET}
    if isinstance(value, list):
        return [_clean(item) for item in value if item is not _RESET]
    return value


def as_mapping(value: Any) -> dict[str, Any]:
    """``depends_on`` / ``environment`` in either compose form, as a mapping."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, list):
        return {}
    mapping: dict[str, Any] = {}
    for entry in value:
        name, _, rest = str(entry).partition("=")
        mapping[name.strip()] = rest
    return mapping


def _merge(base: Any, override: Any, key: str = "") -> Any:
    if isinstance(override, _Override):
        return _clean(override)
    if key in _MAPPINGS:
        base, override = as_mapping(base), as_mapping(_clean(override))
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for name, value in override.items():
            if value is _RESET:
                merged.pop(name, None)
            elif name in merged:
                merged[name] = _merge(merged[name], value, name)
            else:
                merged[name] = _clean(value)
        return merged
    if isinstance(base, list) and isinstance(override, list) and key not in _REPLACED:
        return base + [item for item in _clean(override) if item not in base]
    return _clean(override)


def _parse(text: str) -> Any:
    """One YAML document, through the safe loader with compose's two override tags."""
    loader = _ComposeLoader(text)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def resolve_profile(
    project_root: pathlib.Path, declaration: Declaration
) -> tuple[dict[str, Any], list[Finding]]:
    """The base profile and its overrides, merged in order into one profile."""
    merged: dict[str, Any] = {}
    for index, name in enumerate(declaration.profile_files):
        field = "compose.file" if index == 0 else f"compose.overrides[{index - 1}]"
        path = project_root / name
        if not path.is_file():
            return {}, [
                Finding(
                    f'{field} "{name}" does not exist (allowed: a profile file that '
                    "exists, whose services the units are)"
                )
            ]
        try:
            data = _parse(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            return {}, [Finding(f"{field} {name} is not readable YAML: {exc}", file=name)]
        if not isinstance(data, dict):
            return {}, [
                Finding(f"{field} {name} is not a compose file: it holds no mapping", file=name)
            ]
        merged = _merge(merged, data)
    return merged, []


def services_of(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The profile's services that are mappings, by name."""
    services = profile.get("services")
    if not isinstance(services, dict):
        return {}
    return {name: service for name, service in services.items() if isinstance(service, dict)}


def _builders(services: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Image name -> the service that builds it from the checkout."""
    return {
        service["image"]: name
        for name, service in services.items()
        if "build" in service and isinstance(service.get("image"), str)
    }


def _builder_of(unit: Unit, services: dict[str, dict[str, Any]]) -> str | None:
    service = services.get(unit.id)
    if service is None:
        return None
    if "build" in service:
        return unit.id
    return _builders(services).get(service.get("image"))


def _remote(path: str) -> bool:
    return "://" in path or path.startswith("git@")


def build_path_findings(project_root: pathlib.Path, declaration: Declaration) -> list[Finding]:
    """The build contexts and build files of the declared units: inside the checkout.

    A profile that cannot be read yet leads nowhere, so it is silent here; whether the
    profile is there and reads is the truth check's to report.
    """
    profile, problems = resolve_profile(project_root, declaration)
    if problems:
        return []
    services = services_of(profile)
    checkout = checkout_root(project_root)
    base = (project_root / declaration.compose_file).parent
    label = " + ".join(declaration.profile_files)
    findings: list[Finding] = []
    builders = sorted({name for unit in declaration.units if (name := _builder_of(unit, services))})
    for builder in builders:
        build = services[builder]["build"]
        context = build if isinstance(build, str) else str(build.get("context", "."))
        dockerfile = None if isinstance(build, str) else build.get("dockerfile")
        targets = [("context", context, base)]
        if isinstance(dockerfile, str):
            targets.append(("dockerfile", dockerfile, base / context))
        for what, written, relative_to in targets:
            if _remote(written) or not inside(relative_to / written, checkout):
                findings.append(
                    Finding(
                        f"{label}: services.{builder}.build.{what} {written!r} resolves "
                        "outside the checkout (allowed: a build context and build file "
                        "that resolve inside the checkout)",
                        "A unit without a kind is built from the checkout; a build that "
                        "reaches outside it is not.",
                        file=declaration.compose_file,
                    )
                )
    return findings


#: What compose interpolates: ``$$``, ``$name`` and ``${``, read the way compose reads them.
_INTERPOLATION = re.compile(r"\$(\$|\{|[A-Za-z_])")


def compose_literal(text: str) -> str | None:
    """The literal compose makes of *text*, or ``None`` when it interpolates.

    ``$$`` is one ``$``; ``$name`` and ``${...}`` are interpolations, whose value is the
    environment's and so never equals a literal the declaration restates; any other ``$``
    (``$!``, ``$1``, a trailing one) is literal, as compose leaves it. A profile the
    generator renders doubles every ``$`` of a value, so the declaration's own text is what
    this gives back (ADR 0187).
    """
    out: list[str] = []
    position = 0
    for match in _INTERPOLATION.finditer(text):
        if match.group(1) != "$":
            return None
        out.append(text[position : match.start()] + "$")
        position = match.end()
    return "".join(out) + text[position:]


def _argv(command: Any) -> tuple[str | None, ...] | None:
    """The command compose runs, element by element; ``None`` marks an interpolation."""
    if isinstance(command, list):
        return tuple(compose_literal(str(part)) for part in command)
    if isinstance(command, str):
        literal = compose_literal(command)
        return (None,) if literal is None else tuple(shlex.split(literal))
    return None


def _shown(command: Any) -> str:
    """A profile's command as its author wrote it, for a message."""
    if isinstance(command, list):
        return " ".join(map(str, command))
    return "the image's own command" if command is None else str(command)


def _restated(
    index: int, unit: Unit, service: dict[str, Any], ids: set[str], label: str
) -> list[Finding]:
    """A restated fact the profile owns has to be the profile's."""
    findings: list[Finding] = []
    written = service.get("command")
    actual = _argv(written)
    if unit.command is not None and actual != unit.command:
        runs = _shown(written)
        findings.append(
            Finding(
                f"units[{index}].command restates {list(unit.command)}, and {label} runs "
                f"{runs} for {unit.id} (allowed: the profile's command, as an argument list)"
            )
        )
    if unit.depends_on is not None:
        order = sorted(set(as_mapping(service.get("depends_on"))) & ids)
        if sorted(set(unit.depends_on)) != order:
            findings.append(
                Finding(
                    f"units[{index}].dependsOn restates {sorted(unit.depends_on)}, and {label} "
                    f"starts {unit.id} after {', '.join(order) or 'none'} of the declared "
                    "units (allowed: the profile's start order, restricted to declared units)"
                )
            )
    return findings


def _env_files(service: dict[str, Any]) -> set[str]:
    raw = service.get("env_file")
    entries = raw if isinstance(raw, list) else [raw] if raw else []
    paths = [entry.get("path", "") if isinstance(entry, dict) else str(entry) for entry in entries]
    return {posixpath.normpath(path) for path in paths if path}


#: A compose service name, as ``environment.schema.json``'s ``services`` admits one.
_SERVICE_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,62}")


def rendered_files(declaration: object) -> frozenset[str]:
    """The env files a manifest declaration renders into: the renderer's own rule.

    ``.app.env`` for a declaration that names no services, one ``.app.<service>.env``
    per named service otherwise. The harness sits below the CLI and cannot import
    ``terp.cli.envschema.rendered_files``, so this is a second statement of that rule,
    held equal to it case by case by ``tests/architecture/test_deployment_declaration.py``.
    """
    services = declaration.get("services") if isinstance(declaration, dict) else None
    entries = services if isinstance(services, list) else []
    named = [name for name in entries if isinstance(name, str) and _SERVICE_NAME.fullmatch(name)]
    if not named:
        return frozenset({".app.env"})
    return frozenset(f".app.{service}.env" for service in named)


def _manifest(project_root: pathlib.Path) -> dict[str, Any]:
    try:
        data = json.loads((project_root / "environment.schema.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    properties = data.get("properties") if isinstance(data, dict) else None
    return properties if isinstance(properties, dict) else {}


def _env_findings(
    index: int, unit: Unit, service: dict[str, Any], manifest: dict[str, Any], label: str
) -> list[Finding]:
    """An ``env`` name is a claim that the profile passes it to this unit."""
    loaded = _env_files(service)
    return [
        Finding(
            f"units[{index}].env[{position}] {name} is never passed to {unit.id} by {label} "
            "(allowed: a name in its environment: block, or one the variable manifest "
            "routes to a file it loads through env_file:)"
        )
        for position, name in enumerate(unit.env)
        if name not in as_mapping(service.get("environment"))
        and not (name in manifest and rendered_files(manifest[name]) & loaded)
    ]


def _image_findings(
    index: int, unit: Unit, services: dict[str, dict[str, Any]], table: DatastoreTable, label: str
) -> list[Finding]:
    """Decision 3: the table's image for a kind, the checkout's own build for the rest."""
    image = services[unit.id].get("image")
    if unit.kind is not None:
        entry = table.find(unit.kind, str(unit.version))
        if entry is None or entry.pinned_by(image):
            return []
        return [
            Finding(
                f"units[{index}].kind {unit.kind} {unit.version}: service {unit.id} runs "
                f"{image or 'no image'}, and the datastore table pins {entry.image} "
                "(allowed: exactly the table's image, by its digest and from its registry)",
                "A tag moves, and another registry or digest is not the image this "
                "release vouches for.",
            )
        ]
    if _builder_of(unit, services) is not None:
        return []
    return [
        Finding(
            f'units[{index}].id "{unit.id}" runs {image or "no image"}, which no service of '
            f"{label} builds from the checkout (allowed: an image some profile service "
            "builds from the checkout, or a kind and version from the datastore table)"
        )
    ]


def _external_database_findings(
    declaration: Declaration, services: dict[str, dict[str, Any]], table: DatastoreTable, label: str
) -> list[Finding]:
    if not declaration.external_database:
        return []
    databases = [entry for entry in table.entries if entry.role == "database"]
    running = {
        unit.id for unit in declaration.units if unit.role == "database" and unit.id in services
    }
    running |= {
        name
        for name, service in services.items()
        if not service.get("profiles")
        and any(entry.runs_its_repository(service.get("image")) for entry in databases)
    }
    if not running:
        return []
    return [
        Finding(
            f"externalDatabase is declared, and {label} still runs a database service "
            f"({', '.join(sorted(running))}) (allowed: a resolved profile that runs no "
            "database service)",
            "The profile still runs a database service; name the override that removes it "
            "in compose.overrides, or drop externalDatabase.",
        )
    ]


def truth_findings(
    project_root: pathlib.Path, declaration: Declaration, table: DatastoreTable
) -> list[Finding]:
    """Rule 2 from the files: every fact the declaration restates from the profile."""
    profile, problems = resolve_profile(project_root, declaration)
    if problems:
        return problems
    label = " + ".join(declaration.profile_files)
    services = services_of(profile)
    ids = {unit.id for unit in declaration.units}
    manifest = _manifest(project_root)
    findings: list[Finding] = []
    for index, unit in enumerate(declaration.units):
        service = services.get(unit.id)
        if service is None:
            findings.append(
                Finding(
                    f'units[{index}].id "{unit.id}" is not a service of {label} (allowed: a '
                    f"service of the profile: {', '.join(sorted(services)) or 'none'})",
                    "A declaration is partial, so drop a unit the profile does not run.",
                )
            )
            continue
        findings.extend(_restated(index, unit, service, ids, label))
        findings.extend(_env_findings(index, unit, service, manifest, label))
        findings.extend(_image_findings(index, unit, services, table, label))
    findings.extend(_volume_findings(declaration, profile, services, label))
    findings.extend(_external_database_findings(declaration, services, table, label))
    findings.extend(role_findings(declaration))
    return findings
