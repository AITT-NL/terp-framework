expand_only = True


def upgrade():
    op.alter_column('notes', 'rank', nullable=False)
