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

The fourth finding is the one file in this seam that a human maintains by hand.
``terp guide environment`` instructs the app to add a workbench value to
``.app.env.example`` so the inner loop runs the deployed seam, and until now nothing
opened that file: the check read the manifest and the compose profiles only. So the one
artifact with no renderer behind it -- Studio quotes and escapes every value it writes,
the example file is typed -- was also the only one nothing validated. A declared name
missing from it means ``cp .app.env.example .app.env`` produces a workbench that is
missing configuration the app requires; a name in it the manifest does not declare is
dead on arrival, because Studio renders declarations and nothing else. It is parsed the
way compose's dotenv reader parses it, since a value that reads differently to compose
than to its author is the failure mode a looser parser would hide.

The third finding is the manifest's own shape, and it comes first because it decides
whether the other two mean anything. Studio's reader is fail-closed on the WHOLE file: one
over-long ``description`` and every declared variable vanishes from the environment form
and from the rendered ``.app.env`` — the app's secrets included. That verdict used to be
Studio's alone, which put it a deploy (and a different machine) away from the edit that
caused it; an authoring agent wrote a 500+ character description, the gate stayed green,
and the app lost its whole manifest. The dialect it is judged against lives in
``envschema``.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from terp.cli.envschema import (
    APP_ENV_SCHEMA_FILE,
    declared_variables,
    manifest_findings,
)

#: The file Studio renders the declared values into; the compose profiles forward it.
APP_ENV_FILE = ".app.env"

#: The committed, hand-maintained template for it. `cp .app.env.example .app.env` is the
#: documented way to run the workbench on the deployed seam, so this file is the app's
#: statement of which variables the inner loop needs -- and the only file in the seam
#: with a human rather than a renderer behind it.
APP_ENV_EXAMPLE_FILE = ".app.env.example"

#: Hosts that mean "this machine" — inside a container, that is the container. A list of
#: addresses to DETECT, not one to bind (ruff's S104 reads the literal, not its use).
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"})  # noqa: S104

#: ``${VAR}`` / ``${VAR:-default}`` — a value compose interpolates from its own
#: environment (which is the developer's `.env`, or the default, never `.app.env`).
_INTERPOLATION = re.compile(r"\$\{[^}]+\}")

#: A usable variable name, matching the manifest dialect's own rule.
_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,63}")

#: In an unquoted value, whitespace then ``#`` starts a comment (compose's rule).
_INLINE_COMMENT = re.compile(r"\s#")

#: The escapes compose interprets inside a double-quoted value.
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"'}


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
    #: ``shadowed`` (a compose block outranks .app.env), ``loopback`` (the value names
    #: this container) or ``example`` (.app.env.example disagrees with the manifest).
    #: They have different fixes, so the report must not offer one of them for another.
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


def parse_dotenv(text: str) -> tuple[dict[str, str], list[tuple[int, str]]]:
    """Parse an env file the way compose's dotenv reader does: values and problems.

    Faithful on the four points that decide whether a hand-written value reaches the
    container as written:

    * an ``export `` prefix is accepted and dropped;
    * in an UNQUOTED value, whitespace followed by ``#`` starts a comment -- so
      ``TOKEN=abc # prod`` is the three characters ``abc``, which is the quiet
      truncation a looser parser reports as the whole line;
    * single quotes are literal (no escapes, no interpolation) and double quotes
      interpret ``\\n``, ``\\t``, ``\\"`` and ``\\\\``;
    * an unterminated quote is an ERROR, not a value. Compose refuses the file, so a
      parser that guessed here would report a variable the app will never receive.

    Problems are ``(line number, what is wrong)``; a line with a problem yields no value,
    because a value read differently by this parser than by compose is worse than none.
    """
    values: dict[str, str] = {}
    problems: list[tuple[int, str]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        name, separator, remainder = line.partition("=")
        name = name.strip()
        if not separator:
            problems.append((number, f"`{line}` is not a KEY=value assignment"))
            continue
        if not _ENV_NAME.fullmatch(name):
            problems.append(
                (number, f"`{name}` is not a usable variable name (UPPER_SNAKE)")
            )
            continue
        remainder = remainder.lstrip()
        if remainder[:1] in {"'", '"'}:
            quote = remainder[0]
            closing = _closing_quote(remainder, quote)
            if closing is None:
                problems.append(
                    (number, f"{name} opens a {quote} quote that is never closed")
                )
                continue
            body = remainder[1:closing]
            trailing = remainder[closing + 1 :].strip()
            if trailing and not trailing.startswith("#"):
                problems.append(
                    (
                        number,
                        f"{name} has `{trailing}` after the closing quote, which "
                        "compose does not read as part of the value",
                    )
                )
                continue
            values[name] = body if quote == "'" else _unescape(body)
            continue
        # Unquoted: whitespace then `#` starts a comment, and the value is stripped.
        comment = _INLINE_COMMENT.search(remainder)
        values[name] = (remainder[: comment.start()] if comment else remainder).strip()
    return values, problems


def _closing_quote(text: str, quote: str) -> int | None:
    """Index of the quote that closes the one at position 0, honouring backslashes."""
    index = 1
    while index < len(text):
        character = text[index]
        if character == "\\" and quote == '"':
            index += 2
            continue
        if character == quote:
            return index
        index += 1
    return None


def _unescape(body: str) -> str:
    """The escape sequences compose interprets inside a double-quoted value."""
    out: list[str] = []
    index = 0
    while index < len(body):
        character = body[index]
        if character == "\\" and index + 1 < len(body):
            out.append(_ESCAPES.get(body[index + 1], body[index + 1]))
            index += 2
            continue
        out.append(character)
        index += 1
    return "".join(out)


def _read_env_file(path: pathlib.Path) -> dict[str, str]:
    """A ``KEY=value`` file as a map; absent or unreadable is empty (both are normal)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    values, _problems = parse_dotenv(text)
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
        # The FIRST seam that supplies a value is the one that lands, and it is the only
        # one worth judging: a correct .app.env with a host address left in .env is a
        # developer running CLIs against the workbench, not a defect. Testing every seam
        # and reporting whichever happened to look wrong would flag exactly that.
        supplied = [
            (source, value)
            for source, value in (
                (APP_ENV_FILE, app_env.get(variable)),
                (".env", dot_env.get(variable)),
                (f"{APP_ENV_SCHEMA_FILE} default", prop.get("default")),
            )
            if isinstance(value, str) and value.strip()
        ]
        for source, value in supplied[:1]:
            if not _is_loopback(value):
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


def _example_findings(
    project_root: pathlib.Path, declared: dict[str, dict]
) -> list[EnvSeamFinding]:
    """Where ``.app.env.example`` and the manifest disagree.

    The manifest is the allow-list on both sides. A declared name absent from the
    example means the documented `cp .app.env.example .app.env` hands the workbench a
    configuration the app requires and does not have; a name in the example the manifest
    does not declare is dead, because Studio renders declarations and nothing else --
    and in practice it is a misspelling of one that IS declared, which is the same
    outage wearing a different hat.

    A secret is the one case with a value rule rather than a presence rule. This file is
    COMMITTED; `.app.env` is not. So a `"format": "secret"` declaration must appear with
    an empty value: the name tells the reader what to fill in, and filling it in here
    would put the credential in git.
    """
    path = project_root / APP_ENV_EXAMPLE_FILE
    if not path.is_file():
        return [
            EnvSeamFinding(
                variable="",
                source=APP_ENV_EXAMPLE_FILE,
                services=(),
                detail=(
                    f"is missing, but {APP_ENV_SCHEMA_FILE} declares "
                    f"{len(declared)} variable(s). It is the documented way to run the "
                    "workbench on the deployed seam "
                    f"(`cp {APP_ENV_EXAMPLE_FILE} {APP_ENV_FILE}`), so without it every "
                    "developer invents their own file"
                ),
                kind="example",
            )
        ]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [
            EnvSeamFinding(
                variable="",
                source=APP_ENV_EXAMPLE_FILE,
                services=(),
                detail=f"cannot be read ({exc})",
                kind="example",
            )
        ]
    values, problems = parse_dotenv(text)
    findings = [
        EnvSeamFinding(
            variable="",
            source=APP_ENV_EXAMPLE_FILE,
            services=(),
            detail=f"line {number}: {problem}",
            kind="example",
        )
        for number, problem in problems
    ]
    for variable in sorted(set(declared) - set(values)):
        findings.append(
            EnvSeamFinding(
                variable=variable,
                source=APP_ENV_EXAMPLE_FILE,
                services=(),
                detail=(
                    f"is declared in {APP_ENV_SCHEMA_FILE} but has no entry here, so a "
                    f"workbench copied from this file starts without it"
                ),
                kind="example",
            )
        )
    for variable in sorted(set(values) - set(declared)):
        findings.append(
            EnvSeamFinding(
                variable=variable,
                source=APP_ENV_EXAMPLE_FILE,
                services=(),
                detail=(
                    f"is not declared in {APP_ENV_SCHEMA_FILE}, so Studio never renders "
                    f"it into {APP_ENV_FILE} and it reaches no deployed environment "
                    "(check the spelling against a declared name)"
                ),
                kind="example",
            )
        )
    for variable in sorted(set(declared) & set(values)):
        if declared[variable].get("format") != "secret":
            continue
        if values[variable].strip():
            findings.append(
                EnvSeamFinding(
                    variable=variable,
                    source=APP_ENV_EXAMPLE_FILE,
                    services=(),
                    detail=(
                        'is declared "format": "secret" and carries a value here. This '
                        f"file is COMMITTED (unlike {APP_ENV_FILE}) -- leave the name "
                        "with an empty value so a reader knows to supply one"
                    ),
                    kind="example",
                )
            )
    return findings


def env_seam_findings(project_root: pathlib.Path) -> list[EnvSeamFinding]:
    """Every declared variable whose value cannot arrive through the seam it was promised."""
    declared = declared_variables(project_root)
    if not declared:
        return []
    return [
        *_shadowing_findings(project_root, declared),
        *_loopback_findings(project_root, declared),
        *_example_findings(project_root, declared),
    ]


def run_env_seams_check(project_root: pathlib.Path) -> tuple[int, str]:
    """The ``env-seams`` verify runner: ``(exit_code, output)``.

    A no-op success for an app that declares nothing — the same shape ``routes-drift``
    has for an unadopted generator. Upgrading the framework must not turn an app's gate
    red for a manifest it has not filled in.
    """
    if not (project_root / APP_ENV_SCHEMA_FILE).is_file():
        return 0, f"no {APP_ENV_SCHEMA_FILE} - app-declared variables not applicable"
    # Shape first: a manifest Studio refuses declares nothing at all, so a seam verdict
    # over it would answer a question that no longer applies.
    defects = manifest_findings(project_root)
    if defects:
        lines = [
            f"{APP_ENV_SCHEMA_FILE} is not usable as written, and Terp Studio's reader",
            "fails closed on the WHOLE file: every declared variable -- the app's",
            "secrets included -- disappears from the environment form and is never",
            f"rendered into {APP_ENV_FILE}.",
            "",
            f"  {APP_ENV_SCHEMA_FILE}",
        ]
        for defect in defects:
            subject = f"{defect.subject} " if defect.subject else ""
            lines.append(f"    {subject}{defect.detail}")
        lines += ["", "See: terp guide environment"]
        return 1, "\n".join(lines)
    declared = declared_variables(project_root)
    if not declared:
        return 0, f"{APP_ENV_SCHEMA_FILE} declares no variables - nothing to shadow"
    findings = env_seam_findings(project_root)
    if not findings:
        return 0, (
            f"{len(declared)} declared variable(s) reach the app through {APP_ENV_FILE}, "
            f"and {APP_ENV_EXAMPLE_FILE} carries one entry for each"
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
            subject = f"{finding.variable}: " if finding.variable else ""
            lines.append(f"    {subject}{finding.detail}")
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
    if any(finding.kind == "example" for finding in findings):
        lines += [
            "",
            f"{APP_ENV_EXAMPLE_FILE} is the one file in this seam a human maintains, and",
            f"the manifest is its allow-list: one entry per declared name, no others, and",
            'an empty value for anything declared "format": "secret" -- this file is',
            "committed.",
        ]
    lines.append("See: terp guide environment")
    return 1, "\n".join(lines)
