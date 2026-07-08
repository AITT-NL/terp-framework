"""Lazy SQLAlchemy engine construction (internal).

Kept out of the public surface so the engine, pool, and URL handling can be
refactored freely. Public code reaches the database only through
:data:`terp.core.db.SessionDep`.
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlmodel import create_engine

from terp.core.config import settings

_engine: Engine | None = None


def _engine_options(database_url: str) -> dict[str, object]:
    """Engine kwargs: connection-pool tuning for a server DB; SQLite keeps its defaults.

    Pool sizing / recycling / pre-ping apply to a server database (Postgres, MySQL,
    …). SQLite (dev / test, often in-memory) keeps SQLAlchemy's default pool —
    ``pool_size`` / ``max_overflow`` do not apply to it, and recycling an in-memory
    connection would discard the database.

    A PostgreSQL database additionally receives a per-session ``statement_timeout``
    (``DB_STATEMENT_TIMEOUT_MS``) on every pooled connection, so one runaway query
    cannot hold a worker + connection forever; other server databases apply their
    equivalent knob at the database/DSN level.

    The ``per-module`` schema layout (ADR 0070) is a PostgreSQL feature: any other
    dialect fails closed here, at engine construction, so a misconfigured deployment
    never opens a connection against a layout its database cannot express.
    """
    if settings.DB_SCHEMA_LAYOUT == "per-module" and not database_url.startswith("postgresql"):
        raise RuntimeError(
            "DB_SCHEMA_LAYOUT='per-module' requires a PostgreSQL DATABASE_URL; "
            "schemas are a PostgreSQL feature (ADR 0070)"
        )
    if database_url.startswith("sqlite"):
        return {"echo": False}
    options: dict[str, object] = {
        "echo": False,
        "pool_pre_ping": settings.DB_POOL_PRE_PING,
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
        "pool_recycle": settings.DB_POOL_RECYCLE,
    }
    if database_url.startswith("postgresql") and settings.DB_STATEMENT_TIMEOUT_MS > 0:
        options["connect_args"] = {
            "options": f"-c statement_timeout={settings.DB_STATEMENT_TIMEOUT_MS}"
        }
    return options


def get_engine() -> Engine:
    """Return the process-wide engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_engine(settings.DATABASE_URL, **_engine_options(settings.DATABASE_URL))
    return _engine


def reset_engine() -> None:
    """Dispose and clear the cached engine (used by tests)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


__all__ = ["get_engine", "reset_engine"]
