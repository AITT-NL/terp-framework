expand_only = True


def upgrade():
    op.add_column(
        'notes',
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=True),
    )
