"""Build an Alembic ``Config`` for a single package's independent history.

Every package history shares **one** Terp-owned Alembic environment (the
``_alembic`` directory holding ``env.py`` + ``script.py.mako``) but targets its own
``versions/`` directory and its own ``alembic_version_<label>`` table, so the
histories never share state. The owning package and version table are passed as
custom config options the shared ``env.py`` reads at runtime.
"""

from __future__ import annotations

import pathlib

from alembic.config import Config

from terp.core import get_settings
from terp.core.migrations import MigrationTree

_ALEMBIC_DIR = pathlib.Path(__file__).resolve().parent / "_alembic"


def alembic_config_for(
    tree: MigrationTree,
    database_url: str,
    *,
    app_root: str | pathlib.Path | None = None,
    package: str = "app",
    schema_layout: str | None = None,
) -> Config:
    """An Alembic ``Config`` scoped to *tree* against *database_url*.

    ``path_separator = newline`` makes the single ``version_locations`` path
    robust to spaces and Windows drive colons (a lone path never contains a
    newline), so discovery-resolved absolute paths always parse as one location.

    *app_root* / *package* are forwarded to the shared ``env.py`` so it can discover
    and import every package's models (cross-package foreign keys resolve during
    autogenerate); they are empty for the capability-only path. *schema_layout*
    (default: ``settings.DB_SCHEMA_LAYOUT``) selects the physical table layout the
    env applies per run (ADR 0070) — ``flat`` is a no-op; ``per-module`` routes this
    package's DDL into its own PostgreSQL schema.
    """
    config = Config()

    def option(name: str, value: str) -> None:
        # Alembic keeps its options in a ConfigParser, which reads a bare ``%`` as the
        # start of an interpolation and refuses the value. A URL is rendered with its
        # special characters percent-encoded (a password's ``@`` as ``%40``, a Windows
        # drive colon as ``%3A``), so it is escaped here and reads back unchanged.
        config.set_main_option(name, value.replace("%", "%%"))

    option("script_location", str(_ALEMBIC_DIR))
    option("version_locations", str(tree.versions_path))
    option("path_separator", "newline")
    option("sqlalchemy.url", database_url)
    option("terp_import_path", tree.import_path)
    option("terp_version_table", tree.version_table)
    option("terp_label", tree.label)
    option("terp_app_root", "" if app_root is None else str(app_root))
    option("terp_package", package)
    option(
        "terp_schema_layout",
        schema_layout if schema_layout is not None else get_settings().DB_SCHEMA_LAYOUT,
    )
    return config


__all__ = ["alembic_config_for"]
