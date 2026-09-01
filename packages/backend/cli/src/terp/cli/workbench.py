"""``terp verify --only workbench`` — is the dev topology still what it says it is?

An app's ``docker-compose.yml`` is edited constantly, and increasingly by agents
rather than by hand. Most of it is the app's own business. A small part of it is
*load-bearing*: which service serves the interface, which serves the API, and
through which environment variables the host ports arrive. Nothing recorded that
distinction, so nothing could tell an agent it had just broken it — and the
symptom surfaced much later, as a preview that would not come up.

``workbench.json`` records it, and this checks the record against reality.

**What this is not.** It is not a conformance gate on what kind of application
you may build. The rule it enforces is *did you tell the truth about yourself*,
never *are you built the approved way*. Concretely:

* Red: a declared role points at a service that does not exist; a declared
  service publishes a hard-coded host port instead of the variable it declared
  (which is what breaks running two projects at once).
* **Never** red: a service nobody declared — Redis, a worker, a virus scanner, a
  second frontend, whatever the app needs; the *absence* of a service we happen
  to know about; three APIs; no frontend at all; an optional container from the
  platform replaced by the app's own equivalent.

The declaration is a **partial** description. Services it does not mention are
not the workbench's business, and an exhaustive list here would be exactly the
restriction this file exists not to impose.

**The escape ships with the rule.** ``{"unmanaged": true, "reason": "..."}``
turns the check off for an app whose dev loop does not fit this shape at all.
A workbench then falls back to its configured commands and says honestly that it
cannot determine the app's status. Per the ideology (ADR 0103): one pattern,
enforced, escapable by proof — and the escape is greppable.

**Dev only.** This describes ``docker-compose.yml``, the inner loop. It must
never be consulted for, validated against, or extended to the production
profile: that is where the freedom real deployments need lives, and gate-enforcing
it would take that freedom away.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Any

import yaml

#: The declaration's filename. Seeded by the template and then owned by the app
#: (``_skip_if_exists``), because an app with a non-default topology has to be
#: able to say so and keep saying it across upgrades.
WORKBENCH_FILE = "workbench.json"

#: Versions this reader understands. A file from the future is not a failure of
#: the app's — it means the toolchain is behind, and saying so beats inventing a
#: verdict about fields we cannot read.
SUPPORTED_VERSIONS = frozenset({1})

#: Roles with a defined meaning to a workbench. A role outside this set is not
#: an error — it is simply information no workbench acts on yet, and refusing it
#: would make adding one a breaking change for every existing app.
KNOWN_ROLES = frozenset({"web", "api", "one-shot", "database", "worker"})


@dataclass(frozen=True)
class Finding:
    """One defect, phrased for whoever has to fix it."""

    message: str
    remedy: str = ""


@dataclass(frozen=True)
class Declaration:
    """A parsed ``workbench.json``."""

    unmanaged: bool = False
    reason: str = ""
    compose_file: str = "docker-compose.yml"
    services: tuple[dict[str, Any], ...] = field(default=())
    env: dict[str, str] = field(default_factory=dict)


def load(project_root: pathlib.Path) -> tuple[Declaration | None, list[Finding]]:
    """Read the declaration. ``(None, [])`` when the app has none."""
    path = project_root / WORKBENCH_FILE
    if not path.is_file():
        return None, []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [
            Finding(
                f"{WORKBENCH_FILE} could not be read: {exc}",
                "Fix the JSON, or delete the file to opt out of this check.",
            )
        ]
    if not isinstance(raw, dict):
        return None, [Finding(f"{WORKBENCH_FILE} must contain a JSON object.")]
    if raw.get("unmanaged") is True:
        reason = str(raw.get("reason") or "")
        if not reason.strip():
            return None, [
                Finding(
                    f'{WORKBENCH_FILE} sets "unmanaged": true without a "reason".',
                    "State why this app's development loop does not fit the "
                    "standard shape. An escape without a reason is an escape "
                    "nobody can review.",
                )
            ]
        return Declaration(unmanaged=True, reason=reason), []
    version = raw.get("schemaVersion")
    if version not in SUPPORTED_VERSIONS:
        return None, [
            Finding(
                f"{WORKBENCH_FILE} declares schemaVersion {version!r}, which this "
                f"toolchain does not read (it knows {sorted(SUPPORTED_VERSIONS)}).",
                "Upgrade the Terp toolchain, or lower the declared version.",
            )
        ]
    services = raw.get("services")
    if not isinstance(services, list) or not all(
        isinstance(entry, dict) for entry in services
    ):
        return None, [
            Finding(f'{WORKBENCH_FILE} needs a "services" list of objects.')
        ]
    compose = raw.get("compose")
    compose_file = "docker-compose.yml"
    if isinstance(compose, dict) and isinstance(compose.get("file"), str):
        compose_file = compose["file"]
    env = raw.get("env")
    return (
        Declaration(
            compose_file=compose_file,
            services=tuple(services),
            env={
                str(key): str(value)
                for key, value in (env.items() if isinstance(env, dict) else ())
            },
        ),
        [],
    )


def _published_host_ports(service: dict[str, Any]) -> list[str]:
    """The host side of each published port, as written."""
    ports = service.get("ports")
    if not isinstance(ports, list):
        return []
    published: list[str] = []
    for entry in ports:
        if isinstance(entry, str):
            published.append(entry.rsplit(":", 1)[0] if ":" in entry else entry)
        elif isinstance(entry, dict) and "published" in entry:
            published.append(str(entry["published"]))
    return published


def audit(declared: Declaration, compose: dict[str, Any]) -> list[Finding]:
    """Check the declaration against the compose file it describes.

    Only the two claims that can actually be wrong in a way that matters are
    checked, and both are about the declaration rather than about the app's
    design. Everything the declaration does not mention is left alone — that
    is the rule, not an omission.
    """
    services = compose.get("services")
    if not isinstance(services, dict):
        return [Finding("The compose file declares no services.")]
    findings: list[Finding] = []
    for entry in declared.services:
        name = str(entry.get("service") or "")
        role = str(entry.get("role") or "")
        if not name:
            findings.append(
                Finding(f'{WORKBENCH_FILE} has an entry with no "service" name.')
            )
            continue
        if name not in services:
            findings.append(
                Finding(
                    f"{WORKBENCH_FILE} declares the {role or 'unnamed'} role as "
                    f"service {name!r}, which {declared.compose_file} does not define.",
                    "Point the declaration at the service that actually plays "
                    "this role, or drop the entry if nothing does.",
                )
            )
            continue
        port_env = entry.get("hostPortEnv")
        if not isinstance(port_env, str) or not port_env:
            continue
        published = _published_host_ports(services[name])
        if not published:
            # Declaring a port variable for a service that publishes nothing is
            # a stale declaration, not a broken app: say so, do not fail.
            continue
        if not any(f"${{{port_env}" in value for value in published):
            findings.append(
                Finding(
                    f"Service {name!r} publishes host port {published[0]!r}, but "
                    f"{WORKBENCH_FILE} says its host port comes from ${{{port_env}}}.",
                    "A fixed host port means two projects cannot run at once — "
                    f'use "${{{port_env}:-<default>}}:<container port>" in the '
                    "compose file, or correct the declaration.",
                )
            )
    return findings


def run_workbench_check(project_root: pathlib.Path) -> tuple[int, str]:
    """The ``workbench`` verify runner: ``(exit_code, output)``.

    A no-op success for an app with no declaration — the same shape the other
    generator-backed checks have. Upgrading the toolchain must never turn an
    app's gate red over a file it has not adopted.
    """
    declared, defects = load(project_root)
    if defects:
        return 1, _render(defects)
    if declared is None:
        return 0, f"no {WORKBENCH_FILE} - development topology not declared"
    if declared.unmanaged:
        return 0, (
            f"{WORKBENCH_FILE} declares this app unmanaged: {declared.reason}\n"
            "A workbench will fall back to its configured commands and report "
            "that it cannot determine this app's status."
        )
    compose_path = project_root / declared.compose_file
    if not compose_path.is_file():
        return 1, _render(
            [
                Finding(
                    f"{WORKBENCH_FILE} names {declared.compose_file!r}, which does "
                    "not exist.",
                )
            ]
        )
    try:
        compose = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        return 1, _render([Finding(f"{declared.compose_file} is unreadable: {exc}")])
    findings = audit(declared, compose)
    if not findings:
        return 0, (
            f"{WORKBENCH_FILE}: {len(declared.services)} declared service(s) match "
            f"{declared.compose_file}"
        )
    return 1, _render(findings)


def _render(findings: list[Finding]) -> str:
    lines = [
        "The development topology this app declares does not match the one it has.",
        "",
        "Only what the declaration CLAIMS is checked -- services it does not",
        "mention are not the workbench's business, and adding your own is always",
        "fine. Two ways out: correct the declaration, or, if this app's dev loop",
        'does not fit the standard shape at all, set {"unmanaged": true,',
        '"reason": "..."} and a workbench will stop trying to interpret it.',
        "",
    ]
    for finding in findings:
        lines.append(f"- {finding.message}")
        if finding.remedy:
            lines.append(f"  {finding.remedy}")
    return "\n".join(lines)
