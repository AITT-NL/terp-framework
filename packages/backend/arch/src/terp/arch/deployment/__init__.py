"""The deployment declaration: ``deployment.json``, its reader, and the profile it describes.

ADR 0184. The words are the Terp Standard's (``deployment-declaration.schema.json``,
mirrored here byte for byte); the closed datastore table is this framework release's
(``datastore-table.json``). Two ``terp.arch`` rules read them, from files alone:
``deployment_declaration_is_readable`` and ``deployment_declaration_tells_the_truth``
(:mod:`terp.arch.rules.deployment`). ``terp verify --only deployment`` runs both and
adds the app part, which needs the composed app and so lives in the CLI.

ADR 0187: :func:`generate` renders a generated app's build files from the declaration, the
project name and this release's tables (:mod:`terp.arch.deployment.tables`), and the
template's own three files are its render of the seed.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

from terp.arch.deployment.datastores import (
    Datastore,
    DatastoreTable,
    DatastoreTableError,
    load_table,
    published_table,
)
from terp.arch.deployment.generator import OWNED_PATHS, escape_findings, generate
from terp.arch.deployment.volumes import mounters
from terp.arch.deployment.profile import (
    build_path_findings,
    compose_literal,
    resolve_profile,
    services_of,
    truth_findings,
)
from terp.arch.deployment.files import load
from terp.arch.deployment.reader import (
    DEPLOYMENT_FILE,
    SCHEMA_FILE,
    SPEC_RELEASE,
    Backup,
    Declaration,
    Finding,
    Mount,
    Unit,
    Unmanaged,
    Volume,
    read,
)
from terp.arch.deployment.tables import (
    SystemPackageTable,
    Tables,
    load_system_packages,
    published_system_packages,
    published_tables,
)
from terp.arch.deployment.render_check import Drift
from terp.arch.deployment.render_check import check as check_render


def readable(
    project_root: str | pathlib.Path,
    table: DatastoreTable | None = None,
    packages: SystemPackageTable | None = None,
) -> tuple[Declaration | Unmanaged | None, list[Finding]]:
    """The declaration under *project_root*, or every reason it cannot be read.

    ``(None, [])`` for an app with none. Readable means: one JSON object the schema
    admits, in exactly one state, agreeing with itself and with the datastore table,
    and leading a reader only to paths inside the checkout -- the profile files and the
    declared units' build contexts and build files.
    """
    root = pathlib.Path(project_root)
    resolved = table or published_table()
    declared, findings = load(root, resolved, packages)
    if isinstance(declared, Declaration):
        findings = build_path_findings(root, declared)
        if findings:
            return None, findings
    return declared, findings


def untrue(
    project_root: str | pathlib.Path,
    table: DatastoreTable | None = None,
    packages: SystemPackageTable | None = None,
) -> list[Finding]:
    """Every fact a readable declaration states that its profile contradicts.

    Empty for an absent file, an unmanaged one, and one that cannot be read: a reader
    stops at the first, and the readable rule reports that one.
    """
    root = pathlib.Path(project_root)
    resolved = table or published_table()
    declared, findings = readable(root, resolved, packages)
    if findings or not isinstance(declared, Declaration):
        return []
    return truth_findings(root, declared, resolved)


@dataclass(frozen=True)
class Generated:
    """The generated state's check for one project: whether it applies, and what it found.

    *applies* is false for an undeclared app, ``own``, ``unmanaged`` and a declaration that
    cannot be read, and *reason* then says which; the check is silent for all of them.
    """

    applies: bool
    reason: str
    drift: Drift


def generated(
    project_root: str | pathlib.Path,
    table: DatastoreTable | None = None,
    packages: SystemPackageTable | None = None,
) -> Generated:
    """ADR 0187 decision 3: is every generator-owned file the render of the declaration?"""
    root = pathlib.Path(project_root)
    if not (root / DEPLOYMENT_FILE).is_file():
        return Generated(False, f"no {DEPLOYMENT_FILE}: nothing is generated here", Drift())
    resolved = table or published_table()
    declared, findings = readable(root, resolved, packages)
    if findings:
        return Generated(
            False,
            f"{DEPLOYMENT_FILE} cannot be read, which `terp verify --only deployment` reports",
            Drift(),
        )
    if isinstance(declared, Unmanaged):
        return Generated(False, f"{DEPLOYMENT_FILE} is unmanaged: {declared.reason}", Drift())
    assert isinstance(declared, Declaration)
    if declared.build != "generated":
        return Generated(
            False,
            f'{DEPLOYMENT_FILE} says "build": "{declared.build}": the build files are the app\'s own',
            Drift(),
        )
    published = published_tables()
    tables = Tables(
        datastores=resolved,
        base_images=published.base_images,
        system_packages=packages or published.system_packages,
        recipes=published.recipes,
    )
    return Generated(True, "", check_render(root, declared, tables))


__all__ = [
    "DEPLOYMENT_FILE",
    "OWNED_PATHS",
    "SCHEMA_FILE",
    "SPEC_RELEASE",
    "Backup",
    "Datastore",
    "DatastoreTable",
    "DatastoreTableError",
    "Declaration",
    "Drift",
    "Finding",
    "Generated",
    "Mount",
    "SystemPackageTable",
    "Tables",
    "Unit",
    "Unmanaged",
    "Volume",
    "compose_literal",
    "escape_findings",
    "generate",
    "generated",
    "load_system_packages",
    "load_table",
    "mounters",
    "published_table",
    "published_system_packages",
    "published_tables",
    "read",
    "readable",
    "resolve_profile",
    "services_of",
    "untrue",
]
