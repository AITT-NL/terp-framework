expand_only = True


def upgrade():
    op.create_index('ix_notes_code', 'notes', ['code'], unique=True)
