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
  (which is what breaks running two projects at once); a declared environment
  seam the compose file never reads (which is how live source and the framing
  grant arrive, so a stale name breaks hot reload while everything still
  builds, runs and passes); a field only a workbench reads, declared under a
  role no workbench looks up — a line written to be honoured that nothing will
  ever read (:data:`ROLE_RESOLVED_FIELDS`).
* **Never** red: a service nobody declared — Redis, a worker, a virus scanner, a
  second frontend, whatever the app needs; the *absence* of a service we happen
  to know about; three APIs; no frontend at all; an optional container from the
  platform replaced by the app's own equivalent; **a role this file has never
  heard of**, as long as it carries nothing that had to be resolved by name.

The declaration is a **partial** description. Services it does not mention are
not the workbench's business, and an exhaustive list here would be exactly the
restriction this file exists not to impose.

**An app may drive its own loop.** The optional ``commands`` block names how to
start, stop and observe this app when it is not the Compose shape a workbench
assumes — Tilt, a devcontainer, a Makefile, bare processes. Only the *shape* of
those commands is checked: whether ``tilt up`` is the right way to start this app
is not something a file read can know. Declaring the block is what turns "this
app is unmanageable" into "this app is managed differently", which is the
difference between losing a workbench and configuring one. A slot left out is
not filled in from the Compose defaults: an app that has told us it is not
Compose must never have ``docker compose down --volumes`` run against it because
a repair button wanted to exist.

**The escape ships with the rule.** ``{"unmanaged": true, "reason": "..."}``
turns the check off for an app whose dev loop does not fit this shape at all.
A workbench then falls back to its configured commands and says honestly that it
cannot determine the app's status. Per the ideology (ADR 0103): one pattern,
enforced, escapable by proof — and the escape is greppable.

**Dev only, and that is enforced rather than asked for.** This describes
``docker-compose.yml``, the inner loop. A declaration aimed at a deployment
profile is refused outright (``DEPLOYMENT_PROFILE_MARKERS``), because that is
where the freedom real deployments need lives — an external managed database, a
shared estate, a client's own cluster — and gate-enforcing it would take that
freedom away. Stating the rule in prose was not enough: in a codebase written
by agents, a boundary that only a document defends is a boundary the next agent
walks through.

**The words are the Terp Standard's** (ADR 0186). ``workbench-declaration.schema.json``
fixes the vocabulary; :mod:`terp.arch.workbench` carries it as a byte-for-byte mirror and
this module reads every list from there - the versions, the command slots, the roles,
the fields resolved by role, the reserved variable names and the deployment-profile
markers - and applies the schema itself before reading a field. Two readers each wrote
their own copy of these words once, and they disagreed about which command slots
existed.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import yaml

from terp.arch import workbench as vocabulary

#: The declaration's filename. Seeded by the template and then owned by the app
#: (``_skip_if_exists``), because an app with a non-default topology has to be
#: able to say so and keep saying it across upgrades.
WORKBENCH_FILE = vocabulary.WORKBENCH_FILE

#: Versions this reader understands, from the vocabulary. A file from the future is
#: not a failure of the app's -- it means the toolchain is behind, and saying so
#: beats inventing a verdict about fields we cannot read (ADR 0186).
SUPPORTED_VERSIONS = vocabulary.SUPPORTED_VERSIONS

#: The declaration describes the inner loop and must never be pointed at a deploy
#: profile: that is where the freedom real deployments need lives (an external
#: managed database, a shared estate, a client's own cluster), and it lives there
#: precisely because no gate reaches it. Decision 5 of ADR 0110 said so in prose,
#: which for an agent-written codebase is not a control -- nothing stopped the next
#: agent from aiming ``compose.file`` at the deploy profile and quietly turning this
#: check into a gate on how people deploy. So it is a refusal with a message, and the
#: markers that make a file a deployment profile are the vocabulary's.
DEPLOYMENT_PROFILE_MARKERS = vocabulary.DEPLOYMENT_PROFILE_MARKERS


@dataclass(frozen=True)
class Finding:
    """One defect, phrased for whoever has to fix it."""

    message: str
    remedy: str = ""


#: Command slots a workbench understands, from the vocabulary. ``start`` is the
#: only one that makes the block meaningful; the rest are offers, and a workbench
#: must not invent one that is missing. That last point is the whole safety
#: argument for this block: an app that declares its own loop has told us it is not
#: the standard Compose shape, so falling back to ``docker compose down --volumes``
#: for a repair it never declared would run a destructive command nobody asked for
#: against a stack we do not understand.
#:
#: ``containerLogs`` and ``recreate`` were read and run by a workbench for a long
#: time before this list knew them: a slot belongs in the vocabulary first, and the
#: two arrived in the wrong order. Reading the list from the vocabulary is what keeps
#: that from happening again.
COMMAND_SLOTS = vocabulary.COMMAND_SLOTS

#: Roles a workbench resolves by name. Not a vocabulary an app must use: a role
#: outside this set is still information nobody acts on yet, and refusing one
#: outright would make adding a role a breaking change for every app that
#: already shipped.
#:
#: This set was here once and was removed as a fact nobody consumed, on the
#: reading that neither this toolchain nor a workbench looked at a role name.
#: The first half was true and the second was not: a workbench asks its
#: declaration "which service has role ``api``, and where does it answer the
#: readiness question?" -- a lookup by exact string. So the set comes back, and
#: it comes back *with* a reader, which is what the objection to it actually
#: asked for. See :data:`ROLE_RESOLVED_FIELDS`.
KNOWN_ROLES = vocabulary.KNOWN_ROLES

#: Fields whose only reader is a workbench, and which it looks up BY ROLE.
#:
#: These are what make an off-vocabulary role more than a spelling preference.
#: The same line under ``role: "frontend"`` instead of ``role: "web"`` is not a
#: near-miss -- it is a field nothing will ever read, and every symptom of that
#: is silent. The check passes. The workbench finds no entry for the role it
#: asked about, falls back to its own default, and the two agree exactly as long
#: as the declared value happens to equal that default. The day the app renames
#: the variable, the workbench keeps setting the old name and starts a stack it
#: can no longer find -- which is the failure this whole file exists to make
#: visible, arriving through the file itself.
#:
#: Narrow on purpose. An unrecognised role stays fine; an unrecognised role
#: carrying one of these is a claim that cannot be honoured.
ROLE_RESOLVED_FIELDS = vocabulary.ROLE_RESOLVED_FIELDS


@dataclass(frozen=True)
class Declaration:
    """A parsed ``workbench.json``."""

    unmanaged: bool = False
    reason: str = ""
    compose_file: str = vocabulary.DEFAULT_COMPOSE_FILE
    services: tuple[dict[str, Any], ...] = field(default=())
    env: dict[str, str] = field(default_factory=dict)
    #: How a workbench drives this app's development loop, when the app is not
    #: the Compose shape a workbench assumes by default. Empty means "assume
    #: the default", which is what every app rendered from the template wants.
    commands: dict[str, str] = field(default_factory=dict)
    #: Was ``compose.file`` written down, or is :attr:`compose_file` just the
    #: default this reader supplies? Naming a file is itself a claim that it
    #: exists, and an app that named one has to be held to it even when it
    #: declares nothing else.
    compose_declared: bool = False

    @property
    def describes_a_compose_file(self) -> bool:
        """Does this declaration make a claim a compose file has to settle?

        Three ways to make one: name the file, declare a service, or declare an
        env seam. A declaration with commands and none of those describes an app
        whose development loop is not a compose stack at all — demanding a
        compose file from it would be demanding the one thing it has just said
        it does not have.
        """
        return bool(self.compose_declared or self.services or self.env)


def load(project_root: pathlib.Path) -> tuple[Declaration | None, list[Finding]]:
    """Read the declaration. ``(None, [])`` when the app has none.

    ``(None, findings)`` for one that is there and cannot be read: an unreadable
    declaration is not an absent one, and a caller must never serve it the
    defaults an absent one gets (ADR 0186).
    """
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
    return read(raw)


def read(raw: Any) -> tuple[Declaration | None, list[Finding]]:
    """A parsed document as a :class:`Declaration`, or every reason it is refused.

    The schema first, then the refusals it names and cannot state, from the lists
    it names (ADR 0186): a field resolved by role under a role no workbench looks
    up, a variable name the toolchain reads for itself, and a deployment profile.
    """
    if not isinstance(raw, dict):
        return None, [Finding(f"{WORKBENCH_FILE} must contain a JSON object.")]
    unmanaged = raw.get("unmanaged") is True
    if unmanaged and not (isinstance(raw.get("reason"), str) and raw["reason"].strip()):
        return None, [
            Finding(
                f'{WORKBENCH_FILE} sets "unmanaged": true without a "reason".',
                "State why this app's development loop does not fit the "
                "standard shape. An escape without a reason is an escape "
                "nobody can review.",
            )
        ]
    version = raw.get("schemaVersion")
    if (
        isinstance(version, int)
        and not isinstance(version, bool)
        and version not in SUPPORTED_VERSIONS
    ):
        return None, [
            Finding(
                f"{WORKBENCH_FILE} declares schemaVersion {version!r}, which this "
                f"toolchain does not read (it knows {sorted(SUPPORTED_VERSIONS)}).",
                "Upgrade the Terp toolchain, or lower the declared version. A reader "
                "that is behind refuses a later file rather than reading it with an "
                "earlier vocabulary.",
            )
        ]
    findings = [
        Finding(f"{WORKBENCH_FILE}: {problem.path or 'the file'} {problem.detail}.")
        for problem in vocabulary.problems(raw)
    ]
    if findings:
        return None, findings
    if unmanaged:
        return Declaration(unmanaged=True, reason=raw["reason"]), []
    findings = _refusals_beyond_the_schema(raw)
    if findings:
        return None, findings
    compose = raw.get("compose", {})
    return (
        Declaration(
            compose_file=compose.get("file", vocabulary.DEFAULT_COMPOSE_FILE),
            services=tuple(raw["services"]),
            env=dict(raw.get("env", {})),
            commands={
                slot: line.strip()
                for slot, line in raw.get("commands", {}).items()
                if slot in COMMAND_SLOTS
            },
            compose_declared="file" in compose,
        ),
        [],
    )


def _refusals_beyond_the_schema(raw: dict[str, Any]) -> list[Finding]:
    """What the schema names and its keyword subset cannot state, in document order."""
    findings: list[Finding] = []
    for index, entry in enumerate(raw["services"]):
        findings.extend(_role_findings(entry["service"], entry.get("role", ""), entry))
        findings.extend(_name_findings(f"services[{index}].hostPortEnv", entry.get("hostPortEnv")))
    for label, name in raw.get("env", {}).items():
        findings.extend(_name_findings(f"env.{label}", name))
    compose_file = raw.get("compose", {}).get("file", "")
    if vocabulary.names_a_deployment_profile(compose_file):
        findings.append(
            Finding(
                f"{WORKBENCH_FILE} points at {compose_file!r}, which is a deployment profile.",
                "This declaration describes the development loop only. How an app "
                "deploys is deliberately ungated -- an external managed database, a "
                "shared estate, a client's own cluster, and checking it here would take "
                'that freedom away. Point "compose.file" at the development compose '
                'file, or set {"unmanaged": true, "reason": "..."} if this app has no '
                "development compose file at all.",
            )
        )
    return findings


def _name_findings(where: str, name: str | None) -> list[Finding]:
    """A variable a workbench would set, under a name the toolchain reads for itself.

    A workbench puts every declared name into the environment of the commands it
    runs, and a name such as ``PATH`` or ``DOCKER_CONFIG`` then decides which
    program those commands are, or where they read their configuration from --
    steered by a file an agent writes.
    """
    why = vocabulary.reserved_name(name) if name else ""
    if not why:
        return []
    return [
        Finding(
            f"{WORKBENCH_FILE} declares {where} as {name}: {why}.",
            "A workbench sets this variable in the environment of the commands it "
            "runs, so the name must be the app's own. Rename the variable in the "
            "compose file and here.",
        )
    ]


def _published_host_ports(service: dict[str, Any]) -> list[str]:
    """The host side of each *fixed* published port, as written.

    A short-syntax entry with no colon (``"5173"``) names a container port and
    leaves the host one to the daemon. An ephemeral port cannot collide, so it
    is not a fixed host port and must not read as one — flagging it would fail
    an app over the very thing that makes running two projects at once safe.
    The long syntax says the same by omitting ``published``.
    """
    ports = service.get("ports")
    if not isinstance(ports, list):
        return []
    published: list[str] = []
    for entry in ports:
        if isinstance(entry, str) and ":" in entry:
            published.append(entry.rsplit(":", 1)[0])
        elif isinstance(entry, dict) and "published" in entry:
            published.append(str(entry["published"]))
    return published


def _strings(node: Any) -> Iterator[str]:
    """Every string anywhere in the parsed compose file."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def _interpolates(compose: dict[str, Any], name: str) -> bool:
    """Does the compose file read ``${name}`` anywhere at all?

    Deliberately not "in the right place". Which service needs the source root
    mounted, and which needs the framing grant, is the app's business; that the
    variable it *declared* is read somewhere is the claim being checked.
    """
    needle = "${" + name
    return any(needle in value for value in _strings(compose))


def _role_findings(name: str, role: str, entry: dict[str, Any]) -> list[Finding]:
    """A field a workbench resolves by role, declared under a role it never asks for.

    The two halves both have to be true before this says anything, and that is
    the whole design. An unrecognised role on its own is information; a
    recognised role carrying these fields is the ordinary case. Only the
    combination is a line written to be honoured that nothing will read — and
    unlike every other defect in this file, it has no symptom at all until the
    declared value and the workbench's own default finally differ.
    """
    if not role or role in KNOWN_ROLES:
        return []
    addressed = [key for key in ROLE_RESOLVED_FIELDS if entry.get(key)]
    if not addressed:
        return []
    return [
        Finding(
            f"{WORKBENCH_FILE} declares {', '.join(addressed)} for service "
            f"{name!r} under role {role!r}, which no workbench looks up.",
            "A workbench resolves these fields BY ROLE, so under a role it does "
            "not know they are never read: it falls back to its own default and "
            "this line is decorative until the day the two disagree. Use one of "
            f"{', '.join(sorted(KNOWN_ROLES))}, or drop the field if no tool "
            "needs to carry it.",
        )
    ]


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
                    "A fixed host port means two projects cannot run at once -- "
                    f'use "${{{port_env}:-<default>}}:<container port>" in the '
                    "compose file, or correct the declaration.",
                )
            )
    # The `env` half of the declaration is load-bearing in exactly the way the
    # `services` half is, and it went unchecked: the source root is how live
    # source reaches the containers and the framing grant is how the preview is
    # allowed to embed the app, so a name the compose file stopped reading is a
    # seam that silently is not there. Hot reload dies and the app still builds,
    # still runs, and still passes every other check — which is the whole class
    # of failure this file exists to make visible.
    for label, name in sorted(declared.env.items()):
        if not name or _interpolates(compose, name):
            continue
        findings.append(
            Finding(
                f'{WORKBENCH_FILE} declares "{label}" as ${{{name}}}, but '
                f"{declared.compose_file} never reads it.",
                f"Reference ${{{name}}} in the compose file where that value "
                "has to arrive, or drop the entry: a declared seam the compose "
                "file does not read is a seam that does not exist.",
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
        if not declared.describes_a_compose_file:
            # Commands and nothing else: an app whose development loop is not a
            # compose stack. There is no file to audit, and that is the answer
            # rather than a failure.
            return 0, (
                f"{WORKBENCH_FILE}: this app drives its own development loop "
                f"({', '.join(sorted(declared.commands))})"
            )
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
        loop = (
            f"; drives its own loop ({', '.join(sorted(declared.commands))})"
            if declared.commands
            else ""
        )
        return 0, (
            f"{WORKBENCH_FILE}: {len(declared.services)} declared service(s) match "
            f"{declared.compose_file}{loop}"
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
