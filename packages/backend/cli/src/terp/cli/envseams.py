"""``terp verify --only env-seams`` — which seam actually supplies a declared variable.

An app declares its run-time variables in ``environment.schema.json``; Studio renders
exactly those declarations into a per-environment ``.app.env``, and the compose profiles
forward that file. That is the seam the generated AGENTS.md tells apps never to edit by
hand, because Studio owns environment-specific values.

Compose resolves a service's ``environment:`` mapping **over** its ``env_file:`` list. So
the moment a declared name also appears under ``environment:``, the rendered ``.app.env``
stops reaching the container — silently, with no warning from compose and nothing in the
gate. Worse than a stale override: ``FOO: ${FOO:-}`` sets ``FOO`` to the empty string on a
machine that has no ``.env`` at all, so there is no configuration in which the declared
value wins. A literal (``FOO: http://api:8000``) discards it just as completely; scanning
only for ``${...}`` would miss the shape apps reach for most.

The two facts needed to say this are already checked in — the manifest and the compose
files — so the verdict needs no Docker daemon, no ``docker`` binary, and no rendered
``.app.env``. It is a plain read of two files. (``docker compose config`` is a worse
oracle here despite being daemon-free: it *inlines* ``env_file`` into ``environment`` and
drops the key, erasing the very distinction this check reports.)

The second finding uses the manifest's ``resolvedBy`` annotation. An address is resolved
either by the host, by a container on the compose network, or by the browser, and one
value cannot be right for two of them: ``127.0.0.1:8000`` is the API from the host and the
container's *own* loopback from inside the network. That distinction is not derivable from
a variable's name or type, so the manifest states it and this check enforces it.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass
from urllib.parse import urlparse

#: The app's declared-variable manifest, at the project root.
APP_ENV_SCHEMA_FILE = "environment.schema.json"

#: The file Studio renders the declared values into; the compose profiles forward it.
APP_ENV_FILE = ".app.env"

#: Where a declared variable's value is resolved. ``host`` and ``browser`` addresses are
#: reached from outside the compose network (a developer's shell, a redirected browser);
#: ``container`` addresses are dialled by a service on the network, where a loopback host
#: means the container itself.
RESOLVED_BY_VALUES = frozenset({"host", "container", "browser"})

#: Hosts that mean "this machine" — inside a container, that is the container. A list of
#: addresses to DETECT, not one to bind (ruff's S104 reads the literal, not its use).
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"})  # noqa: S104

#: ``${VAR}`` / ``${VAR:-default}`` — a value compose interpolates from its own
#: environment (which is the developer's `.env`, or the default, never `.app.env`).
_INTERPOLATION = re.compile(r"\$\{[^}]+\}")


@dataclass(frozen=True)
class EnvSeamFinding:
    """One variable whose seam is not the one the app was told it would be.

    Grouped per (variable, file, how) with every affected service listed, never one
    finding per service: a variable on a shared backend anchor lands in every service
    that merges it, and six repetitions of one fact -- with the fix recipe restated each
    time -- buries the four things actually wrong. One offence, named once.
    """

    variable: str
    source: str
    #: Compose services carrying the override; empty for a non-compose source.
    services: tuple[str, ...]
    detail: str
    #: ``shadowed`` (a compose block outranks .app.env) or ``loopback`` (the value
    #: names this container). They have different fixes, so the report must not offer
    #: one of them for the other.
    kind: str = "shadowed"


def _load_compose(path: pathlib.Path) -> dict:
    """Parse a compose file as data (anchors and ``<<:`` merge keys resolved by PyYAML)."""
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def compose_files(project_root: pathlib.Path) -> list[pathlib.Path]:
    """Every compose profile at the project root, in a stable order.

    Discovered rather than a named list, for the reason the lockstep walk learned: the
    template ships two profiles today (workbench and production) and an app may add an
    override, and a check that named only the ones we shipped would leave the rest
    outside the ratchet.
    """
    return sorted(
        path for path in project_root.glob("docker-compose*.y*ml") if path.is_file()
    )


def _service_environment(service: object) -> dict[str, str]:
    """A service's ``environment:`` as a name -> value map (mapping or ``KEY=value`` list)."""
    if not isinstance(service, dict):
        return {}
    declared = service.get("environment")
    if isinstance(declared, dict):
        return {str(k): "" if v is None else str(v) for k, v in declared.items()}
    if isinstance(declared, list):
        entries: dict[str, str] = {}
        for item in declared:
            name, _, value = str(item).partition("=")
            entries[name] = value
        return entries
    return {}


def _forwards_app_env(service: object) -> bool:
    """Whether the service forwards ``.app.env`` (short or long ``env_file`` form)."""
    if not isinstance(service, dict):
        return False
    declared = service.get("env_file")
    entries = declared if isinstance(declared, list) else [declared]
    for entry in entries:
        path = entry.get("path") if isinstance(entry, dict) else entry
        if isinstance(path, str) and pathlib.PurePosixPath(path).name == APP_ENV_FILE:
            return True
    return False


def read_declared_variables(project_root: pathlib.Path) -> dict[str, dict]:
    """The app's declared variables, or ``{}`` when it declares none.

    Tolerant by design: an unusable manifest is Studio's verdict to give (it fails the
    deploy closed with a directive message), not a reason for this check to turn an app's
    gate red on a file it merely could not parse.
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


def _read_env_file(path: pathlib.Path) -> dict[str, str]:
    """A ``KEY=value`` file as a map; absent or unreadable is empty (both are normal)."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, separator, value = stripped.partition("=")
        if separator:
            values[name.strip()] = value.strip().strip("'\"")
    return values


def _is_loopback(value: str) -> bool:
    """Whether *value* addresses the local machine (URL, ``host:port``, or bare host)."""
    candidate = value.strip()
    if not candidate:
        return False
    if "//" in candidate:
        host = urlparse(candidate).hostname
        return host is not None and host.lower() in _LOOPBACK_HOSTS
    # Bare `host:port` or a hostname on its own.
    host = candidate.rsplit(":", 1)[0] if candidate.count(":") == 1 else candidate
    return host.lower() in _LOOPBACK_HOSTS


def _shadowing_findings(
    project_root: pathlib.Path, declared: dict[str, dict]
) -> list[EnvSeamFinding]:
    """Declared variables a compose ``environment:`` block overrides."""
    findings: list[EnvSeamFinding] = []
    for compose_path in compose_files(project_root):
        rel = compose_path.relative_to(project_root).as_posix()
        try:
            compose = _load_compose(compose_path)
        except Exception:  # noqa: BLE001, S112 - unreadable YAML is not this check's verdict
            continue
        services = compose.get("services")
        if not isinstance(services, dict):
            continue
        # (variable, how) -> the services carrying it. A shared backend anchor puts the
        # same override on every service that merges it: one offence, not six.
        overrides: dict[tuple[str, str], list[str]] = {}
        for service_name, service in sorted(services.items()):
            if not _forwards_app_env(service):
                # Without the .app.env seam there is nothing for this to shadow.
                continue
            environment = _service_environment(service)
            for variable in sorted(set(environment) & set(declared)):
                value = environment[variable]
                how = (
                    f"forwarded from the host environment as `{value}`"
                    if _INTERPOLATION.search(value)
                    else f"hardcoded as `{value}`"
                )
                overrides.setdefault((variable, how), []).append(service_name)
        for (variable, how), service_names in sorted(overrides.items()):
            findings.append(
                EnvSeamFinding(
                    variable=variable,
                    source=rel,
                    services=tuple(service_names),
                    detail=how,
                )
            )
    return findings


def _loopback_findings(
    project_root: pathlib.Path, declared: dict[str, dict]
) -> list[EnvSeamFinding]:
    """Container-resolved variables carrying an address that means "this container"."""
    # Seams in the order compose lets them win, so the message names the file that
    # actually lands the value rather than the first one that merely mentions it.
    app_env = _read_env_file(project_root / APP_ENV_FILE)
    dot_env = _read_env_file(project_root / ".env")
    findings: list[EnvSeamFinding] = []
    for variable, prop in sorted(declared.items()):
        if prop.get("resolvedBy") != "container":
            continue
        for source, value in (
            (APP_ENV_FILE, app_env.get(variable)),
            (".env", dot_env.get(variable)),
            (f"{APP_ENV_SCHEMA_FILE} default", prop.get("default")),
        ):
            if not isinstance(value, str) or not _is_loopback(value):
                continue
            findings.append(
                EnvSeamFinding(
                    variable=variable,
                    source=source,
                    services=(),
                    detail=(
                        f'declared "resolvedBy": "container" but set to `{value}` -- a '
                        "loopback address, which inside a container is that container "
                        "itself, not the service it means to reach. Use the compose "
                        "service name (e.g. http://api:8000); a host address belongs in "
                        'a "resolvedBy": "host" variable'
                    ),
                    kind="loopback",
                )
            )
            break  # The first seam that supplies a value is the one that lands.
    return findings


def env_seam_findings(project_root: pathlib.Path) -> list[EnvSeamFinding]:
    """Every declared variable whose value cannot arrive through the seam it was promised."""
    declared = read_declared_variables(project_root)
    if not declared:
        return []
    return [
        *_shadowing_findings(project_root, declared),
        *_loopback_findings(project_root, declared),
    ]


def run_env_seams_check(project_root: pathlib.Path) -> tuple[int, str]:
    """The ``env-seams`` verify runner: ``(exit_code, output)``.

    A no-op success for an app that declares nothing — the same shape ``routes-drift``
    has for an unadopted generator. Upgrading the framework must not turn an app's gate
    red for a manifest it has not filled in.
    """
    if not (project_root / APP_ENV_SCHEMA_FILE).is_file():
        return 0, f"no {APP_ENV_SCHEMA_FILE} - app-declared variables not applicable"
    declared = read_declared_variables(project_root)
    if not declared:
        return 0, f"{APP_ENV_SCHEMA_FILE} declares no variables - nothing to shadow"
    findings = env_seam_findings(project_root)
    if not findings:
        return 0, (
            f"{len(declared)} declared variable(s) reach the app through {APP_ENV_FILE}"
        )
    lines = [
        f"{len(findings)} app-declared variable(s) cannot arrive through the seam "
        f"{APP_ENV_SCHEMA_FILE} promises.",
        "",
    ]
    for source in sorted({finding.source for finding in findings}):
        lines.append(f"  {source}")
        for finding in findings:
            if finding.source != source:
                continue
            lines.append(f"    {finding.variable}: {finding.detail}")
            if finding.services:
                lines.append(f"      in: {', '.join(finding.services)}")
    # The two kinds have different fixes; offering the precedence recipe for a loopback
    # value would be a confident answer to a question nobody asked.
    if any(finding.kind == "shadowed" for finding in findings):
        lines += [
            "",
            "Compose resolves `environment:` over `env_file:`, so a name in both is",
            f"supplied by the developer's .env (or a compose default) and never by the",
            f"{APP_ENV_FILE} Studio renders -- in every environment, including one with no",
            ".env at all, where `${VAR:-}` still wins with an empty string.",
            "",
            f"Fix: remove the variable from that `environment:` block -- {APP_ENV_FILE} is",
            "its seam. Keep it in compose only if the app owns the value there, and then",
            f"drop it from {APP_ENV_SCHEMA_FILE} (one owner per variable).",
        ]
    lines.append("See: terp guide environment")
    return 1, "\n".join(lines)
