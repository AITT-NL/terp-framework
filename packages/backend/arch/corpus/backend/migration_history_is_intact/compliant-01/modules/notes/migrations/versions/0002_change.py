revision = "bbb222"
down_revision = "aaa111"


def upgrade():
    op.add_column("notes", column)


def downgrade():
    op.drop_column("notes", "title")
