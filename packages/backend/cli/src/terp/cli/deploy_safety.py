"""``terp verify --only deploy-safety`` — the deployment safety envelope.

The inner loop and a deployment fail in opposite directions, and that is the
whole reason this file is not the workbench check.

A misconfigured development stack does not come up, and you find out in seconds.
A misconfigured deployment comes up *perfectly* and you find out from a bill, a
breach notification, or a column that is no longer there. So the workbench
check's rule — *did you tell the truth about yourself* — is the right rule
there and an insufficient one here: a declaration cannot help when the danger is
not a lie. ``POSTGRES_PASSWORD: hunter2`` is a completely truthful, checkable
statement of a catastrophe.

**What this constrains, and what it deliberately does not.** Properties, never
topology. An app may use any containers, any networking, any provider, any
architecture and satisfy every invariant here — which is what makes an enforced
envelope compatible with the freedom ADR 0013 protects rather than a
contradiction of it. Nothing in this file asks how many services there are, what
they run, which of them exist, or whether the platform's own images are among
them.

**Why conformance is right here and nowhere else.** The audience is people
building applications through an agent who cannot themselves evaluate a security
trade-off, and networking, secrets and blast radius are exactly such trade-offs.
That is the justification ADR 0103 already gives for enforcing security
invariants by default, applied to the one surface that had none.

**The escape is per-thing, in the file, with a reason.** A Compose ``x-``
extension field on the service it excuses::

    db:
      image: postgres:17-alpine
      ports: ["5432:5432"]
      x-terp-allow:
        published-datastore: "single-tenant appliance on a private VLAN"

Docker Compose ignores ``x-`` fields, so this costs the app nothing at runtime.
It is greppable, it sits on the thing it forgives rather than in a distant
allowlist, and it arrives in the same diff as the risk it accepts. A reason is
required: an escape nobody can review is a hole.

**Two invariants, not five.** The envelope this file implements is smaller than
the one proposed in ADR 0111, on purpose. "Every stateful resource names a
backup", "TLS terminated at the edge" and "a destructive scope requires
confirmation" are not decidable from a compose file — the first two live in
infrastructure this artifact does not describe, and the third is a property of a
workbench's own screens. Inventing a check for them here would be theatre, and a
gate that pretends to cover what it does not is worse than an honest gap.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass
from typing import Any

import yaml

#: The deployment profile the template generates. An app with none of these
#: passes as a no-op, like every other generator-backed check: adopting the
#: toolchain must never redden a gate over a file the app does not have.
DEPLOY_PROFILES = ("docker-compose.prod.yml",)

#: The Compose extension field carrying an accepted risk. ``x-`` prefixed
#: fields are ignored by Compose itself, so the escape costs nothing at runtime.
ALLOW_FIELD = "x-terp-allow"

#: Image families that hold state somebody would mind losing or leaking. Named
#: rather than inferred: this is the conformance layer, so recognising a
#: datastore by what it *is* rather than by what the app *said* is the point --
#: an undeclared database is exactly the one a declaration would not catch.
#: A family this list does not know is not flagged, which is the honest
#: consequence of a closed list and the reason it errs toward the common ones.
DATASTORE_IMAGES = (
    "postgres",
    "mysql",
    "mariadb",
    "mongo",
    "redis",
    "valkey",
    "memcached",
    "elasticsearch",
    "opensearch",
    "clickhouse",
    "cassandra",
    "couchdb",
    "influxdb",
    "neo4j",
    "rabbitmq",
    "kafka",
    "minio",
)

#: Environment names whose value is a credential. Precise on purpose: a broad
#: match like ``_KEY`` would flag half of every compose file and teach people to
#: reach for the escape hatch, which is how a gate stops meaning anything.
SECRET_NAME_HINTS = (
    "SECRET",
    "PASSWORD",
    "PASSPHRASE",
    "TOKEN",
    "CREDENTIAL",
    "PRIVATE_KEY",
    "API_KEY",
)

#: ``${NAME:-default}``. The default is what matters: a *weak default* for a
#: credential is a literal secret that looks like an interpolation, and it is
#: the version of this mistake that survives review.
_DEFAULTED = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*:-([^}]*)\}")


@dataclass(frozen=True)
class Finding:
    """One accepted-risk-shaped defect, phrased for whoever has to fix it."""

    invariant: str
    message: str
    remedy: str = ""


def _allowed(service: dict[str, Any], invariant: str) -> str:
    """The reason this service is excused from *invariant*, or ``""``."""
    allow = service.get(ALLOW_FIELD)
    if not isinstance(allow, dict):
        return ""
    reason = allow.get(invariant)
    return reason.strip() if isinstance(reason, str) else ""


def _image_family(service: dict[str, Any]) -> str:
    """The bare image name, without registry, tag or digest."""
    image = service.get("image")
    if not isinstance(image, str) or not image:
        return ""
    name = image.split("@", 1)[0]
    name = name.rsplit("/", 1)[-1]
    return name.split(":", 1)[0].lower()


def _publishes(service: dict[str, Any]) -> list[str]:
    """The host side of each *fixed* published port, as written.

    An entry with no host side gets an ephemeral port, which is still reachable
    and therefore still counts here -- unlike in the workbench check, where the
    question was collision rather than exposure.
    """
    ports = service.get("ports")
    if not isinstance(ports, list):
        return []
    published: list[str] = []
    for entry in ports:
        if isinstance(entry, str):
            published.append(entry)
        elif isinstance(entry, dict):
            published.append(str(entry.get("published", entry.get("target", ""))))
    return [entry for entry in published if entry]


def _environment(service: dict[str, Any]) -> dict[str, str]:
    """``environment:`` as a mapping, from either Compose form."""
    raw = service.get("environment")
    if isinstance(raw, dict):
        return {str(k): "" if v is None else str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        pairs: dict[str, str] = {}
        for entry in raw:
            if isinstance(entry, str) and "=" in entry:
                key, _, value = entry.partition("=")
                pairs[key.strip()] = value
        return pairs
    return {}


def _names_a_secret(key: str) -> bool:
    upper = key.upper()
    if upper.endswith("_FILE"):
        # The Docker secrets convention: the value is a path to the credential,
        # not the credential. Flagging it would push people away from the safe
        # pattern, which is the opposite of the point.
        return False
    return any(hint in upper for hint in SECRET_NAME_HINTS)


def audit(compose: dict[str, Any]) -> list[Finding]:
    """Check one parsed deployment profile against the envelope.

    Pure, so the whole envelope is testable without a filesystem -- and so it can
    later be run against a *resolved* plan (``docker compose config``) rather
    than a source file, which is where this check ultimately belongs: an agent
    can satisfy a file and still deploy something dangerous, because the danger
    is in the rendered result.
    """
    services = compose.get("services")
    if not isinstance(services, dict):
        return []
    findings: list[Finding] = []
    for name in sorted(services):
        service = services[name]
        if not isinstance(service, dict):
            continue
        findings.extend(_datastore_exposure(name, service))
        findings.extend(_literal_secrets(name, service))
    return findings


def _datastore_exposure(name: str, service: dict[str, Any]) -> list[Finding]:
    family = _image_family(service)
    if not any(family.startswith(known) for known in DATASTORE_IMAGES):
        return []
    published = _publishes(service)
    if not published:
        return []
    if _allowed(service, "published-datastore"):
        return []
    return [
        Finding(
            "published-datastore",
            f"Service {name!r} runs {family} and publishes {published[0]!r} on "
            "the host.",
            "A datastore reachable from outside the compose network is the "
            "single most common way application data leaves a deployment. "
            "Reach it over the internal network by service name instead, or, "
            "if this really is intended, accept the risk in the file:\n"
            f"      {ALLOW_FIELD}:\n"
            "        published-datastore: \"why this is safe here\"",
        )
    ]


def _literal_secrets(name: str, service: dict[str, Any]) -> list[Finding]:
    excused = _allowed(service, "literal-secret")
    findings: list[Finding] = []
    for key, value in sorted(_environment(service).items()):
        if not _names_a_secret(key) or not value.strip() or excused:
            continue
        if "${" not in value:
            findings.append(
                Finding(
                    "literal-secret",
                    f"Service {name!r} sets {key} to a literal value.",
                    "A credential written into a compose file is a credential "
                    "in version control, in every clone of it, and in its whole "
                    f"history. Take it from the environment instead: "
                    f"``{key}: ${{{key}:?{key} is required}}`` fails the deploy "
                    "loudly when it is missing, which is the behaviour you want.",
                )
            )
            continue
        weak = [
            default
            for default in _DEFAULTED.findall(value)
            if default.strip() and "${" not in default
        ]
        if weak:
            findings.append(
                Finding(
                    "literal-secret",
                    f"Service {name!r} gives {key} the fallback value "
                    f"{weak[0]!r}.",
                    "A default credential is a literal credential that looks "
                    "like an interpolation, and it is the version of this "
                    f"mistake that survives review. Use ``${{{key}:?{key} is "
                    "required}}`` so a missing value stops the deploy instead "
                    "of silently shipping a known one.",
                )
            )
    return findings


def run_deploy_safety_check(project_root: pathlib.Path) -> tuple[int, str]:
    """The ``deploy-safety`` verify runner: ``(exit_code, output)``."""
    profiles = [
        path
        for path in (project_root / name for name in DEPLOY_PROFILES)
        if path.is_file()
    ]
    if not profiles:
        return 0, (
            "no deployment profile found "
            f"({', '.join(DEPLOY_PROFILES)}) - nothing to check"
        )
    findings: list[Finding] = []
    for path in profiles:
        try:
            compose = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            return 1, _render([Finding("unreadable", f"{path.name}: {exc}")])
        findings.extend(audit(compose))
    if not findings:
        return 0, (
            f"{', '.join(path.name for path in profiles)}: no datastore is "
            "published and no credential is literal"
        )
    return 1, _render(findings)


def _render(findings: list[Finding]) -> str:
    lines = [
        "This deployment would ship something that cannot be taken back.",
        "",
        "Only SAFETY is checked here, never shape: how many services you run,",
        "what they are, how they are wired and where they deploy are yours to",
        "decide, and nothing in this check asks. What it will not let past is a",
        "datastore reachable from outside, or a credential written into a file",
        "that lives in version control for ever.",
        "",
    ]
    for finding in findings:
        lines.append(f"- [{finding.invariant}] {finding.message}")
        if finding.remedy:
            lines.extend(f"  {line}" for line in finding.remedy.split("\n"))
    return "\n".join(lines)
