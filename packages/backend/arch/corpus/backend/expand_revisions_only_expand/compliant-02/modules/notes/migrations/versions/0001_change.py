expand_only = True


def upgrade():
    with op.batch_alter_table('notes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('project_id', sa.Uuid(), nullable=True))
        batch_op.create_index(batch_op.f('ix_notes_project_id'), ['project_id'], unique=False)
        batch_op.create_foreign_key(
            batch_op.f('fk_notes_project_id'), 'projects', ['project_id'], ['id'], ondelete='SET NULL'
        )
