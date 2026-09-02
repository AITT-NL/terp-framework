"""create the per-module role assignment table

Revision ID: c3a71f5b90d2
Revises: 71a140f9930e
Create Date: 2026-09-02 17:45:00.000000

Additive only (ADR 0072): a new table with no change to `access_grant`, so an app that never
assigns a per-module role is unaffected by having it.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'c3a71f5b90d2'
down_revision: str | None = '71a140f9930e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('access_module_role',
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('subject_id', sa.Uuid(), nullable=False),
    sa.Column('module', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('role_rank', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_access_module_role')),
    sa.UniqueConstraint('subject_id', 'module', name='uq_access_module_role_subject_module')
    )
    with op.batch_alter_table('access_module_role', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_access_module_role_module'), ['module'], unique=False)
        batch_op.create_index(batch_op.f('ix_access_module_role_role_rank'), ['role_rank'], unique=False)
        batch_op.create_index(batch_op.f('ix_access_module_role_subject_id'), ['subject_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('access_module_role', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_access_module_role_subject_id'))
        batch_op.drop_index(batch_op.f('ix_access_module_role_role_rank'))
        batch_op.drop_index(batch_op.f('ix_access_module_role_module'))

    op.drop_table('access_module_role')
