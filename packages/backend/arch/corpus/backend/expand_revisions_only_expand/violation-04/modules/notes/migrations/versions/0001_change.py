expand_only = True


def upgrade():
    op.add_column('notes', sa.Column('rank', sa.Integer(), nullable=True))
    op.get_bind().execute(sa.text('UPDATE notes SET rank = 0'))
