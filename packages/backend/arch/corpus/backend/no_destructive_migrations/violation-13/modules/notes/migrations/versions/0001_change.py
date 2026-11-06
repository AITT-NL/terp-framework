def _contract():
    op.drop_table('notes_archive')


_step = _contract
upgrade = _step
