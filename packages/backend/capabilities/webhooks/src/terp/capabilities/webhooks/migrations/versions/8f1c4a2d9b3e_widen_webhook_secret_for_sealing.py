"""widen webhook secret for at-rest sealing

Revision ID: 8f1c4a2d9b3e
Revises: 717754ab63f6
Create Date: 2026-07-06 20:30:00.000000

The subscription's signing ``secret`` is now sealed before it is persisted
(ADR 0076): the stored value is the ``enc:v1:`` Fernet ciphertext of the
client-supplied secret, whose seal of the schema's 256-char maximum input is
~447 characters — so the column widens from 256 to 512. A widening VARCHAR
change loses no data; existing (legacy plaintext) rows are untouched and keep
delivering — the runtime unseal passes an unsealed value through unchanged.
"""
# terp-allow-destructive-migration: widening webhook_subscription.secret 256 -> 512 (a pure widen — no value can be truncated) so the sealed-at-rest ciphertext fits (ADR 0076)
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '8f1c4a2d9b3e'
down_revision: str | None = '717754ab63f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('webhook_subscription', schema=None) as batch_op:
        batch_op.alter_column(
            'secret',
            existing_type=sqlmodel.sql.sqltypes.AutoString(length=256),
            type_=sqlmodel.sql.sqltypes.AutoString(length=512),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('webhook_subscription', schema=None) as batch_op:
        batch_op.alter_column(
            'secret',
            existing_type=sqlmodel.sql.sqltypes.AutoString(length=512),
            type_=sqlmodel.sql.sqltypes.AutoString(length=256),
            existing_nullable=False,
        )
