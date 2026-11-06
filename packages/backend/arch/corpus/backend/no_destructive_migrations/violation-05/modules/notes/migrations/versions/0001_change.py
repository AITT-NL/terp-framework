def upgrade():
    op.execute('DELETE FROM notes WHERE deleted_at IS NOT NULL')
    op.execute('TRUNCATE TABLE notes_audit')
