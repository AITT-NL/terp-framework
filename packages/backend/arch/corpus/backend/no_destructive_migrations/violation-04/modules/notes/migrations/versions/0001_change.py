import sqlalchemy as sa


def upgrade():
    op.drop_column('notes', 'legacy_flag')
    op.alter_column('notes', 'title', type_=sa.Text())
