"""Compatibility helpers for the shared document/note knowledge source model."""

from sqlalchemy.orm import Session

from app.db.models import Document, KnowledgeSource


def ensure_document_source(db: Session, document: Document) -> KnowledgeSource:
    """Backfill a document source lazily so old databases remain usable."""
    source_id = document.source_id or document.id
    with db.no_autoflush:
        source = db.query(KnowledgeSource).filter(KnowledgeSource.id == source_id).first()
    if source is None:
        source = KnowledgeSource(
            id=source_id,
            kind="document",
            title=document.original_name,
            index_status="indexed" if document.status == "indexed" else "not_indexed",
        )
        db.add(source)
    document.source_id = source.id
    return source
