def upgrade():
    with op.batch_alter_table('notes') as batch_op:
        batch_op.add_column(sa.Column('rank', sa.Integer(), nullable=False))
