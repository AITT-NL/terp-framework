# terp-allow-destructive-migration: the pre-0.6.0 bespoke file-level waiver is retired
def upgrade():
    op.drop_table('notes_beta')
