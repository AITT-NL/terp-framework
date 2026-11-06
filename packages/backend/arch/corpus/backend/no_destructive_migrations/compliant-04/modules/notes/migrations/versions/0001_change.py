import sqlalchemy as sa


def upgrade():
    op.create_table('drafts', sa.Column('id', sa.Integer(), primary_key=True))
    op.alter_column('drafts', 'title', nullable=False)
    op.create_unique_constraint('uq_drafts_slug', 'drafts', ['slug'])
    op.create_check_constraint('ck_drafts_rank', 'drafts', 'rank >= 0')
    op.create_index('ix_drafts_slug', 'drafts', ['slug'], unique=True)
    with op.batch_alter_table('drafts') as batch_op:
        batch_op.create_index('ix_drafts_code', ['code'], unique=True)
        batch_op.alter_column('body', nullable=False)
