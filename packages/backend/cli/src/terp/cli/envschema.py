"""``environment.schema.json`` — the app-declared variable manifest, and its dialect.

An app declares the run-time variables it reads in this manifest; Terp Studio renders
exactly those declarations into a per-environment ``.app.env`` that the compose profiles
forward. Studio's reader is **fail closed on the whole file**: one defect anywhere and
every declaration disappears — the app's secrets included — from the environment form and
from the rendered ``.app.env``.

That verdict used to be Studio's alone, which put it a deploy (and often a different
machine) away from the edit that caused it. An authoring agent wrote a ``description``
longer than 500 characters explaining an OIDC variable well, ``terp verify --profile
full`` stayed green, and the app silently lost its whole manifest. So the dialect is
checked here too, in the app's own gate, where the edit happens.

The two halves have no package to share (Terp Studio never imports ``terp.*``), so the
rules below are mirrored from Terp Studio's own manifest reader deliberately — same
limits, same wording — and held equal case by case by
``tests/architecture/test_cli_env_seams.py``. Unknown property fields are dropped by
Studio rather than refused, which is why nothing here may depend on one.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

#: The app's declared-variable manifest, at the project root.
APP_ENV_SCHEMA_FILE = "environment.schema.json"

#: Where a declared variable's value is resolved. ``host`` and ``browser`` addresses are
#: reached from outside the compose network (a developer's shell, a redirected browser);
#: ``container`` addresses are dialled by a service on the network, where a loopback host
#: means the container itself.
RESOLVED_BY_VALUES = frozenset({"host", "container", "browser"})

#: Names the platform already owns; a manifest may never shadow them.
PLATFORM_OWNED_NAMES = frozenset(
    {
        "SECRET_KEY",
        "POSTGRES_PASSWORD",
        "DATABASE_URL",
        "ENVIRONMENT",
        "WEB_PORT",
        "BACKEND_CORS_ORIGINS",
    }
)

#: The dialect's limits. Off by one on any of them is a manifest that passes the gate and
#: dies in Studio, which is the exact failure this module exists to prevent.
MAX_PROPERTIES = 50
MAX_TEXT = 500
MAX_ENUM = 50
MAX_ENUM_VALUE = 200

#: Property fields Studio requires to be short strings.
_TEXT_FIELDS = ("type", "title", "description", "format", "group", "resolvedBy")

_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


@dataclass(frozen=True)
class ManifestFinding:
    """One reason Studio's reader would refuse the manifest — and with it every
    declaration in the file, not just the offending one.

    *subject* is what the reader was looking at: ``""`` for the file itself, a variable
    name, or ``NAME.field``. Rendered as ``subject detail``, which is deliberately the
    shape Studio's own message has, so the two halves of the platform say one thing.
    """

    subject: str
    detail: str


def _property_findings(name: object, prop: object) -> list[ManifestFinding]:
    """Every way one declared property is unusable.

    The name defects return early: a property Studio refuses on its key is not one whose
    fields it ever looks at, and pricing one mistake twice buries the name that has to
    change.
    """
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        return [
            ManifestFinding(
                repr(name),
                "is not a valid variable name -- use UPPER_SNAKE (a letter, then "
                "letters, digits and underscores; at most 64 characters)",
            )
        ]
    if name in PLATFORM_OWNED_NAMES:
        return [
            ManifestFinding(
                name,
                "is platform-owned -- one owner per variable; remove it from the "
                "manifest",
            )
        ]
    if name.startswith("VITE_"):
        return [
            ManifestFinding(
                name,
                "is a frontend build-time variable -- it is baked at image build and "
                "cannot be injected at run time; remove it from the manifest",
            )
        ]
    if not isinstance(prop, dict):
        return [ManifestFinding(name, 'must be an object, e.g. {"type": "string"}')]

    findings: list[ManifestFinding] = []
    for field in _TEXT_FIELDS:
        value = prop.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            findings.append(
                ManifestFinding(
                    f"{name}.{field}",
                    f"must be a string of at most {MAX_TEXT} characters",
                )
            )
        elif len(value) > MAX_TEXT:
            findings.append(
                ManifestFinding(
                    f"{name}.{field}",
                    f"must be a string of at most {MAX_TEXT} characters "
                    f"(it is {len(value)}) -- shorten it",
                )
            )
    resolved_by = prop.get("resolvedBy")
    # Judge the vocabulary only once the value cleared the shape check above, so a
    # non-string or over-long `resolvedBy` is one offence rather than two.
    if (
        isinstance(resolved_by, str)
        and len(resolved_by) <= MAX_TEXT
        and resolved_by not in RESOLVED_BY_VALUES
    ):
        findings.append(
            ManifestFinding(
                f"{name}.resolvedBy",
                f"is {resolved_by!r} -- use one of "
                f"{', '.join(sorted(RESOLVED_BY_VALUES))} (who resolves the address: a "
                "service on the compose network, your shell, or the user's browser)",
            )
        )
    enum = prop.get("enum")
    if enum is not None and (
        not isinstance(enum, list)
        or len(enum) > MAX_ENUM
        or not all(isinstance(v, str) and len(v) <= MAX_ENUM_VALUE for v in enum)
    ):
        findings.append(
            ManifestFinding(
                f"{name}.enum",
                f"must be a list of at most {MAX_ENUM} strings of at most "
                f"{MAX_ENUM_VALUE} characters",
            )
        )
    return findings


def manifest_findings(project_root: pathlib.Path) -> list[ManifestFinding]:
    """Every reason Studio's fail-closed reader would refuse this app's manifest.

    An absent manifest has no shape to refuse — the same no-op an app that has not
    adopted the seam gets everywhere else. Studio raises on the *first* defect; this
    reports all of them, because an author fixing one per gate run pays exactly the
    round trip this exists to remove.
    """
    import json

    path = project_root / APP_ENV_SCHEMA_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [ManifestFinding("", f"is not valid JSON ({exc})")]
    # Each of the three below makes every later reading meaningless, so each is the whole
    # verdict rather than the first of several.
    if not isinstance(data, dict) or data.get("type") != "object":
        return [ManifestFinding("", 'must be a JSON object with "type": "object"')]
    properties = data.get("properties", {})
    if not isinstance(properties, dict):
        return [ManifestFinding("", '"properties" must be an object of declarations')]

    findings: list[ManifestFinding] = []
    if len(properties) > MAX_PROPERTIES:
        findings.append(
            ManifestFinding(
                "",
                f"declares {len(properties)} variables -- at most {MAX_PROPERTIES} "
                "are allowed",
            )
        )
    for name, prop in properties.items():
        findings.extend(_property_findings(name, prop))

    required = data.get("required", [])
    if not isinstance(required, list) or not all(isinstance(n, str) for n in required):
        findings.append(
            ManifestFinding("", '"required" must be a list of declared variable names')
        )
    else:
        findings.extend(
            ManifestFinding(name, 'is in "required" but not declared in "properties"')
            for name in required
            if name not in properties
        )
    return findings


def declared_variables(project_root: pathlib.Path) -> dict[str, dict]:
    """The names the app *means* to declare, tolerantly — ``{}`` when it declares none.

    Deliberately not the verdict: ``manifest_findings`` gives that, and callers report it
    first, so this never has to raise on a file that has already been refused.
    """
    import json

    path = project_root / APP_ENV_SCHEMA_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    properties = data.get("properties") if isinstance(data, dict) else None
    if not isinstance(properties, dict):
        return {}
    return {name: prop for name, prop in properties.items() if isinstance(prop, dict)}
