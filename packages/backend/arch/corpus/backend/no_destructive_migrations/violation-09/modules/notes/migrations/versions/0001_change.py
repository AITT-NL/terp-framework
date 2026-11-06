import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('notes') as batch_op:
        batch_op.drop_column('legacy_flag')
        batch_op.alter_column('title', new_column_name='heading')
        batch_op.alter_column('body', nullable=False)
        batch_op.alter_column('summary', type_=sa.String(50))
        batch_op.create_unique_constraint('uq_notes_slug', ['slug'])
        batch_op.create_foreign_key('fk_notes_owner', 'users', ['owner_id'], ['id'])
