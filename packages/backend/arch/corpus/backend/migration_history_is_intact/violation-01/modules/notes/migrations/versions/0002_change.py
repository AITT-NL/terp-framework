revision = "bbb222"
down_revision = "deleted_parent"


def upgrade():
    op.add_column("notes", column)


def downgrade():
    op.drop_column("notes", "title")
