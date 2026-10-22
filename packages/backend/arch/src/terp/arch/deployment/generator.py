"""The generator: a generated app's three build files, rendered from its declaration (ADR 0187).

Where ``deployment.json`` says ``"build": "generated"`` the production build files are the
framework's to write: ``Dockerfile.prod`` when a unit runs the backend image,
``frontend/Dockerfile.prod`` when a ``web`` unit is declared, and ``docker-compose.prod.yml``
always. The template's own three files are this function's render of the seed, held byte
for byte by a test, so the two cannot drift and a hardening change is made once.

:func:`generate` is a **pure function** of the typed declaration, the project name, whether
the checkout holds ``frontend/package-lock.json``, and the framework release's tables
(:mod:`terp.arch.deployment.tables`). It imports the standard library and the reader's own
modules only, does no I/O, and returns every file or none: a map of path to bytes, or the
refusals in the reader's finding shape. It refuses what it cannot render faithfully and never
what it would rather not, and each refusal names ``own`` as the way out.

**One encoder per grammar.** The output is UTF-8 and ASCII-only, LF, one final newline, no
trailing whitespace, a fixed key order, units and volumes in declaration order, and no
timestamp, path or version in a file. Every fragment is typed as fixed text or a value, and
quoting is decided on the finished scalar: a command element, a health path and a mount path
are always double-quoted with every ``$`` doubled, so compose never interpolates them; a
scalar built only from ids and fixed text stands plain when both YAML 1.1 and 1.2 read it as
a string (and, for one that starts with an id, when that id does not start with a digit). The
Dockerfiles take no declaration value in this version. The backend image carries no
``HEALTHCHECK`` and a unit that serves no request gets none: Compose's ``up --wait`` refuses
both an unhealthy container and a disabled check, and ready-once-running is the truth for
such a unit until ADR 0024's heartbeat gives it a liveness of its own.

Its parts are modules of their own: the refusals (:mod:`._refusals`), the profile
(:mod:`._compose`), the one YAML encoder (:mod:`._yaml`) and the fixed text, the Dockerfiles
among it (:mod:`._generator_text`).

:func:`escape_findings` is the audit an executor runs over a carried profile without
rendering it: every ``$`` in a parsed scalar or key is half of a ``$$`` or opens one of the
fixed interpolations this module writes, at the place it writes it.
"""

from __future__ import annotations

import re

from terp.arch.deployment._compose import _plan, _profile
from terp.arch.deployment._generator_text import (
    _BACKEND_DOCKERFILE,
    _FRONTEND_DOCKERFILE,
    APP_ROOT,
    BACKEND_DOCKERFILE,
    CORS_ORIGINS,
    DEFAULT_COMMANDS,
    EXTERNAL_DATABASE_URL,
    FRONTEND_DOCKERFILE,
    FRONTEND_LOCK,
    HEADER,
    HEALTH_PROBE,
    KEY_SEAM,
    MIGRATION_STEP,
    MOUNT_PATH,
    NO_DATABASE_URL,
    OWN_REMEDY,
    OWNED_PATHS,
    PROFILE,
    PROFILE_FILE,
    RELEASE_TAG_SEAM,
    RELEASE_TAG_VARIABLE,
    WEB_PORT,
)
from terp.arch.deployment._refusals import refusals
from terp.arch.deployment._yaml import fixed, plain_safe, scalar, value
from terp.arch.deployment.reader import Declaration, Finding
from terp.arch.deployment.tables import Tables


def _dockerfile(template: str, tables: Tables, names: tuple[str, ...]) -> str:
    text = template
    for name in names:
        base = tables.base_images.get(name)
        text = text.replace(f"@@{name.upper()}_TAG@@", base.tag).replace(
            f"@@{name.upper()}@@", base.image
        )
    return text


def generate(
    declaration: Declaration, project: str, *, tables: Tables, frontend_lock: bool
) -> tuple[dict[str, bytes], list[Finding]]:
    """The generator-owned files *declaration* renders to, or every reason it cannot.

    *project* is ``[project].name`` from ``pyproject.toml``, used verbatim; *frontend_lock*
    says whether the checkout holds ``frontend/package-lock.json``; *tables* are the
    framework release's (:func:`terp.arch.deployment.tables.published_tables`). Returns
    ``(files, [])`` - a path the declaration renders nothing for is absent from *files* - or
    ``({}, findings)``. Two calls with the same inputs return the same bytes, in any process.
    """
    found = refusals(declaration, project, tables=tables, frontend_lock=frontend_lock)
    if found:
        return {}, found
    plan = _plan(declaration, project, tables, frontend_lock)
    files = {PROFILE: _profile(plan)}
    if plan.backend:
        files[BACKEND_DOCKERFILE] = _dockerfile(_BACKEND_DOCKERFILE, tables, ("uv", "python"))
    if plan.upstream is not None:
        files[FRONTEND_DOCKERFILE] = _dockerfile(_FRONTEND_DOCKERFILE, tables, ("node", "nginx"))
    return {path: files[path].encode("ascii") for path in OWNED_PATHS if path in files}, []


_ID = r"[a-z0-9][a-z0-9_.-]{0,62}"

#: A project name as an image name starts with it: the characters compose and Docker both
#: accept, which never include a ``$``.
_PROJECT = r"[a-z0-9][a-z0-9_.-]*"


def fixed_interpolations(tables: Tables) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Every interpolation the generator writes, as (place, the exact scalar it may be).

    A place is the last two steps of the path to a mapping value - its key and the key
    above it, ``environment.SECRET_KEY`` - or, for an item of a list, the list's own key,
    ``ports[]``; ``*.image`` is an ``image`` under any key, a service or ``x-backend``. The
    closed list an executor carries, which a framework release only extends: this one
    added the per-release tag of ADR 0185 on the two image names.
    """
    places = [
        ("environment.DATABASE_URL", re.escape(EXTERNAL_DATABASE_URL)),
        ("environment.DATABASE_URL", re.escape(NO_DATABASE_URL)),
        ("environment.SECRET_KEY", re.escape(KEY_SEAM)),
        ("environment.BACKEND_CORS_ORIGINS", re.escape(CORS_ORIGINS)),
        ("ports[]", re.escape(WEB_PORT)),
        ("*.image", rf"{_PROJECT}-(?:backend|frontend)-prod:{re.escape(RELEASE_TAG_SEAM)}"),
    ]
    for recipe in tables.recipes:
        url = re.escape(recipe.url).replace(re.escape("{host}"), _ID)
        places.append(
            (f"environment.{recipe.variable}", rf"\$\{{{recipe.variable}:-{url}\}}")
        )
        for name, text in recipe.environment:
            if "$" in text:
                places.append((f"environment.{name}", re.escape(text)))
    return tuple((place, re.compile(pattern)) for place, pattern in places)


def _literal(text: str) -> bool:
    """Whether every ``$`` in *text* is half of a ``$$``."""
    return "$" not in text.replace("$$", "")


def _at(where: str, place: str) -> bool:
    """Whether a fixed interpolation's *where* names *place* (``*.`` is any key above)."""
    if where.startswith("*."):
        return "." in place and place.rsplit(".", 1)[1] == where[2:]
    return where == place


def escape_findings(profile: object, tables: Tables) -> list[str]:
    """Every scalar or key of a parsed profile through which compose would interpolate.

    Over the parsed values, never the text: each ``$`` is half of a ``$$`` or the scalar
    is exactly one of :func:`fixed_interpolations` at its place.
    """
    allowed = fixed_interpolations(tables)
    found: list[str] = []

    def walk(node: object, path: tuple[str, ...]) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                if isinstance(key, str) and not _literal(key):
                    found.append(f"{'.'.join(path) or '(top)'}: the key {key!r} interpolates")
                walk(item, (*path, str(key)))
        elif isinstance(node, list):
            for item in node:
                walk(item, (*path[:-1], f"{path[-1]}[]") if path else ("[]",))
        elif isinstance(node, str) and not _literal(node):
            place = path[-1] if path[-1].endswith("[]") else ".".join(path[-2:])
            if not any(_at(where, place) and pattern.fullmatch(node) for where, pattern in allowed):
                found.append(f"{'.'.join(path)}: {node!r} interpolates outside the fixed list")

    walk(profile, ())
    return found


__all__ = [
    "APP_ROOT",
    "BACKEND_DOCKERFILE",
    "CORS_ORIGINS",
    "DEFAULT_COMMANDS",
    "EXTERNAL_DATABASE_URL",
    "FRONTEND_DOCKERFILE",
    "FRONTEND_LOCK",
    "HEADER",
    "HEALTH_PROBE",
    "KEY_SEAM",
    "MIGRATION_STEP",
    "MOUNT_PATH",
    "NO_DATABASE_URL",
    "OWNED_PATHS",
    "OWN_REMEDY",
    "PROFILE",
    "PROFILE_FILE",
    "RELEASE_TAG_SEAM",
    "RELEASE_TAG_VARIABLE",
    "WEB_PORT",
    "escape_findings",
    "fixed",
    "fixed_interpolations",
    "generate",
    "plain_safe",
    "refusals",
    "scalar",
    "value",
]
