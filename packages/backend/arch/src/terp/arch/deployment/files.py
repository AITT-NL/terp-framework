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


def development_compose_file(project_root: pathlib.Path) -> pathlib.Path:
    """The compose file ``workbench.json`` names, else the template's development file."""
    named = DEV_COMPOSE_FILE
    try:
        workbench = json.loads((project_root / "workbench.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        workbench = None
    compose = workbench.get("compose") if isinstance(workbench, dict) else None
    if isinstance(compose, dict) and isinstance(compose.get("file"), str):
        named = compose["file"]
    return (project_root / named).resolve()


def path_findings(project_root: pathlib.Path, declaration: Declaration) -> list[Finding]:
    """Every profile file named: inside the checkout, and never the development file."""
    checkout = checkout_root(project_root)
    development = os.path.normcase(str(development_compose_file(project_root)))
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
                    f'{field} "{name}" is the development compose file (allowed: a deployment profile, never the development one)',
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
        raw = json.loads(path.read_text(encoding="utf-8"))
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
