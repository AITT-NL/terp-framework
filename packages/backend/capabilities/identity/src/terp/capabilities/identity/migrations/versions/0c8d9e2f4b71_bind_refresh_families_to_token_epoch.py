"""Bind new refresh families to their authenticated token epoch.

Revision ID: 0c8d9e2f4b71
Revises: 4f1c9d3a7b02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0c8d9e2f4b71"
down_revision = "4f1c9d3a7b02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing families keep their existing lifetime and explicit revocation rules.
    # Nullable is deliberate: older workers can still run during an expand rollout.
    op.add_column("identity_refresh_token", sa.Column("token_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("identity_refresh_token", "token_version")
