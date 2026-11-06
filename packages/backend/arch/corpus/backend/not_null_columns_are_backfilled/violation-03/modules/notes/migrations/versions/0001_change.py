def upgrade():
    op.add_column(table_name='notes', column=sa.Column('rank', sa.Integer(), nullable=False))
