"""create notes tables

Revision ID: 0a1b2c3d4e5f
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0a1b2c3d4e5f"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "note",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("note")
