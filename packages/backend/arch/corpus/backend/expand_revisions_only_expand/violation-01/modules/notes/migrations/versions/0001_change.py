expand_only = True


def upgrade():
    op.drop_column('notes', 'legacy')
