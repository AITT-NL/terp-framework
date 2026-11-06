expand_only = False


def upgrade():
    op.drop_column('notes', 'legacy')
    op.alter_column('notes', 'title', nullable=False)
    op.execute('UPDATE notes SET rank = 0')
