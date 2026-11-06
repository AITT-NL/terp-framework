def upgrade():
    op.alter_column('notes', 'title', new_column_name='heading')
    op.rename_table('notes', 'entries')
    op.execute('ALTER TABLE notes RENAME COLUMN body TO content')
    op.execute(f'ALTER TABLE {table} RENAME TO archived_notes')
    op.get_bind().exec_driver_sql('RENAME TABLE drafts TO notes_drafts')
