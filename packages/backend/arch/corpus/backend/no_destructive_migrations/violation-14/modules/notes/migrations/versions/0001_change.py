def upgrade():
    getattr(op, 'drop_column')('notes', 'legacy_flag')
    with op.batch_alter_table('notes') as batch_op:
        getattr(batch_op, 'alter_column')('body', nullable=False)
