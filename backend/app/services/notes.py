"""Note drafting, source pinning, and opt-in indexing."""

import json
import uuid
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import (
    Chunk,
    Collection,
    ConversationSummary,
    KnowledgeSource,
    Message,
    Note,
    NoteCollection,
    NoteSource,
    NoteTag,
    Tag,
    WebSnapshot,
)
from app.db.vector_store import vector_store
from app.services.chunker import chunker
from app.services.embedder import embedding_service


class NoteService:
    def serialize(self, db: Session, note: Note) -> dict:
        tags = (
            db.query(Tag).join(NoteTag, NoteTag.tag_id == Tag.id)
            .filter(NoteTag.note_id == note.id).all()
        )
        collections = (
            db.query(Collection).join(NoteCollection, NoteCollection.collection_id == Collection.id)
            .filter(NoteCollection.note_id == note.id).all()
        )
        sources = db.query(NoteSource).filter(NoteSource.note_id == note.id).all()
        return {
            "id": note.id,
            "title": note.title,
            "summary": note.summary,
            "content_md": note.content_md,
            "status": note.status,
            "index_status": note.index_status,
            "conversation_id": note.conversation_id,
            "source_message_id": note.source_message_id,
            "tags": [{"id": item.id, "name": item.name} for item in tags],
            "collections": [
                {"id": item.id, "name": item.name, "description": item.description}
                for item in collections
            ],
            "sources": [
                {
                    "id": item.id,
                    "source_type": item.source_type,
                    "chunk_id": item.chunk_id,
                    "snapshot_id": item.snapshot_id,
                    "message_id": item.message_id,
                    "citation_index": item.citation_index,
                    "excerpt": item.excerpt,
                    "metadata": json.loads(item.metadata_json) if item.metadata_json else None,
                }
                for item in sources
            ],
            "suggested_tags": json.loads(note.suggested_tags_json or "[]"),
            "created_at": note.created_at,
            "updated_at": note.updated_at,
        }

    def create_draft_from_conversation(self, db: Session, conversation_id: str) -> Note:
        messages = (
            db.query(Message).filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc()).all()
        )
        if not messages:
            raise ValueError("对话不存在或没有消息")

        last_user = next((m for m in reversed(messages) if m.role == "user"), messages[0])
        last_assistant = next((m for m in reversed(messages) if m.role == "assistant"), None)
        title = last_user.content.strip().replace("\n", " ")[:80] or "对话笔记"
        summary_source = last_assistant.content if last_assistant else last_user.content
        summary = summary_source.strip()[:300]
        body_parts = [f"# {title}", "", summary]
        display_messages = messages
        rolling_summary = db.query(ConversationSummary).filter_by(conversation_id=conversation_id).first()
        if rolling_summary and rolling_summary.summary:
            body_parts.extend(["", "## 早期对话摘要", "", rolling_summary.summary])
            message_ids = [message.id for message in messages]
            if rolling_summary.through_message_id in message_ids:
                display_messages = messages[message_ids.index(rolling_summary.through_message_id) + 1:]
        for message in display_messages:
            label = "问题" if message.role == "user" else "回答"
            body_parts.extend(["", f"## {label}", "", message.content.strip()])

        terms = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,6}", last_user.content)
        suggested_tags = list(dict.fromkeys(term.lower() for term in terms))[:5]
        note = Note(
            title=title,
            summary=summary,
            content_md="\n".join(body_parts),
            status="draft",
            index_status="not_indexed",
            conversation_id=conversation_id,
            source_message_id=last_assistant.id if last_assistant else last_user.id,
            suggested_tags_json=json.dumps(suggested_tags, ensure_ascii=False),
        )
        db.add(note)
        db.flush()
        for message in messages:
            db.add(NoteSource(
                note_id=note.id, source_type="message", message_id=message.id,
                content=message.content,
                metadata_json=json.dumps({"role": message.role}, ensure_ascii=False),
            ))

        if last_assistant and last_assistant.citations_json:
            for citation in json.loads(last_assistant.citations_json):
                chunk_id = citation.get("chunk_id") or None
                chunk = db.query(Chunk).filter(Chunk.id == chunk_id).first() if chunk_id else None
                db.add(NoteSource(
                    note_id=note.id,
                    source_type=citation.get("source_type", "text"),
                    chunk_id=citation.get("chunk_id") or None,
                    snapshot_id=citation.get("snapshot_id") or None,
                    citation_index=citation.get("index"),
                    excerpt=citation.get("snippet", "")[:1000],
                    content=chunk.text if chunk else citation.get("snippet", ""),
                    metadata_json=json.dumps(citation, ensure_ascii=False),
                ))
        db.commit()
        db.refresh(note)
        return note

    def set_memberships(
        self, db: Session, note: Note, tag_ids: list[str] | None, collection_ids: list[str] | None
    ) -> None:
        if tag_ids is not None:
            db.query(NoteTag).filter(NoteTag.note_id == note.id).delete()
            valid = {row[0] for row in db.query(Tag.id).filter(Tag.id.in_(tag_ids)).all()} if tag_ids else set()
            for tag_id in valid:
                db.add(NoteTag(note_id=note.id, tag_id=tag_id))
        if collection_ids is not None:
            db.query(NoteCollection).filter(NoteCollection.note_id == note.id).delete()
            valid = {row[0] for row in db.query(Collection.id).filter(Collection.id.in_(collection_ids)).all()} if collection_ids else set()
            for collection_id in valid:
                db.add(NoteCollection(note_id=note.id, collection_id=collection_id))

    def publish(self, db: Session, note: Note) -> None:
        note.status = "published"
        snapshot_ids = [
            row[0] for row in db.query(NoteSource.snapshot_id)
            .filter(NoteSource.note_id == note.id, NoteSource.snapshot_id.is_not(None)).all()
        ]
        if snapshot_ids:
            db.query(WebSnapshot).filter(WebSnapshot.id.in_(snapshot_ids)).update(
                {WebSnapshot.is_pinned: True, WebSnapshot.expires_at: None},
                synchronize_session=False,
            )
        db.commit()

    async def index(self, db: Session, note: Note) -> int:
        if note.status != "published":
            raise ValueError("只有已发布笔记可以加入知识库")
        source = db.query(KnowledgeSource).filter(KnowledgeSource.id == note.source_id).first()
        if source is None:
            source = KnowledgeSource(id=note.id, kind="note", title=note.title, index_status="indexing")
            db.add(source)
            note.source_id = source.id
        source.title = note.title
        source.index_status = "indexing"

        old_ids = [row[0] for row in db.query(Chunk.id).filter(Chunk.source_id == source.id).all()]
        if old_ids:
            vector_store.delete_chunks(old_ids)
            db.query(Chunk).filter(Chunk.source_id == source.id).delete()

        parts = chunker.chunk_text(note.content_md, {"source_type": "note"})
        texts = [part["text"] for part in parts]
        embeddings = await embedding_service.embed_batch(texts) if texts else []
        chunk_ids = [str(uuid.uuid4()) for _ in parts]
        for index, part in enumerate(parts):
            db.add(Chunk(
                id=chunk_ids[index], source_id=source.id, document_id=None,
                chunk_index=index, text=part["text"], token_count=len(part["text"]) // 4,
                embedding_model=embedding_service.model_name,
            ))
        try:
            db.flush()
            vector_store.add_chunks(
                chunk_ids, texts, embeddings,
                [{"source_id": source.id, "source_type": "note", "title": note.title} for _ in parts],
            )
            note.index_status = "indexed"
            source.index_status = "indexed"
            source.content_version += 1
            db.commit()
        except Exception:
            db.rollback()
            vector_store.delete_chunks(chunk_ids)
            raise
        return len(parts)

    def remove_index(self, db: Session, note: Note) -> int:
        if not note.source_id:
            note.index_status = "not_indexed"
            db.commit()
            return 0
        ids = [row[0] for row in db.query(Chunk.id).filter(Chunk.source_id == note.source_id).all()]
        vector_store.delete_chunks(ids)
        db.query(Chunk).filter(Chunk.source_id == note.source_id).delete()
        source = db.query(KnowledgeSource).filter(KnowledgeSource.id == note.source_id).first()
        if source:
            source.index_status = "not_indexed"
        note.index_status = "not_indexed"
        db.commit()
        return len(ids)


note_service = NoteService()
