def upgrade():
    op.execute('ALTER TABLE notes ALTER COLUMN title TYPE varchar(50)')
    op.execute('ALTER TABLE notes ALTER COLUMN rank SET DATA TYPE smallint')
    # A column named type, altered without the COLUMN keyword.
    op.execute('ALTER TABLE notes ALTER type TYPE text')
