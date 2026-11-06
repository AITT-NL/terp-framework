import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('notes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(None, 'users', ['owner_id'], ['id'])
        batch_op.create_index('ix_notes_owner_id', ['owner_id'], unique=False)
        batch_op.alter_column('summary', nullable=True)
