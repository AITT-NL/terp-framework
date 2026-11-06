def upgrade():
    op.create_table('drafts', sa.Column('id', sa.Integer()))
    op.add_column('drafts', sa.Column('rank', sa.Integer(), nullable=False))
    op.add_column('notes', sa.Column('note', sa.String(), nullable=True))
