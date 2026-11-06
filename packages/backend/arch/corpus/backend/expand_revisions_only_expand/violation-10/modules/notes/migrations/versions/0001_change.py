expand_only = True


def upgrade():
    op.create_table(
        'drafts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('note_id', sa.Uuid(), sa.ForeignKey('notes.id', ondelete='CASCADE')),
    )
