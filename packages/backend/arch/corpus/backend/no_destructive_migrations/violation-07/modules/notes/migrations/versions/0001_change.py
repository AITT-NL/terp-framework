import sqlalchemy as sa


def upgrade():
    op.alter_column('notes', 'title', existing_type=sa.String(200), nullable=False)
    op.alter_column(table_name='notes', column_name='body', nullable=False)
    op.execute('ALTER TABLE notes ALTER COLUMN summary SET NOT NULL')
    # Added, back-filled and tightened in one release: the release still running
    # writes NULL between the back-fill and the tightening.
    op.add_column('notes', sa.Column('rank', sa.Integer(), nullable=True))
    op.execute('UPDATE notes SET rank = 0')
    op.alter_column('notes', 'rank', nullable=False)
