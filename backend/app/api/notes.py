from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import (
    Collection, Document, DocumentCollection, DocumentTag,
    Note, NoteCollection, NoteTag, Tag,
)
from app.schemas.note import ConversationDraftRequest, NoteCreate, NoteUpdate, TaxonomyCreate
from app.services.notes import note_service

router = APIRouter()


def _get_note(db: Session, note_id: str) -> Note:
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return note


@router.get("/notes")
async def list_notes(
    status: str | None = None,
    query: str | None = None,
    tag_id: str | None = None,
    collection_id: str | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
):
    notes_query = db.query(Note)
    if status:
        notes_query = notes_query.filter(Note.status == status)
    elif not include_archived:
        notes_query = notes_query.filter(Note.status != "archived")
    if query:
        notes_query = notes_query.filter(Note.title.contains(query) | Note.content_md.contains(query))
    if tag_id:
        notes_query = notes_query.join(NoteTag).filter(NoteTag.tag_id == tag_id)
    if collection_id:
        notes_query = notes_query.join(NoteCollection).filter(NoteCollection.collection_id == collection_id)
    notes = notes_query.order_by(Note.updated_at.desc()).all()
    return {"notes": [note_service.serialize(db, note) for note in notes], "total": len(notes)}


@router.post("/notes", status_code=201)
async def create_note(payload: NoteCreate, db: Session = Depends(get_db)):
    note = Note(title=payload.title, summary=payload.summary, content_md=payload.content_md)
    db.add(note)
    db.flush()
    note_service.set_memberships(db, note, payload.tag_ids, payload.collection_ids)
    db.commit()
    db.refresh(note)
    return note_service.serialize(db, note)


@router.get("/notes/{note_id}")
async def get_note(note_id: str, db: Session = Depends(get_db)):
    return note_service.serialize(db, _get_note(db, note_id))


@router.put("/notes/{note_id}")
async def update_note(note_id: str, payload: NoteUpdate, db: Session = Depends(get_db)):
    note = _get_note(db, note_id)
    content_changed = False
    for field in ("title", "summary", "content_md", "status"):
        value = getattr(payload, field)
        if value is not None:
            if field in {"title", "content_md"} and value != getattr(note, field):
                content_changed = True
            setattr(note, field, value)
    if note.status not in {"draft", "published", "archived"}:
        raise HTTPException(status_code=422, detail="无效的笔记状态")
    if content_changed and note.index_status == "indexed":
        note.index_status = "stale"
        if note.source_id:
            from app.db.models import KnowledgeSource
            source = db.query(KnowledgeSource).filter(KnowledgeSource.id == note.source_id).first()
            if source:
                source.index_status = "stale"
    note.updated_at = datetime.now(timezone.utc)
    note_service.set_memberships(db, note, payload.tag_ids, payload.collection_ids)
    db.commit()
    return note_service.serialize(db, note)


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str, db: Session = Depends(get_db)):
    note = _get_note(db, note_id)
    source_id = note.source_id
    note_service.remove_index(db, note)
    db.delete(note)
    db.flush()
    if source_id:
        from app.db.models import KnowledgeSource
        source = db.query(KnowledgeSource).filter(KnowledgeSource.id == source_id).first()
        if source:
            db.delete(source)
    db.commit()
    return {"id": note_id, "deleted": True}


@router.post("/notes/drafts/from-conversation", status_code=201)
async def draft_from_conversation(payload: ConversationDraftRequest, db: Session = Depends(get_db)):
    try:
        note = note_service.create_draft_from_conversation(db, payload.conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return note_service.serialize(db, note)


@router.post("/notes/{note_id}/publish")
async def publish_note(note_id: str, db: Session = Depends(get_db)):
    note = _get_note(db, note_id)
    note_service.publish(db, note)
    return note_service.serialize(db, note)


@router.post("/notes/{note_id}/index")
async def index_note(note_id: str, db: Session = Depends(get_db)):
    note = _get_note(db, note_id)
    try:
        count = await note_service.index(db, note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": note.id, "index_status": note.index_status, "chunk_count": count}


@router.delete("/notes/{note_id}/index")
async def remove_note_index(note_id: str, db: Session = Depends(get_db)):
    note = _get_note(db, note_id)
    count = note_service.remove_index(db, note)
    return {"id": note.id, "index_status": note.index_status, "chunks_deleted": count}


@router.get("/tags")
async def list_tags(db: Session = Depends(get_db)):
    return [{"id": item.id, "name": item.name} for item in db.query(Tag).order_by(Tag.name).all()]


@router.post("/tags", status_code=201)
async def create_tag(payload: TaxonomyCreate, db: Session = Depends(get_db)):
    if db.query(Tag).filter(Tag.name == payload.name).first():
        raise HTTPException(status_code=409, detail="标签已存在")
    item = Tag(name=payload.name)
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "name": item.name}


@router.put("/tags/{tag_id}")
async def update_tag(tag_id: str, payload: TaxonomyCreate, db: Session = Depends(get_db)):
    item = db.query(Tag).filter(Tag.id == tag_id).first()
    if not item: raise HTTPException(status_code=404, detail="标签不存在")
    item.name = payload.name; db.commit()
    return {"id": item.id, "name": item.name}


@router.delete("/tags/{tag_id}")
async def delete_tag(tag_id: str, db: Session = Depends(get_db)):
    item = db.query(Tag).filter(Tag.id == tag_id).first()
    if not item: raise HTTPException(status_code=404, detail="标签不存在")
    db.delete(item); db.commit()
    return {"id": tag_id, "deleted": True}


@router.get("/collections")
async def list_collections(db: Session = Depends(get_db)):
    return [{"id": i.id, "name": i.name, "description": i.description} for i in db.query(Collection).order_by(Collection.name).all()]


@router.post("/collections", status_code=201)
async def create_collection(payload: TaxonomyCreate, db: Session = Depends(get_db)):
    if db.query(Collection).filter(Collection.name == payload.name).first():
        raise HTTPException(status_code=409, detail="集合已存在")
    item = Collection(name=payload.name, description=payload.description)
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "name": item.name, "description": item.description}


@router.put("/collections/{collection_id}")
async def update_collection(collection_id: str, payload: TaxonomyCreate, db: Session = Depends(get_db)):
    item = db.query(Collection).filter(Collection.id == collection_id).first()
    if not item: raise HTTPException(status_code=404, detail="集合不存在")
    item.name = payload.name; item.description = payload.description; db.commit()
    return {"id": item.id, "name": item.name, "description": item.description}


@router.delete("/collections/{collection_id}")
async def delete_collection(collection_id: str, db: Session = Depends(get_db)):
    item = db.query(Collection).filter(Collection.id == collection_id).first()
    if not item: raise HTTPException(status_code=404, detail="集合不存在")
    db.delete(item); db.commit()
    return {"id": collection_id, "deleted": True}


@router.put("/tags/{tag_id}/notes/{note_id}")
async def add_note_tag(tag_id: str, note_id: str, db: Session = Depends(get_db)):
    _get_note(db, note_id)
    if not db.query(Tag).filter(Tag.id == tag_id).first(): raise HTTPException(status_code=404, detail="标签不存在")
    if not db.query(NoteTag).filter_by(note_id=note_id, tag_id=tag_id).first(): db.add(NoteTag(note_id=note_id, tag_id=tag_id)); db.commit()
    return {"note_id": note_id, "tag_id": tag_id}


@router.delete("/tags/{tag_id}/notes/{note_id}")
async def remove_note_tag(tag_id: str, note_id: str, db: Session = Depends(get_db)):
    db.query(NoteTag).filter_by(note_id=note_id, tag_id=tag_id).delete(); db.commit()
    return {"note_id": note_id, "tag_id": tag_id, "deleted": True}


@router.put("/collections/{collection_id}/notes/{note_id}")
async def add_note_collection(collection_id: str, note_id: str, db: Session = Depends(get_db)):
    _get_note(db, note_id)
    if not db.query(Collection).filter(Collection.id == collection_id).first(): raise HTTPException(status_code=404, detail="集合不存在")
    if not db.query(NoteCollection).filter_by(note_id=note_id, collection_id=collection_id).first(): db.add(NoteCollection(note_id=note_id, collection_id=collection_id)); db.commit()
    return {"note_id": note_id, "collection_id": collection_id}


@router.delete("/collections/{collection_id}/notes/{note_id}")
async def remove_note_collection(collection_id: str, note_id: str, db: Session = Depends(get_db)):
    db.query(NoteCollection).filter_by(note_id=note_id, collection_id=collection_id).delete(); db.commit()
    return {"note_id": note_id, "collection_id": collection_id, "deleted": True}


@router.put("/tags/{tag_id}/documents/{document_id}")
async def add_document_tag(tag_id: str, document_id: str, db: Session = Depends(get_db)):
    if not db.query(Document).filter(Document.id == document_id).first(): raise HTTPException(status_code=404, detail="文档不存在")
    if not db.query(Tag).filter(Tag.id == tag_id).first(): raise HTTPException(status_code=404, detail="标签不存在")
    if not db.query(DocumentTag).filter_by(document_id=document_id, tag_id=tag_id).first():
        db.add(DocumentTag(document_id=document_id, tag_id=tag_id)); db.commit()
    return {"document_id": document_id, "tag_id": tag_id}


@router.delete("/tags/{tag_id}/documents/{document_id}")
async def remove_document_tag(tag_id: str, document_id: str, db: Session = Depends(get_db)):
    db.query(DocumentTag).filter_by(document_id=document_id, tag_id=tag_id).delete(); db.commit()
    return {"document_id": document_id, "tag_id": tag_id, "deleted": True}


@router.put("/collections/{collection_id}/documents/{document_id}")
async def add_document_collection(collection_id: str, document_id: str, db: Session = Depends(get_db)):
    if not db.query(Document).filter(Document.id == document_id).first(): raise HTTPException(status_code=404, detail="文档不存在")
    if not db.query(Collection).filter(Collection.id == collection_id).first(): raise HTTPException(status_code=404, detail="集合不存在")
    if not db.query(DocumentCollection).filter_by(document_id=document_id, collection_id=collection_id).first():
        db.add(DocumentCollection(document_id=document_id, collection_id=collection_id)); db.commit()
    return {"document_id": document_id, "collection_id": collection_id}


@router.delete("/collections/{collection_id}/documents/{document_id}")
async def remove_document_collection(collection_id: str, document_id: str, db: Session = Depends(get_db)):
    db.query(DocumentCollection).filter_by(document_id=document_id, collection_id=collection_id).delete(); db.commit()
    return {"document_id": document_id, "collection_id": collection_id, "deleted": True}
