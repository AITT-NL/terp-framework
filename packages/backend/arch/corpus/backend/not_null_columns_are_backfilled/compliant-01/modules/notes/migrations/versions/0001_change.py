def upgrade():
    op.add_column('notes', sa.Column('rank', sa.Integer(), nullable=False, server_default='0'))
