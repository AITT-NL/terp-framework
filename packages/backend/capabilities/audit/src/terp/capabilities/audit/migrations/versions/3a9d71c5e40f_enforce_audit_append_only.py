"""enforce audit append-only at the database

Revision ID: 3a9d71c5e40f
Revises: 586333320cdd
Create Date: 2026-07-06 20:45:00.000000

ADR 0076: the audit trail was append-only **by convention** (no service exposes
an update/delete); this revision makes the database itself refuse an UPDATE or
DELETE on ``audit_event``, so even code that bypasses the service layer (a raw
session, a compromised dependency, an ad-hoc script on the app role) cannot
silently rewrite history. Row-level triggers abort both statements on the two
dialects the gate exercises (SQLite dev/test, PostgreSQL production).
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '3a9d71c5e40f'
down_revision: str | None = '586333320cdd'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POSTGRES_UPGRADE = """
CREATE FUNCTION terp_audit_event_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_event is append-only (ADR 0076)';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_event_no_update
    BEFORE UPDATE ON audit_event
    FOR EACH ROW EXECUTE FUNCTION terp_audit_event_append_only();

CREATE TRIGGER trg_audit_event_no_delete
    BEFORE DELETE ON audit_event
    FOR EACH ROW EXECUTE FUNCTION terp_audit_event_append_only();
"""

_POSTGRES_DOWNGRADE = """
DROP TRIGGER trg_audit_event_no_delete ON audit_event;

DROP TRIGGER trg_audit_event_no_update ON audit_event;

DROP FUNCTION terp_audit_event_append_only();
"""

_SQLITE_UPGRADE = """
CREATE TRIGGER trg_audit_event_no_update
    BEFORE UPDATE ON audit_event
BEGIN
    SELECT RAISE(ABORT, 'audit_event is append-only (ADR 0076)');
END;

CREATE TRIGGER trg_audit_event_no_delete
    BEFORE DELETE ON audit_event
BEGIN
    SELECT RAISE(ABORT, 'audit_event is append-only (ADR 0076)');
END;
"""

_SQLITE_DOWNGRADE = """
DROP TRIGGER trg_audit_event_no_delete;

DROP TRIGGER trg_audit_event_no_update;
"""


def _statements(script: str) -> list[str]:
    """Split *script* on blank lines (each block is one statement, `;`-safe for triggers)."""
    return [block.strip() for block in script.split("\n\n") if block.strip()]


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        for statement in _statements(_POSTGRES_UPGRADE):
            op.execute(statement)
    elif dialect == "sqlite":
        for statement in _statements(_SQLITE_UPGRADE):
            op.execute(statement)
    # Any other (unverified) dialect gets no trigger: the application-level
    # convention still holds, and production boot already requires an explicit
    # DB_ALLOW_UNVERIFIED_DIALECT acknowledgement for such a database.


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        for statement in _statements(_POSTGRES_DOWNGRADE):
            op.execute(statement)
    elif dialect == "sqlite":
        for statement in _statements(_SQLITE_DOWNGRADE):
            op.execute(statement)
