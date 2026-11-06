def upgrade():
    op.add_column("notes", column)


def downgrade():
    op.drop_column("notes", "title")
