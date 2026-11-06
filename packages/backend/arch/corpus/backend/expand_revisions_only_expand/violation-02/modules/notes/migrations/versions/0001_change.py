expand_only = True


def upgrade():
    op.add_column('notes', sa.Column('rank', sa.Integer(), nullable=False))
