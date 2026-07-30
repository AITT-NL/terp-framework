"""create identity service_account table

Revision ID: 4f1c9d3a7b02
Revises: 18216f00ee61
Create Date: 2026-07-14 10:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '4f1c9d3a7b02'
down_revision: str | None = '18216f00ee61'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('identity_service_account',
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True),
    sa.Column('client_id', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('hashed_secret', sqlmodel.sql.sqltypes.AutoString(length=256), nullable=False),
    sa.Column('role', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_identity_service_account'))
    )
    with op.batch_alter_table('identity_service_account', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_identity_service_account_client_id'), ['client_id'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('identity_service_account', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_identity_service_account_client_id'))

    op.drop_table('identity_service_account')
