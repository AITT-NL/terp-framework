import sqlalchemy as sa


def upgrade():
    # A new reference column: nullable, so every existing row holds NULL, which a
    # foreign key and a unique index both accept.
    op.add_column('notes', sa.Column('owner_id', sa.Uuid(), nullable=True))
    op.create_index('ix_notes_owner_id', 'notes', ['owner_id'], unique=True)
    op.create_foreign_key(None, 'notes', 'users', ['owner_id'], ['id'])
    op.create_index('ix_notes_title', 'notes', ['title'])
    op.alter_column('notes', 'summary', nullable=True)
    # Constraints added without checking the existing rows.
    op.execute('ALTER TABLE notes ADD CONSTRAINT ck_notes_rank CHECK (rank >= 0) NOT VALID')
    op.execute(
        'ALTER TABLE notes ADD CONSTRAINT fk_notes_project FOREIGN KEY (project_id) '
        'REFERENCES projects (id) NOT VALID'
    )
    op.execute('ALTER TABLE notes ALTER COLUMN body DROP NOT NULL')
    op.execute('ALTER TABLE notes ALTER COLUMN type SET DEFAULT 1')
    op.execute('ALTER TABLE notes RENAME CONSTRAINT uq_notes_a TO uq_notes_b')
    op.execute('ALTER INDEX ix_notes_a RENAME TO ix_notes_b')
    op.execute('ALTER TABLE notes ADD COLUMN slug text; ALTER INDEX ix_c RENAME TO ix_d')
    op.execute('CREATE INDEX ix_notes_slug ON notes (slug)')
    op.execute("UPDATE notes SET summary = 'none' WHERE summary IS NULL")
