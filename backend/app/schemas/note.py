from datetime import datetime

from pydantic import BaseModel, Field


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    summary: str = ""
    content_md: str = ""
    tag_ids: list[str] = Field(default_factory=list)
    collection_ids: list[str] = Field(default_factory=list)


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    summary: str | None = None
    content_md: str | None = None
    status: str | None = None
    tag_ids: list[str] | None = None
    collection_ids: list[str] | None = None


class ConversationDraftRequest(BaseModel):
    conversation_id: str


class TaxonomyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""


class NoteResponse(BaseModel):
    id: str
    title: str
    summary: str
    content_md: str
    status: str
    index_status: str
    conversation_id: str | None
    source_message_id: str | None
    tags: list[dict] = Field(default_factory=list)
    collections: list[dict] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    suggested_tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
