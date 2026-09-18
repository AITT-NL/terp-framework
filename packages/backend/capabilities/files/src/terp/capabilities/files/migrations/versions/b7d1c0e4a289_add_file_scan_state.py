"""add file scan state

Revision ID: b7d1c0e4a289
Revises: e3a9c47d51b8
Create Date: 2026-09-18 11:40:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b7d1c0e4a289'
down_revision: str | None = 'e3a9c47d51b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every pre-existing row was stored before any scanner could have run, so the honest
    # backfill is 'not_scanned' -- not 'clean'. Backfilling a clean bill of health onto
    # files nothing ever looked at is the one value that would make the new column lie,
    # and it would lie in the direction that lets bytes out.
    with op.batch_alter_table('file_object', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'scan_state',
                sqlmodel.sql.sqltypes.AutoString(length=32),
                nullable=False,
                server_default='not_scanned',
            )
        )
        # Indexed because the question this column answers is a listing one -- "which
        # stored files were never scanned" -- which an operator asks once a scanner is
        # finally wired, over the whole table.
        batch_op.create_index(
            batch_op.f('ix_file_object_scan_state'), ['scan_state'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('file_object', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_file_object_scan_state'))
        batch_op.drop_column('scan_state')
