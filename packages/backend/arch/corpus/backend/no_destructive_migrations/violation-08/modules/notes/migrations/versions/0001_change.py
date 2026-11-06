import sqlalchemy as sa


def upgrade():
    op.create_unique_constraint('uq_notes_slug', 'notes', ['slug'])
    op.create_foreign_key('fk_notes_owner', 'notes', 'users', ['owner_id'], ['id'])
    op.create_check_constraint('ck_notes_rank', 'notes', 'rank >= 0')
    op.create_index('ix_notes_slug', 'notes', ['slug'], unique=True)
    op.create_primary_key('pk_tags', 'tags', ['id'])
    op.execute('ALTER TABLE notes ADD CONSTRAINT uq_notes_code UNIQUE (code)')
    op.execute('CREATE UNIQUE INDEX ix_notes_code ON notes (code)')
    op.execute('ALTER TABLE notes VALIDATE CONSTRAINT ck_notes_rank')
    # A unique constraint cannot be added unchecked: the qualifier does not apply.
    op.execute('ALTER TABLE notes ADD CONSTRAINT uq_notes_ref UNIQUE (ref) NOT VALID')
    # A new column with a server default holds that value on every row, not NULL.
    op.add_column('notes', sa.Column('lane', sa.String(20), server_default='main'))
    op.create_unique_constraint('uq_notes_lane', 'notes', ['lane'])
