"""The words of ``workbench.json``, as the Terp Standard fixes them.

``workbench.json`` says which parts of an app's development loop a tool that drives
it relies on (ADR 0110). Its vocabulary is the Terp Standard's
``workbench-declaration.schema.json``, and this package ships a byte-for-byte mirror of
it beside this module (ADR 0186): terp-spec is only a development dependency of the
framework, so the mirror is what an installed toolchain reads, and
``tests/architecture/test_workbench_schema_mirror.py`` holds it to the pinned release.

Nothing here restates the schema. Every list a reader needs is read out of the mirror
when this module loads - the versions, the command slots, the roles, the fields
resolved by role, the seams, the reserved variable names and the deployment-profile
markers - and :func:`problems` applies the mirror itself, through the same small
validator the deployment declaration is read with, which refuses a schema keyword it
does not apply. What a reader does with a fact lives with the reader:
:mod:`terp.cli.workbench` is the gate's, and a development tool has its own.

It lives in terp-arch rather than beside the CLI's checker because two packages read
the file: the checker, and the deployment declaration's reader, which needs to know
which compose file is the development one, and terp-arch cannot import terp-cli.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from terp.arch.deployment import _jsonschema

#: The declaration's filename, at the project root.
WORKBENCH_FILE = "workbench.json"

#: The schema mirror, beside this module in the wheel.
SCHEMA_FILE = "workbench-declaration.schema.json"

#: The terp-spec release whose ``workbench-declaration.schema.json`` this mirror must
#: equal byte for byte once that release is pinned.
SPEC_RELEASE = "0.40.0"


def _load() -> dict[str, Any]:
    raw = json.loads(pathlib.Path(__file__).with_name(SCHEMA_FILE).read_text(encoding="utf-8"))
    _jsonschema.check_schema(raw)
    return raw


#: The mirror, parsed once. Checked against the validator's keyword subset on load, so
#: a later schema that adds a constraint this reader cannot apply fails here, loudly,
#: instead of being read as if the constraint were not there.
SCHEMA: dict[str, Any] = _load()

_DECLARED: dict[str, Any] = SCHEMA["else"]
_PROPERTIES: dict[str, Any] = _DECLARED["properties"]
_DEFS: dict[str, Any] = SCHEMA["$defs"]

#: The versions this vocabulary defines. A file from the future is not the app's
#: failure: it means the reader is behind, and it says so rather than reading a later
#: file with an earlier vocabulary.
SUPPORTED_VERSIONS: frozenset[int] = frozenset({_PROPERTIES["schemaVersion"]["const"]})

#: The compose file a declaration that names none describes.
DEFAULT_COMPOSE_FILE: str = _PROPERTIES["compose"]["properties"]["file"]["default"]

#: The command slots a reader knows. ``start`` is the one that makes the block
#: meaningful; a slot outside these is information, never run and never refused.
COMMAND_SLOTS: frozenset[str] = frozenset(_PROPERTIES["commands"]["properties"])

#: The roles a reader resolves by name. A role outside them is information.
KNOWN_ROLES: frozenset[str] = frozenset(_DEFS["knownRoles"]["enum"])

#: The service fields a reader resolves BY ROLE, in the schema's order.
ROLE_RESOLVED_FIELDS: tuple[str, ...] = tuple(_DEFS["roleResolvedFields"]["enum"])

#: The ``env`` seams a reader sets a value for. A label outside them is information.
ENV_SEAMS: frozenset[str] = frozenset(_PROPERTIES["env"]["properties"])

#: Name prefixes and names a declared variable may never take: a reader puts every
#: declared name into the environment of the commands it runs.
RESERVED_ENV_PREFIXES: tuple[str, ...] = tuple(_DEFS["reservedEnvironmentPrefixes"]["enum"])
RESERVED_ENV_NAMES: frozenset[str] = frozenset(_DEFS["reservedEnvironmentNames"]["enum"])

#: A compose file whose name contains one of these is a deployment profile.
DEPLOYMENT_PROFILE_MARKERS: tuple[str, ...] = tuple(_DEFS["deploymentProfileMarkers"]["enum"])


def problems(document: Any) -> list[_jsonschema.Problem]:
    """Every way *document* fails the schema, in document order."""
    return _jsonschema.validate(document, SCHEMA)


def reserved_name(name: str) -> str:
    """Why *name* may not be declared, or ``""`` if it may."""
    if name in RESERVED_ENV_NAMES:
        return f"{name} is a name the process environment reads for itself"
    prefix = next((prefix for prefix in RESERVED_ENV_PREFIXES if name.startswith(prefix)), "")
    if prefix:
        return f"{name} is in the {prefix} namespace, which the toolchain reads for itself"
    return ""


def names_a_deployment_profile(compose_file: str) -> bool:
    """Does *compose_file* carry a marker that makes it a deployment profile?"""
    return any(marker in compose_file for marker in DEPLOYMENT_PROFILE_MARKERS)


__all__ = [
    "COMMAND_SLOTS",
    "DEFAULT_COMPOSE_FILE",
    "DEPLOYMENT_PROFILE_MARKERS",
    "ENV_SEAMS",
    "KNOWN_ROLES",
    "RESERVED_ENV_NAMES",
    "RESERVED_ENV_PREFIXES",
    "ROLE_RESOLVED_FIELDS",
    "SCHEMA",
    "SCHEMA_FILE",
    "SPEC_RELEASE",
    "SUPPORTED_VERSIONS",
    "WORKBENCH_FILE",
    "names_a_deployment_profile",
    "problems",
    "reserved_name",
]
