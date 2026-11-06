import sqlalchemy as sa


def upgrade():
    op.add_column('notes', column)
    # Restates a constraint the column already has: not a tightening.
    op.alter_column('notes', 'title', existing_type=sa.String(200), nullable=False,
                    existing_nullable=False)
    op.alter_column('notes', 'title', server_default='untitled')
