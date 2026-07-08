"""add file storage profile

Revision ID: e3a9c47d51b8
Revises: ceffeb4b0fc2
Create Date: 2026-07-02 12:05:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e3a9c47d51b8'
down_revision: str | None = 'ceffeb4b0fc2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every pre-existing row was stored through the original single (default) backend,
    # so the backfill value is exactly the store that holds its bytes.
    with op.batch_alter_table('file_object', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'storage_profile',
                sqlmodel.sql.sqltypes.AutoString(length=64),
                nullable=False,
                server_default='default',
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('file_object', schema=None) as batch_op:
        batch_op.drop_column('storage_profile')
