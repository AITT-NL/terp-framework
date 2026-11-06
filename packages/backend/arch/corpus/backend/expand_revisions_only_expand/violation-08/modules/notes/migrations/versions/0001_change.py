expand_only = True


def upgrade():
    op.bulk_insert(sa.table('notes', sa.column('id')), [{'id': 1}])
