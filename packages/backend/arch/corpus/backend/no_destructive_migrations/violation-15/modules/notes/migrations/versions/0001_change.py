def upgrade():
    op.execute('DROP SCHEMA billing CASCADE')
    op.execute('DROP SCHEMA IF EXISTS notes_archive')
