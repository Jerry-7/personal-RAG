"""Add research-agent knowledge, notes, web evidence, and audit tables."""

from alembic import op
import sqlalchemy as sa

from app.db.models import (
    AgentRun, Collection, ConversationSummary, DocumentCollection, DocumentTag,
    KnowledgeSource, Note, NoteCollection, NoteSource, NoteTag,
    ResearchRunSnapshot, Tag, ToolExecution, WebSnapshot,
)

revision = "20260731_01"
down_revision = None
branch_labels = None
depends_on = None


NEW_TABLES = (
    KnowledgeSource.__table__, AgentRun.__table__, ToolExecution.__table__,
    WebSnapshot.__table__, ResearchRunSnapshot.__table__, ConversationSummary.__table__,
    Note.__table__, Tag.__table__, Collection.__table__, NoteTag.__table__,
    NoteCollection.__table__, DocumentTag.__table__, DocumentCollection.__table__,
    NoteSource.__table__,
)


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
        # Recover cleanly if a previous SQLite batch migration was interrupted.
        for table_name in ("documents", "chunks", "index_jobs"):
            bind.exec_driver_sql(f"DROP TABLE IF EXISTS _alembic_tmp_{table_name}")
    KnowledgeSource.__table__.create(bind, checkfirst=True)

    if "source_id" not in _columns("documents"):
        with op.batch_alter_table("documents") as batch:
            batch.add_column(sa.Column("source_id", sa.String(36), nullable=True))
            batch.create_foreign_key("fk_documents_source", "knowledge_sources", ["source_id"], ["id"], ondelete="CASCADE")
            batch.create_index("ix_documents_source_id", ["source_id"], unique=True)
    if "source_id" not in _columns("chunks"):
        with op.batch_alter_table("chunks") as batch:
            batch.alter_column("document_id", existing_type=sa.String(36), nullable=True)
            batch.add_column(sa.Column("source_id", sa.String(36), nullable=True))
            batch.create_foreign_key("fk_chunks_source", "knowledge_sources", ["source_id"], ["id"], ondelete="CASCADE")
            batch.create_index("ix_chunks_source_id", ["source_id"], unique=False)
    if "source_id" not in _columns("index_jobs"):
        with op.batch_alter_table("index_jobs") as batch:
            batch.alter_column("document_id", existing_type=sa.String(36), nullable=True)
            batch.add_column(sa.Column("source_id", sa.String(36), nullable=True))
            batch.create_foreign_key("fk_index_jobs_source", "knowledge_sources", ["source_id"], ["id"], ondelete="CASCADE")
            batch.create_index("ix_index_jobs_source_id", ["source_id"], unique=True)

    bind.execute(sa.text(
        "INSERT OR IGNORE INTO knowledge_sources "
        "(id, kind, title, status, index_status, content_version, created_at, updated_at) "
        "SELECT id, 'document', original_name, 'active', "
        "CASE WHEN status='indexed' THEN 'indexed' ELSE status END, 1, created_at, updated_at FROM documents"
    ))
    bind.execute(sa.text("UPDATE documents SET source_id=id WHERE source_id IS NULL"))
    bind.execute(sa.text("UPDATE chunks SET source_id=document_id WHERE source_id IS NULL"))
    bind.execute(sa.text("UPDATE index_jobs SET source_id=document_id WHERE source_id IS NULL"))

    with op.batch_alter_table("documents") as batch:
        batch.alter_column("source_id", existing_type=sa.String(36), nullable=False)
    with op.batch_alter_table("chunks") as batch:
        batch.alter_column("source_id", existing_type=sa.String(36), nullable=False)
    with op.batch_alter_table("index_jobs") as batch:
        batch.alter_column("source_id", existing_type=sa.String(36), nullable=False)

    for table in NEW_TABLES[1:]:
        table.create(bind, checkfirst=True)


def downgrade() -> None:
    for table in reversed(NEW_TABLES[1:]):
        table.drop(op.get_bind(), checkfirst=True)
    with op.batch_alter_table("index_jobs") as batch:
        batch.drop_index("ix_index_jobs_source_id")
        batch.drop_constraint("fk_index_jobs_source", type_="foreignkey")
        batch.drop_column("source_id")
        batch.alter_column("document_id", existing_type=sa.String(36), nullable=False)
    with op.batch_alter_table("chunks") as batch:
        batch.drop_index("ix_chunks_source_id")
        batch.drop_constraint("fk_chunks_source", type_="foreignkey")
        batch.drop_column("source_id")
        batch.alter_column("document_id", existing_type=sa.String(36), nullable=False)
    with op.batch_alter_table("documents") as batch:
        batch.drop_index("ix_documents_source_id")
        batch.drop_constraint("fk_documents_source", type_="foreignkey")
        batch.drop_column("source_id")
    KnowledgeSource.__table__.drop(op.get_bind(), checkfirst=True)
