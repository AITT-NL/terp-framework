"""The declaration on disk: ``deployment.json`` read, and the paths it leads a reader to.

ADR 0184 decision 3 defines *the checkout* as the root of the git work tree that holds
the project root, or the project root itself when it lies in no work tree. A path the
declaration leads a reader to is resolved against it, links followed, and refused when it
lands outside; a deployable in a subdirectory may still build from the repository root,
the way ``apps/example`` builds with ``context: ../..``. Decision 6 holds the other
boundary: the declaration never names the development compose file, the mirror of
``workbench.json`` refusing a deployment profile. Only the actual overlap is refused,
never a file name, so ``compose.production.yml`` or ``deploy/compose.yml`` can be declared.
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any

from terp.arch.deployment import _jsonschema
from terp.arch.deployment.datastores import DatastoreTable
from terp.arch.deployment.tables import SystemPackageTable
from terp.arch.deployment.reader import (
    DEPLOYMENT_FILE,
    DEV_COMPOSE_FILE,
    Declaration,
    Finding,
    Unmanaged,
    read,
)


class StrictJSONError(ValueError):
    """Text a lenient parser reads and strict JSON does not hold; ``allowed`` names the form."""

    allowed = "one JSON object"


class DuplicateKeyError(StrictJSONError):
    """A key written twice in one object: which one a parser keeps is the parser's choice."""

    allowed = "one JSON object, each key once"


class ConstantError(StrictJSONError):
    """``NaN`` or an infinity: Python's parser reads them, and JSON has no such number."""

    allowed = "one JSON object, each number finite"


#: How deep a declaration's objects and arrays may nest, the document itself being the first
#: (terp-spec 0.47.0). The number, and the way of counting, an event of the conversation
#: stream is held to.
MAX_DEPTH = 64


class DepthError(ValueError):
    """Objects and arrays nested deeper than the contract allows.

    What a parser does with such a file is where its own stack ends: an error in one
    language, a crash in another, and a different answer in the next release of the same
    one. So the depth is a number of the contract, counted before anything parses.
    """

    allowed = f"one JSON object, nested at most {MAX_DEPTH} deep"


def depth(text: str) -> int:
    """How deep *text* nests objects and arrays, counted in the text and never by parsing it.

    The document itself is the first level. A bracket inside a string is no nesting, and a
    quote behind a backslash does not end one. Text that is no JSON gets a count all the
    same, and is the parser's to refuse.
    """
    deepest = level = 0
    in_string = escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "{[":
            level += 1
            deepest = max(deepest, level)
        elif character in "}]":
            level -= 1
    return deepest


def _once(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for key, value in pairs:
        if key in found:
            raise DuplicateKeyError(f"the key {json.dumps(key[:64])} appears twice in one object")
        found[key] = value
    return found


def _no_constant(name: str) -> Any:
    raise ConstantError(f"{name} is not a JSON number")


def loads(text: str) -> Any:
    """Parse ``deployment.json`` strictly, as terp-runner does, so no two readers can read
    one file differently: a key twice in one object is refused, never read as its last
    value, and so are ``NaN`` and the infinities, which only a lenient parser reads. A file
    nested deeper than :data:`MAX_DEPTH` is refused before it is parsed, so the answer never
    depends on where this interpreter's parser gives up."""
    nested = depth(text)
    if nested > MAX_DEPTH:
        raise DepthError(f"its objects and arrays nest {nested} deep")
    return json.loads(text, object_pairs_hook=_once, parse_constant=_no_constant)


def checkout_root(project_root: pathlib.Path) -> pathlib.Path:
    """The git work tree that holds the project, or the project when it is in none."""
    start = project_root.resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def inside(path: pathlib.Path, checkout: pathlib.Path) -> bool:
    """Does *path*, every link followed, land inside *checkout*?"""
    return path.resolve().is_relative_to(checkout)


def development_compose_name(project_root: pathlib.Path) -> tuple[str, bool]:
    """The compose file ``workbench.json`` names as written, else the template's; and
    whether the development declaration named it."""
    try:
        workbench = json.loads((project_root / "workbench.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        workbench = None
    compose = workbench.get("compose") if isinstance(workbench, dict) else None
    if isinstance(compose, dict) and isinstance(compose.get("file"), str):
        return compose["file"], True
    return DEV_COMPOSE_FILE, False


def development_compose_file(project_root: pathlib.Path) -> pathlib.Path:
    """The compose file ``workbench.json`` names, else the template's development file."""
    return (project_root / development_compose_name(project_root)[0]).resolve()


def path_findings(project_root: pathlib.Path, declaration: Declaration) -> list[Finding]:
    """Every profile file named: inside the checkout, and never the development file."""
    checkout = checkout_root(project_root)
    development = os.path.normcase(str(development_compose_file(project_root)))
    written, by_declaration = development_compose_name(project_root)
    named = f"{' the development declaration names' if by_declaration else ''} ({_jsonschema.name(written)})"
    findings: list[Finding] = []
    for index, name in enumerate(declaration.profile_files):
        field = "compose.file" if index == 0 else f"compose.overrides[{index - 1}]"
        target = project_root / name
        if not inside(target, checkout):
            findings.append(
                Finding(
                    f'{field} "{name}" resolves outside the checkout (allowed: a path that resolves inside the checkout)'
                )
            )
        elif os.path.normcase(str(target.resolve())) == development:
            findings.append(
                Finding(
                    f'{field} "{name}" is the development compose file (allowed: a deployment profile, '
                    f"never the development one{named})",
                    "deployment.json describes the deployment profile; workbench.json describes the development loop.",
                )
            )
    return findings


def load(
    project_root: pathlib.Path,
    table: DatastoreTable,
    packages: SystemPackageTable | None = None,
) -> tuple[Declaration | Unmanaged | None, list[Finding]]:
    """Read ``deployment.json`` and the profile paths it names. ``(None, [])`` when absent."""
    path = project_root / DEPLOYMENT_FILE
    if not path.is_file():
        return None, []
    try:
        raw = loads(path.read_text(encoding="utf-8"))
    except StrictJSONError as exc:
        return None, [Finding(f"{DEPLOYMENT_FILE} is not strict JSON: {exc} (allowed: {exc.allowed})")]
    except DepthError as exc:
        return None, [Finding(f"{DEPLOYMENT_FILE} is nested too deeply: {exc} (allowed: {exc.allowed})")]
    except (OSError, ValueError) as exc:
        return None, [
            Finding(f"{DEPLOYMENT_FILE} is not valid JSON ({exc}) (allowed: one JSON object)")
        ]
    declared, findings = read(raw, table, packages)
    if isinstance(declared, Declaration):
        findings = path_findings(project_root, declared)
        if findings:
            return None, findings
    return declared, findings
