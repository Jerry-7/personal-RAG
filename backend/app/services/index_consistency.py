"""Consistency checks between SQLite chunk metadata and the FAISS index."""

from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, IndexJob, KnowledgeSource, Note
from app.db.vector_store import vector_store


def repair_vector_index(db: Session) -> dict[str, int]:
    """Remove orphan vectors and queue documents with missing vectors for rebuild."""
    sqlite_ids = {row[0] for row in db.query(Chunk.id).all()}
    vector_ids = vector_store.chunk_ids()
    orphan_ids = vector_ids - sqlite_ids
    if orphan_ids:
        vector_store.delete_chunks(list(orphan_ids))
    # 数据库中有 但是向量数据库中没有的id
    missing_ids = sqlite_ids - vector_ids
    affected_documents: set[str] = set()
    affected_note_sources: set[str] = set()
    if missing_ids:
        affected_documents = {
            row[0]
            for row in db.query(Chunk.document_id).filter(
                Chunk.id.in_(missing_ids), Chunk.document_id.is_not(None)
            ).distinct().all()
        }
        affected_note_sources = {
            row[0]
            for row in db.query(Chunk.source_id).filter(
                Chunk.id.in_(missing_ids), Chunk.document_id.is_(None)
            ).distinct().all()
        }

    for doc_id in affected_documents:
        document_chunk_ids = [
            row[0]
            for row in db.query(Chunk.id).filter(Chunk.document_id == doc_id).all()
        ]
        vector_store.delete_chunks(document_chunk_ids)
        db.query(Chunk).filter(Chunk.document_id == doc_id).delete()
        document = db.query(Document).filter(Document.id == doc_id).first()
        if document:
            document.status = "uploaded"
            document.chunk_count = 0
            document.error_message = "检测到向量索引不完整，已排队重建"
        job = db.query(IndexJob).filter(IndexJob.document_id == doc_id).first()
        if job:
            job.status = "queued"
            job.error_message = None
        else:
            db.add(IndexJob(
                document_id=doc_id,
                source_id=document.source_id if document else doc_id,
                status="queued",
                config_json="{}",
            ))

    for source_id in affected_note_sources:
        note_chunk_ids = [row[0] for row in db.query(Chunk.id).filter(Chunk.source_id == source_id).all()]
        vector_store.delete_chunks(note_chunk_ids)
        db.query(Chunk).filter(Chunk.source_id == source_id).delete()
        note = db.query(Note).filter(Note.source_id == source_id).first()
        source = db.query(KnowledgeSource).filter(KnowledgeSource.id == source_id).first()
        if note:
            note.index_status = "stale"
        if source:
            source.index_status = "stale"

    db.commit()
    return {
        "orphan_vectors_removed": len(orphan_ids),
        "documents_queued": len(affected_documents),
        "notes_marked_stale": len(affected_note_sources),
    }
