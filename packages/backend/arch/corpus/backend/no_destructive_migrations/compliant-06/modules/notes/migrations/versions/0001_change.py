import sqlalchemy as sa


def _expand():
    op.add_column('notes', sa.Column('slug', sa.String(), nullable=True))


def _restore():
    op.drop_table('notes_v2')


def upgrade():
    _expand()
    op.execute(
        'CREATE FUNCTION notes_touch() RETURNS trigger AS $$ '
        'BEGIN NEW.rank := 0; RETURN NEW; END; $$ LANGUAGE plpgsql'
    )


def downgrade():
    _restore()
