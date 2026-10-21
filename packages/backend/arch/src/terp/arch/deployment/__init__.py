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

from terp.arch.deployment.datastores import (
    Datastore,
    DatastoreTable,
    DatastoreTableError,
    load_table,
    published_table,
)
from terp.arch.deployment.generator import OWNED_PATHS, escape_findings, generate
from terp.arch.deployment.profile import (
    build_path_findings,
    compose_literal,
    mounters,
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
from terp.arch.deployment.tables import Tables, published_tables


def readable(
    project_root: str | pathlib.Path, table: DatastoreTable | None = None
) -> tuple[Declaration | Unmanaged | None, list[Finding]]:
    """The declaration under *project_root*, or every reason it cannot be read.

    ``(None, [])`` for an app with none. Readable means: one JSON object the schema
    admits, in exactly one state, agreeing with itself and with the datastore table,
    and leading a reader only to paths inside the checkout -- the profile files and the
    declared units' build contexts and build files.
    """
    root = pathlib.Path(project_root)
    resolved = table or published_table()
    declared, findings = load(root, resolved)
    if isinstance(declared, Declaration):
        findings = build_path_findings(root, declared)
        if findings:
            return None, findings
    return declared, findings


def untrue(project_root: str | pathlib.Path, table: DatastoreTable | None = None) -> list[Finding]:
    """Every fact a readable declaration states that its profile contradicts.

    Empty for an absent file, an unmanaged one, and one that cannot be read: a reader
    stops at the first, and the readable rule reports that one.
    """
    root = pathlib.Path(project_root)
    resolved = table or published_table()
    declared, findings = readable(root, resolved)
    if findings or not isinstance(declared, Declaration):
        return []
    return truth_findings(root, declared, resolved)


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
    "Finding",
    "Mount",
    "Tables",
    "Unit",
    "Unmanaged",
    "Volume",
    "compose_literal",
    "escape_findings",
    "generate",
    "load_table",
    "mounters",
    "published_table",
    "published_tables",
    "read",
    "readable",
    "resolve_profile",
    "services_of",
    "untrue",
]
