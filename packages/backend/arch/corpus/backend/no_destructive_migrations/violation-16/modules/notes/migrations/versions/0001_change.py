def upgrade():
    # Two statements in one text are two steps.
    op.execute('DROP TABLE notes_archive; ALTER TABLE notes RENAME TO entries')
    # A semicolon inside a quoted string ends no statement.
    op.execute(
        "UPDATE notes SET body = 'a; b' WHERE body IS NULL; "
        'ALTER TABLE notes ALTER COLUMN body SET NOT NULL'
    )
