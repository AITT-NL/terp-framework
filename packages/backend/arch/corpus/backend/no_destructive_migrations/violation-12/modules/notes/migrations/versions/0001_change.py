from alembic.op import alter_column, drop_table
from alembic.op import rename_table as move


def upgrade():
    drop_table('notes_archive')
    move('notes', 'entries')
    alter_column('notes', 'body', nullable=False)
