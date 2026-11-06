def downgrade():
    op.drop_table('notes')


def upgrade():
    op.execute("UPDATE notes SET title = 'untitled' WHERE title IS NULL")
    op.execute('DROP INDEX ix_notes_title')
    op.alter_column('notes', 'title', nullable=True)
