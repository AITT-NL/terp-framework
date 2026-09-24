"""create mfa enrolment and recovery-code tables

Revision ID: a3f9c1e7b204
Revises:
Create Date: 2026-09-18 15:10:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a3f9c1e7b204'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'mfa_enrolment',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('secret', sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_step', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_mfa_enrolment_user_id'), 'mfa_enrolment', ['user_id'], unique=True)
    # Indexed because the login path asks "is this subject enrolled and live?" on every
    # attempt, and a started-but-unconfirmed row must not answer yes.
    op.create_index(
        op.f('ix_mfa_enrolment_confirmed_at'), 'mfa_enrolment', ['confirmed_at'], unique=False
    )

    op.create_table(
        'mfa_recovery_code',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('enrolment_id', sa.Uuid(), nullable=False),
        sa.Column('code_hash', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        # CASCADE: a recovery code is a PART of its enrolment, so disabling the factor
        # destroys the codes with it and leaves nothing usable behind.
        sa.ForeignKeyConstraint(['enrolment_id'], ['mfa_enrolment.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_mfa_recovery_code_enrolment_id'),
        'mfa_recovery_code',
        ['enrolment_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_mfa_recovery_code_code_hash'), 'mfa_recovery_code', ['code_hash'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_mfa_recovery_code_code_hash'), table_name='mfa_recovery_code')
    op.drop_index(op.f('ix_mfa_recovery_code_enrolment_id'), table_name='mfa_recovery_code')
    op.drop_table('mfa_recovery_code')
    op.drop_index(op.f('ix_mfa_enrolment_confirmed_at'), table_name='mfa_enrolment')
    op.drop_index(op.f('ix_mfa_enrolment_user_id'), table_name='mfa_enrolment')
    op.drop_table('mfa_enrolment')
