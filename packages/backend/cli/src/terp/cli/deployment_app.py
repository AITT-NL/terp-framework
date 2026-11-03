"""The app part of ``terp verify --only deployment``: the declaration against the app.

Two of the facts a declaration states can only be checked against the app's installed
environment (ADR 0184 decision 5): which migration histories exist, and which paths the
API serves. Both turn red when the declaration names one the app does not have. Both
need the app's own environment, and the path check builds the app, so where
``app.main:build`` cannot be imported -- a tool reading the checkout as data, the
platform's own tree -- the whole part skips with a named note rather than guessing.

Beside them it reads what the app's own declarations say it uses, and notes, never
fails, where the deploy declaration says nothing about it: the files volume the files
capability writes to, the companion roots ``[tool.terp.arch]`` ships beside the app, and
the datastore kinds the app's capabilities need. A declaration is partial on purpose;
those notes are what a deploy tool will not know, said once, where the author can act.
"""

from __future__ import annotations

import importlib
import pathlib
import re
import tomllib
from dataclasses import dataclass
from typing import Any

from terp.arch.deployment import Declaration, DatastoreTable, Finding, mounters

#: The app reference every app-importing check uses (``terp verify``'s default).
APP_REF = "app.main:build"

#: The package app modules live in; an app module's migration label is its name.
APP_PACKAGE = "app"

#: The files capability's default storage root, relative to the image's working
#: directory (``terp.capabilities.files.storage``).
FILES_ROOT = "var/files"

#: Capability distributions that need a datastore of a kind a table may carry.
CAPABILITY_KINDS = {"terp-cap-redis": "redis"}

#: The roles whose health paths the app itself answers. Another role's paths are that
#: role's to serve (a web tier answers its own), so nothing here can judge them.
APP_SERVED_ROLES = frozenset({"api"})


@dataclass(frozen=True)
class AppReport:
    """What the app part found: red findings, and notes that are never red."""

    findings: tuple[Finding, ...] = ()
    notes: tuple[str, ...] = ()


def _pyproject(project_root: pathlib.Path) -> dict[str, Any]:
    try:
        return tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _dependencies(pyproject: dict[str, Any]) -> set[str]:
    names = set()
    for requirement in pyproject.get("project", {}).get("dependencies", ()):
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", str(requirement))
        if match:
            names.add(re.sub(r"[._]", "-", match.group(1).lower()))
    return names


def _label_findings(declaration: Declaration, project_root: pathlib.Path) -> list[Finding]:
    from terp.core import MigrationDiscoveryError, resolve_all_migration_trees

    app_root = project_root / APP_PACKAGE
    try:
        trees = resolve_all_migration_trees(
            app_root if app_root.is_dir() else None, package=APP_PACKAGE
        )
    except MigrationDiscoveryError as exc:
        return [Finding(f"the app's migration histories cannot be discovered: {exc}")]
    labels = sorted(tree.label for tree in trees)
    return [
        Finding(
            f'units[{index}].migrations[{position}] "{label}" is a history no installed '
            f"package and no app module owns (allowed: {', '.join(labels) or 'none'})",
            "A unit claims a history by its package label: an app module's is its "
            "module name, a capability's its terp.migrations entry point.",
        )
        for index, unit in enumerate(declaration.units)
        for position, label in enumerate(unit.migrations)
        if label not in labels
    ]


def _serves(app: Any, path: str) -> bool:
    from starlette.routing import Match

    scope = {"type": "http", "path": path, "method": "GET", "root_path": ""}
    return any(route.matches(scope)[0] == Match.FULL for route in app.router.routes)


def _path_findings(declaration: Declaration, app: Any) -> list[Finding]:
    return [
        Finding(
            f'units[{index}].{name} is "{path}", which {APP_REF} does not serve '
            "(allowed: a path the API answers, such as /health/ready or /health/live)"
        )
        for index, unit in enumerate(declaration.units)
        if unit.role in APP_SERVED_ROLES
        for name, path in (("healthPath", unit.health_path), ("livenessPath", unit.liveness_path))
        if path is not None and not _serves(app, path)
    ]


def _files_notes(declaration: Declaration, services: dict[str, Any], uses_files: bool) -> list[str]:
    if not uses_files:
        return []
    built = {unit.id for unit in declaration.units if unit.kind is None}
    stateful = {unit.id for unit in declaration.units if unit.stateful}
    mounted = mounters(services)
    covered = {volume.id for volume in declaration.volumes} | {
        volume for volume, users in mounted.items() if {name for name, _ in users} <= stateful
    }
    holding = {
        volume: sorted({name for name, _target in users if name in built})
        for volume, users in mounted.items()
        if any(name in built and target.rstrip("/").endswith(FILES_ROOT) for name, target in users)
    }
    if not holding:
        return [
            "the app stores files (terp-cap-files) and no declared unit mounts a named "
            f"volume at its storage root ({FILES_ROOT}), so stored files live in a "
            "container's writable layer"
        ]
    return [
        f"volume {volume} holds the files the app stores ({', '.join(users)}) and has no "
        'backup policy here: declare it in "volumes"'
        for volume, users in sorted(holding.items())
        if volume not in covered
    ]


def _runs(root: str, argv: tuple[str, ...]) -> bool:
    modules = [argv[index + 1] for index, part in enumerate(argv[:-1]) if part == "-m"]
    return any(module.split(".")[0] == root for module in [*modules, *argv[:1]])


def _companion_notes(declaration: Declaration, pyproject: dict[str, Any]) -> list[str]:
    roots = pyproject.get("tool", {}).get("terp", {}).get("arch", {}).get("companions", ())
    commands = [unit.command or () for unit in declaration.units]
    return [
        f"companion root {root} ([tool.terp.arch] companions) is run by no declared unit, "
        "so a deploy tool will not know it ships"
        for root in roots
        if not any(_runs(str(root), argv) for argv in commands)
    ]


def _datastore_notes(
    declaration: Declaration, table: DatastoreTable, dependencies: set[str]
) -> list[str]:
    offered = table.versions()
    declared = {unit.kind for unit in declaration.units}
    database = {entry.kind for entry in table.entries if entry.role == "database"}
    needed = {kind: "the app's own database" for kind in database}
    needed.update({kind: dist for dist, kind in CAPABILITY_KINDS.items() if dist in dependencies})
    notes: list[str] = []
    for kind, why in sorted(needed.items()):
        if kind in declared or (kind in database and declaration.external_database):
            continue
        if kind not in offered:
            notes.append(
                f"the app uses {kind} ({why}), which this release's datastore table does "
                "not carry, so its service stays undeclared"
            )
        else:
            suffix = " and there is no externalDatabase" if kind in database else ""
            notes.append(
                f"the app uses {kind} ({why}), and no declared unit is kind {kind}{suffix}"
            )
    return notes


def audit_app(
    declaration: Declaration,
    profile: dict[str, Any],
    project_root: pathlib.Path,
    table: DatastoreTable,
) -> AppReport:
    """Rule 2 from the app, and the notes; skipped by name when no app imports."""
    from terp.arch.deployment import services_of
    from terp.cli._appref import load_app, push_app_root

    push_app_root(project_root)
    importlib.invalidate_caches()
    try:
        app = load_app(APP_REF)
    except (SystemExit, ImportError) as exc:
        return AppReport(
            notes=(
                f"no importable {APP_REF} ({exc}): the app part (migration labels, health "
                "paths, what the app uses) is skipped",
            )
        )
    pyproject = _pyproject(project_root)
    dependencies = _dependencies(pyproject)
    return AppReport(
        findings=(*_label_findings(declaration, project_root), *_path_findings(declaration, app)),
        notes=(
            *_files_notes(declaration, services_of(profile), "terp-cap-files" in dependencies),
            *_companion_notes(declaration, pyproject),
            *_datastore_notes(declaration, table, dependencies),
        ),
    )
