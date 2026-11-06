expand_only = True


def upgrade():
    drafts = op.create_table(
        'drafts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('note_id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['note_id'], ['notes.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('note_id'),
    )
    op.create_index('ix_drafts_note_id', 'drafts', ['note_id'], unique=True)
    op.bulk_insert(drafts, [{'id': 1}])
    op.add_column('notes', sa.Column('rank', sa.Integer(), nullable=True))
    op.add_column('notes', sa.Column('weight', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('notes', sa.Column('total', sa.Integer(), sa.Computed('rank + weight')))
    op.create_index('ix_notes_rank', 'notes', ['rank'], unique=False)
