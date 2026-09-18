"""``environment.schema.json`` — the app-declared variable manifest, and its dialect.

An app declares the run-time variables it reads in this manifest; Terp Studio renders
exactly those declarations into a per-environment ``.app.env`` that the compose profiles
forward. A declaration may narrow that with ``"services"``: the variable is then rendered
into ``.app.<service>.env`` (see ``app_env_file_name``) and only the services that forward
that file ever see it. Without the field the credentials one worker holds for a foreign
system also ship to the app's api, migrate and seed containers, which is why apps reached
for a second, hand-made env file that no manifest governs and Studio cannot manage.
Studio's reader is **fail closed on the whole file**: one defect anywhere and every
declaration disappears — the app's secrets included — from the environment form and from
the rendered ``.app.env``.

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
MAX_SERVICES = 10
MAX_SERVICE_NAME = 63

#: Compose service naming, as compose itself allows it: lowercase letters, digits,
#: underscore, dot and hyphen. Kept a literal rather than built from ``MAX_SERVICE_NAME``
#: so it can be read — and pasted into the other half of the platform — as one pattern;
#: the ``62`` is that limit minus the leading character the pattern spells out.
SERVICE_NAME_PATTERN = r"^[a-z0-9][a-z0-9_.-]{0,62}$"

#: The file the shared declarations are rendered into; the compose profiles forward it.
APP_ENV_FILE = ".app.env"

#: Whether the deploy side can render the per-service files ``"services"`` implies.
#:
#: This half of the platform is only ever the *reader* of a manifest; Terp Studio is what
#: renders one into the files a compose profile forwards, and it pins this framework by
#: git ref rather than the other way round. So the dialect can grow a field here a
#: release before Studio can honour it — and per the module docstring above, Studio
#: **drops** a field it does not know rather than refusing it.
#:
#: That combination is the one failure this whole module exists to prevent, in its worst
#: shape. An app that scopes a variable while this is False gets a value that arrives in
#: the workbench (where ``terp env`` renders the per-service file) and silently never
#: arrives in a Studio-managed environment (where every declaration lands in the shared
#: ``.app.env`` while the app's compose forwards a ``.app.<service>.env`` nothing wrote).
#: Local green, production empty, nothing anywhere saying why. So the field is REFUSED by
#: ``env-seams`` while this is False: the dialect, the checks and the renderer all ship
#: and are exercised, and no app can depend on a path that does not exist end to end yet.
#:
#: Flip to True in the same change that moves Studio's ``TERP_FRAMEWORK_REF`` onto a
#: framework release carrying this dialect AND teaches Studio's three sites to render it
#: (its reader's field list, the hardcoded shared-file name in its compose renderer, and
#: the exact-path filter its Portainer path strips the app env file by). ADR 0124 records
#: the contract and why the window is shut from this side.
#: ``test_the_scope_field_is_refused_until_the_deploy_side_can_render_it`` pins it.
STUDIO_RENDERS_SCOPED_FILES = False

#: Property fields Studio requires to be short strings.
_TEXT_FIELDS = ("type", "title", "description", "format", "group", "resolvedBy")

#: Every field a declaration may carry. Studio's reader keeps exactly its own list and
#: **drops** the rest -- the module docstring above says so, and that drop is silent.
#: For most fields that is harmless. For one it inverts the platform's central claim:
#: an author who writes ``"secret": true`` instead of ``"format": "secret"`` has written
#: a key nothing recognises, so the variable is stored as an ordinary shared value in
#: plain records rather than routed through sealed custody -- and every check stays
#: green, because a dropped key leaves nothing behind to disagree with. Insecurity is
#: then not an explicit, greppable, budgeted opt-out; it is a typo, and it is invisible.
#: The manifest is the seam to the pipeline that holds real credentials, it is written
#: once per app, and it is rarely re-read, so "invisible" means "permanent".
#:
#: Refusing an unrecognised key here is the whole fix: the gate runs where the edit
#: happens. ``$``-prefixed keys are exempt because they are JSON Schema's own annotation
#: convention and carry no behaviour -- the shipped manifests use ``$comment`` for
#: exactly that.
#: ``default`` and ``services`` are this half's own: ``terp env init`` fills a default in
#: and ``env-seams`` judges a loopback one, and the deploy side's field list carries
#: neither -- so it drops both, which is the same hazard as ``secret`` pointed the other
#: way and is tracked separately. Listing them here is not a claim that they travel; it is
#: the honest set of fields SOMETHING in the platform reads, which is what decides whether
#: writing one is a mistake.
PROPERTY_FIELDS = frozenset(
    {
        "type",
        "title",
        "description",
        "format",
        "enum",
        "group",
        "resolvedBy",
        "default",
        "services",
    }
)

#: What ``format`` may say, closed for the same reason ``resolvedBy`` is closed: a typo
#: in an open vocabulary is silently inert, and this is the one field whose value decides
#: whether a value is sealed. ``secret`` routes through sealed custody; ``port`` and
#: ``hostname`` are the narrowed inputs the deploy-target kinds already render; ``plain``
#: is the author saying a credential-shaped name does not hold a credential, which is the
#: one opt-out :data:`CREDENTIAL_NAME_WORDS` accepts -- in the file, in the diff, and
#: greppable, rather than by saying nothing.
FORMAT_VALUES = frozenset({"secret", "port", "hostname", "plain"})

#: Final name segments that mean "this holds a credential". Matched on the last
#: underscore-separated word, so both ``API_TOKEN`` and a bare ``TOKEN`` are read the
#: same way. Deliberately a small, unambiguous list: the check's cost is a one-word
#: opt-out on a false positive, and its value is catching the variable whose declaration
#: forgot the single field that decides whether its value is sealed at rest.
CREDENTIAL_NAME_WORDS = frozenset(
    {"SECRET", "TOKEN", "PASSWORD", "PASSPHRASE", "KEY", "CREDENTIAL", "CREDENTIALS"}
)

_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SERVICE_RE = re.compile(SERVICE_NAME_PATTERN)


def app_env_file_name(service: str | None = None) -> str:
    """The env file a declared variable is rendered into.

    The shared ``.app.env`` when the variable names no service, and ``.app.<service>.env``
    when it does. Both halves of the platform derive the name the same way -- a variable
    rendered into one file and forwarded from another is a value that never arrives, with
    nothing anywhere to say why.
    """
    if not service:
        return APP_ENV_FILE
    return f".app.{service}.env"


def rendered_files(prop: object) -> frozenset[str]:
    """Every env file one declaration's value is rendered into.

    The shared :data:`APP_ENV_FILE` for an unscoped declaration; one
    ``.app.<service>.env`` per named service for a scoped one -- and a declaration naming
    two services renders into BOTH, because compose forwards one file per service and a
    value two services need has to exist in each of their files.

    Lives here rather than in either caller because it is the routing rule itself: the
    checker asks it "which file does this have to arrive through" and the renderer asks it
    "which file do I write this into". Two copies of that answer is precisely the "value
    rendered into one file and forwarded from another" this seam exists to prevent, with
    the disagreement inside one repository instead of between two.
    """
    scope = declared_services(prop)
    if not scope:
        return frozenset({APP_ENV_FILE})
    return frozenset(app_env_file_name(service) for service in scope)


def declared_services(prop: object) -> tuple[str, ...]:
    """The compose services a declaration is scoped to — ``()`` when it names none.

    Tolerant for the same reason ``declared_variables`` is: the verdict on a malformed
    ``"services"`` belongs to ``manifest_findings``, and callers report that first, so
    this only has to answer "which services does the app mean" without raising on a file
    that has already been refused. An unusable entry reads as absent, never as a wider
    scope than the app asked for.
    """
    services = prop.get("services") if isinstance(prop, dict) else None
    if not isinstance(services, list):
        return ()
    return tuple(
        service
        for service in services
        if isinstance(service, str) and _SERVICE_RE.fullmatch(service)
    )


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
    for field in sorted(k for k in prop if isinstance(k, str)):
        if field in PROPERTY_FIELDS or field.startswith("$"):
            continue
        if field == "secret":
            # The mis-key this whole check exists for, named with its exact fix. It is
            # the plausible spelling -- Studio's own GUI calls the concept "secret" and
            # its authoring API takes `secret=True` -- which is why it has to be refused
            # rather than left to be noticed.
            findings.append(
                ManifestFinding(
                    f"{name}.secret",
                    'is not a field this dialect has -- write "format": "secret", which '
                    "is what routes the value through sealed custody; an unrecognised "
                    "key is DROPPED, so this variable would be stored as an ordinary "
                    "shared value in plain records with nothing to say so",
                )
            )
            continue
        findings.append(
            ManifestFinding(
                f"{name}.{field}",
                "is not a field this dialect has, and the deploy side drops what it "
                "does not recognise rather than refusing it -- so a misspelled field "
                f"silently does nothing; use one of {', '.join(sorted(PROPERTY_FIELDS))}",
            )
        )
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
    fmt = prop.get("format")
    # Same shape as the resolvedBy check above, and the same reason: judge the vocabulary
    # only once the value cleared the string/length check, so one mistake is one offence.
    if isinstance(fmt, str) and len(fmt) <= MAX_TEXT and fmt not in FORMAT_VALUES:
        findings.append(
            ManifestFinding(
                f"{name}.format",
                f"is {fmt!r} -- use one of {', '.join(sorted(FORMAT_VALUES))}. Only "
                '"secret" seals a value; every other spelling, including a near miss '
                'like "secrt", is inert and leaves the value in plain records',
            )
        )
    elif (
        fmt is None
        # A property that carries the mis-key has already been told to write
        # `"format": "secret"`, and that is the identical fix -- saying it twice
        # buries the one line the author has to change.
        and "secret" not in prop
        and name.rsplit("_", 1)[-1] in CREDENTIAL_NAME_WORDS
    ):
        findings.append(
            ManifestFinding(
                f"{name}.format",
                'is absent on a credential-shaped name -- declare "format": "secret" so '
                'the value is sealed at rest and write-only in the UI, or "format": '
                '"plain" to record that this one does not hold a credential',
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
    services = prop.get("services")
    if services is not None:
        # One offence per mistake: a list of ten bad names is one thing to fix, and ten
        # repetitions of the same sentence bury the nine other findings in the file.
        if (
            not isinstance(services, list)
            or len(services) > MAX_SERVICES
            or not all(
                isinstance(service, str) and _SERVICE_RE.fullmatch(service)
                for service in services
            )
        ):
            findings.append(
                ManifestFinding(
                    f"{name}.services",
                    f"must be a list of at most {MAX_SERVICES} compose service names "
                    '(lowercase letters, digits, "_", "." and "-"; at most '
                    f"{MAX_SERVICE_NAME} characters)",
                )
            )
        elif not services:
            # An empty list reads like "no service", which is the opposite of what the
            # renderer does with it: nothing forwards `.app.<nothing>.env`, so the
            # variable reaches no container at all.
            findings.append(
                ManifestFinding(
                    f"{name}.services",
                    'is an empty list -- omit "services" for a variable every backend '
                    "service reads, or name the services that read it",
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
