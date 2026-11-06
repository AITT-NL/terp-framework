def _contract():
    op.drop_column('notes', 'legacy_flag')
    _rename()


def _rename():
    # Each helper calls the other: each is read once.
    op.alter_column('notes', 'title', new_column_name='heading')
    _contract()


def upgrade():
    _contract()
