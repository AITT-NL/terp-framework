revision = "aaa111"
down_revision = None


def upgrade():
    op.create_table("notes")


def downgrade():
    op.drop_table("notes")
