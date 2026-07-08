"""add journal visibility

Revision ID: e3f1a9c40b21
Revises: 6a0738d075b7
Create Date: 2026-07-03 20:55:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e3f1a9c40b21'
down_revision: str | None = '6a0738d075b7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('journal', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'visibility',
                sqlmodel.sql.sqltypes.AutoString(length=20),
                nullable=False,
                server_default='shared',
            )
        )
        batch_op.create_index(batch_op.f('ix_journal_visibility'), ['visibility'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('journal', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_journal_visibility'))
        batch_op.drop_column('visibility')
