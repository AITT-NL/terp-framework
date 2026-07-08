"""Terp-owned Alembic environment, shared by every package's history.

Thin shim by design: the per-run logic lives in the covered
``terp.migrations._runtime`` module, parameterized by the ``terp_import_path`` /
``terp_version_table`` config options ``terp migrate`` sets. Migrating a package
isolates its history in its own ``alembic_version_<label>`` table and scopes
autogenerate to that package's tables.
"""

from __future__ import annotations

from alembic import context

from terp.migrations._runtime import run_migrations

run_migrations(context)
