"""Every host port Terp binds by default sits in the range Terp owns.

A published host port is the one part of a development stack that has to coexist
with software the framework has never heard of. 5173, 8000, 3000 and 8080 are
where that software lives, so a default there is not a convention — it is a
collision with the developer's own machine, and the symptom is diffuse: a stack
that appears to start and answers somebody else's application, or refuses to bind
at all with a message about an address in use.

The framework was also contradicting itself. A workbench allocating ports for
several projects at once has always drawn them from a Terp-owned range, and its
own comment says why. The compose files it starts carried ``${WEB_PORT:-5173}``,
so the two agreed only while the workbench was the thing doing the starting —
and disagreed for every other way to run an app, which is most of them: a shell,
an editor task, an agent, ``terp dev``.

The bound cannot be applied centrally, for the same reason ADR 0108's shutdown
bound cannot: the host side of a port is written in the app's own compose file,
its own Vite config, or a CLI default, and none of those routes through
``create_app``. So the control is this test. It enumerates the repository's
published ports as data and requires each to fall in range, and
:func:`test_no_conventional_host_port_is_published_anywhere` greps rather than
reads a list — a new file that publishes 5173 fails even though this test never
named it.

Publishing is only half of it, and the half that was checked. The other half is
DIALLING: a CI workflow, an e2e config or a script that hard-codes the number a
compose file used to publish. Moving the publisher then leaves the consumer pointing
at a closed port, which is exactly what happened -- the conformance suite drove
``localhost:5173`` and the production smoke test curled ``localhost:8080`` after both
had moved, and nothing in this file noticed because neither of them publishes
anything. :func:`test_nothing_dials_a_conventional_host_port` closes that side.

**What is deliberately not checked.** Container-internal ports. Inside a Compose
network 8000 and 5173 cannot collide with anything, and the app's healthchecks,
proxy targets and process arguments are written against them; moving those would
be churn with no beneficiary. Only the *host* side of a mapping is in scope -- which
is why the dialling check has to know the one place a ``localhost`` URL in a workflow
is NOT the host: a probe that runs through ``compose exec``, inside the container.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

from terp.cli.dev import DEFAULT_API_PORT, DEFAULT_WEB_PORT

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: The range Terp owns, and the reason the numbers are what they are: a workbench
#: allocates web ports from 21100 and api ports from 22100 in lockstep offsets, and
#: deployment host ports from 23100. The defaults here are the first slot of each,
#: so a single project run by hand lands exactly where a workbench would have put
#: it — which is what lets a stack started outside the workbench be adopted by one.
TERP_PORT_FLOOR = 21000
TERP_PORT_CEILING = 23999

#: Ports a default must never be, stated positively so the failure message can name
#: what went wrong rather than only that a number was out of range. Each is the
#: documented default of something a developer plausibly already runs: Vite, a
#: FastAPI/Django tutorial, a Node app, an alternative HTTP port.
CONVENTIONAL_PORTS = frozenset({3000, 4200, 5000, 5173, 5432, 6379, 8000, 8080, 8081})

_COMPOSE_FILES = (
    _REPO_ROOT / "apps" / "example" / "docker-compose.yml",
    _REPO_ROOT / "apps" / "example" / "docker-compose.prod.yml",
    _REPO_ROOT / "template" / "project" / "docker-compose.yml.jinja",
    _REPO_ROOT / "template" / "project" / "docker-compose.prod.yml.jinja",
)

#: Where a published host port may appear at all.
_SEARCH_ROOTS = (
    _REPO_ROOT / "apps",
    _REPO_ROOT / "template",
    _REPO_ROOT / "packages" / "backend" / "cli" / "src",
)

_SEARCH_SUFFIXES = {".yml", ".yaml", ".jinja", ".ts"}

_SKIP_DIRS = {"node_modules", "dist", ".venv", "__pycache__"}

#: A compose port mapping whose host side is an interpolation with a default:
#: ``"${WEB_PORT:-21100}:5173"``. The default is what this test judges, because it
#: is what binds when nobody passes anything — which is the case that goes wrong.
_INTERPOLATED_HOST_PORT = re.compile(r"\$\{(\w+):-(\d+)\}:\d+")

#: A compose port mapping with a bare literal host side: ``"5173:5173"``. Its own
#: rule, because there is no variable to override it with — two projects cannot
#: run at once and no workbench can place it.
_LITERAL_HOST_PORT = re.compile(r'^\s*-\s*["\']?(\d+):\d+["\']?\s*$', re.MULTILINE)


def _in_range(port: int) -> bool:
    return TERP_PORT_FLOOR <= port <= TERP_PORT_CEILING


def _iter_search_files():
    for root in _SEARCH_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in _SEARCH_SUFFIXES:
                continue
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            yield path


#: A whole Jinja conditional, contents included — the same strip
#: ``test_serving_shutdown`` uses, for the same reason and with the same limit: a
#: port declared INSIDE a conditional is invisible to the YAML half. That is what
#: the grep half is for, and it reads the raw text.
_JINJA_IF_BLOCK = re.compile(r"\{%-?\s*if\b.*?%\}.*?\{%-?\s*endif\s*-?%\}", re.DOTALL)


def _jinja_free(text: str) -> str:
    """Compose files in the template are Jinja; strip the tags so YAML can parse.

    Every ``{{ ... }}`` in these files is a name (a project slug, an image), so a
    placeholder keeps the document well-formed.
    """
    text = _JINJA_IF_BLOCK.sub("", text)
    assert "{%" not in text, "unstripped Jinja block"
    return re.sub(r"\{\{.*?\}\}", "x", text)


def _published_defaults(path: pathlib.Path) -> list[tuple[str, str, int]]:
    """``(service, variable, default)`` for every published port in *path*.

    Parsed from the resolved YAML rather than grepped, so a long-syntax entry
    (``published:``) is seen and a port inside a comment is not.
    """
    document = yaml.safe_load(_jinja_free(path.read_text(encoding="utf-8")))
    found: list[tuple[str, str, int]] = []
    for name, service in (document.get("services") or {}).items():
        for entry in service.get("ports") or []:
            text = (
                entry
                if isinstance(entry, str)
                else f"{entry.get('published', '')}:{entry.get('target', '')}"
            )
            match = _INTERPOLATED_HOST_PORT.search(str(text))
            if match is not None:
                found.append((name, match.group(1), int(match.group(2))))
    return found


@pytest.mark.parametrize("path", _COMPOSE_FILES, ids=lambda p: p.name)
def test_every_published_compose_port_defaults_into_the_terp_range(
    path: pathlib.Path,
) -> None:
    published = _published_defaults(path)
    assert published, f"{path} publishes no host port — the parse found nothing"
    for service, variable, default in published:
        assert _in_range(default), (
            f"{path.name}: service {service!r} defaults ${{{variable}}} to {default}, "
            f"outside the Terp range {TERP_PORT_FLOOR}-{TERP_PORT_CEILING}. A host "
            "port default has to coexist with software this framework has never "
            "heard of; pick the range's slot for this role (web 21100, api 22100, "
            "deploy 23100) rather than the convention for the tool."
        )
        assert default not in CONVENTIONAL_PORTS, (
            f"{path.name}: service {service!r} defaults ${{{variable}}} to {default}, "
            "which is the documented default of something a developer probably "
            "already runs."
        )


@pytest.mark.parametrize("path", _COMPOSE_FILES, ids=lambda p: p.name)
def test_no_compose_service_publishes_a_bare_literal_host_port(
    path: pathlib.Path,
) -> None:
    """A literal host port cannot be moved, so two projects cannot both run.

    Separate from the range check because it is a different defect: a literal in
    range is still unplaceable by a workbench, and a comment showing one is how
    the practice spreads (this repository's own database hint used to).
    """
    text = path.read_text(encoding="utf-8")
    literals = _LITERAL_HOST_PORT.findall(text)
    assert not literals, (
        f"{path.name} publishes host port(s) {literals} as literals. The host side "
        'has to arrive through a variable ("${SOME_PORT:-21400}:5432") so a '
        "workbench can place it and two projects can run at once."
    )


def test_the_cli_dev_defaults_are_in_range() -> None:
    """``terp dev`` binds the host directly, so it is bound by the same rule — and
    it is the invocation an app cannot edit, which makes its default the one that
    reaches every project."""
    for name, port in (("api", DEFAULT_API_PORT), ("web", DEFAULT_WEB_PORT)):
        assert _in_range(port), f"terp dev's {name} default {port} is out of range"
        assert port not in CONVENTIONAL_PORTS, (
            f"terp dev's {name} default is {port}, a conventional port"
        )


def test_no_conventional_host_port_is_published_anywhere() -> None:
    """The grep half: a NEW file that publishes a conventional host port fails here
    even though nothing above names it.

    Deliberately narrow. It matches only the two shapes that actually bind a host
    port — a compose mapping's default and a Vite ``port:`` setting — so prose, a
    container-internal argument, and a proxy target are all left alone.
    """
    offenders: list[str] = []
    vite_port = re.compile(r"^\s*port:\s*(\d+)\s*,", re.MULTILINE)
    for path in _iter_search_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(_REPO_ROOT).as_posix()
        for variable, default in _INTERPOLATED_HOST_PORT.findall(text):
            if int(default) in CONVENTIONAL_PORTS or not _in_range(int(default)):
                offenders.append(f"{relative}: ${{{variable}:-{default}}}")
        if path.name == "vite.config.ts":
            for value in vite_port.findall(text):
                if int(value) in CONVENTIONAL_PORTS or not _in_range(int(value)):
                    offenders.append(f"{relative}: server.port {value}")
    assert not offenders, (
        "Host port defaults outside the Terp range:\n  "
        + "\n  ".join(offenders)
        + f"\nThe range is {TERP_PORT_FLOOR}-{TERP_PORT_CEILING} (web 21100, "
        "api 22100, deploy 23100)."
    )


#: Files that DIAL a published host port: the CI workflows that drive a running stack,
#: and the e2e configs whose default base URL is what a developer gets when they run the
#: suite by hand. Neither publishes a port, so the check above cannot see them.
_DIALLING_FILES = (
    *sorted((_REPO_ROOT / ".github" / "workflows").glob("*.yml")),
    _REPO_ROOT / "apps" / "example" / "frontend" / "playwright.config.ts",
    _REPO_ROOT / "packages" / "frontend" / "conformance" / "playwright.config.ts",
    _REPO_ROOT / "apps" / "workbench" / "playwright.config.ts",
)

#: A ``localhost`` HTTP URL with a port, which is the shape a consumer takes.
#:
#: The scheme is part of the pattern rather than decoration. This control is about the
#: app's HTTP surface -- the thing a compose file publishes and a suite drives -- and the
#: first run of it flagged ``postgresql+psycopg://postgres:terp@localhost:5432`` in
#: ci.yml, which is a runner SERVICE CONTAINER: its port is published by Actions on an
#: ephemeral machine, cannot collide with a developer's, and is out of scope by the same
#: sentence in the module docstring that exempts a database client mapping.
_DIALLED_HOST_PORT = re.compile(r"https?://(?:localhost|127\.0\.0\.1):(\d{2,5})")

#: The one line where ``localhost`` is NOT the host, named rather than pattern-matched:
#: it runs THROUGH ``docker compose exec``, so localhost is the api container and 8000 is
#: its internal port -- the case the module docstring exempts. A second such probe adds a
#: line here with its reason; a pattern would quietly exempt every future host-side call
#: that happened to look similar.
_CONTAINER_INTERNAL_PROBES = (
    "urllib.request.urlopen('http://localhost:8000/health/ready')",
)


def test_nothing_dials_a_conventional_host_port() -> None:
    """A consumer that hard-codes a conventional port is a stack nobody can reach.

    The failure is worse than a collision, because it survives review: the workflow is
    syntactically fine, the stack comes up healthy, and every request is refused at a
    port nothing is listening on. Measured on main, this shape cost three red jobs --
    two Playwright suites at 5173 and four curls at 8080.

    Read as text rather than parsed, for the reason the grep half above gives: a new
    workflow that dials the wrong number fails here even though nothing names it.
    """
    offenders: list[str] = []
    for path in _DIALLING_FILES:
        if not path.is_file():
            continue
        relative = path.relative_to(_REPO_ROOT).as_posix()
        for number, line in [
            (number, line)
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            for number in _DIALLED_HOST_PORT.findall(line)
        ]:
            if any(probe in line for probe in _CONTAINER_INTERNAL_PROBES):
                continue
            port = int(number)
            if port in CONVENTIONAL_PORTS or not _in_range(port):
                offenders.append(f"{relative}: {line.strip()}")
    assert not offenders, (
        "These dial a host port outside the Terp range, so they reach nothing once the\n"
        "publisher moves:\n  " + "\n  ".join(offenders) + f"\nThe range is "
        f"{TERP_PORT_FLOOR}-{TERP_PORT_CEILING} (web 21100, api 22100, deploy 23100)."
    )
