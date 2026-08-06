# Personal RAG - SQLAlchemy ORM 模型定义
"""
数据库 ORM 模型模块

定义文档、分块、对话、消息和设置五个核心表。
每个模型映射到 SQLite 中的对应表。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def _new_id() -> str:
    """生成唯一 ID (UUID7 格式，时间排序友好)。"""
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    """获取当前 UTC 时间。"""
    return datetime.now(timezone.utc)


class Document(Base):
    """
    已上传文档的元数据记录。

    跟踪文件解析和索引状态，存储原始文件信息和内容统计。
    """

    __tablename__ = "documents"

    # ── 主键 & 文件标识 ──────────────────────────────────────
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        unique=True, nullable=False, index=True,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    # ── 状态 & 统计 ──────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="uploaded", index=True
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, nullable=True)
    duration_secs: Mapped[float] = mapped_column(Float, nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)

    # ── 时间戳 ───────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )

    # ── 关系 ─────────────────────────────────────────────────
    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk", back_populates="document", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, name={self.original_name}, status={self.status})>"


class Chunk(Base):
    """
    文档分块记录。

    每个分块对应文档中的一段连续文本，存储于 ChromaDB 之外的元数据索引。
    视频/音频文件额外包含时间戳信息。
    """

    __tablename__ = "chunks"

    # ── 主键 & 关联 ──────────────────────────────────────────
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # ── 内容 & 元数据 ────────────────────────────────────────
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=True)
    start_timestamp: Mapped[float] = mapped_column(Float, nullable=True)
    end_timestamp: Mapped[float] = mapped_column(Float, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # ── 关系 ─────────────────────────────────────────────────
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

    def __repr__(self) -> str:
        return f"<Chunk(id={self.id}, doc={self.document_id}, index={self.chunk_index})>"


class Conversation(Base):
    """
    对话会话记录。

    每次聊天会话创建一个 Conversation，包含多条 Message。
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    title: Mapped[str] = mapped_column(String(512), nullable=True)
    model_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )

    # ── 关系 ─────────────────────────────────────────────────
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, title={self.title})>"


class Message(Base):
    """
    对话消息记录。

    存储用户问题和 AI 回答，包括引用元数据的 JSON 序列化。
    """

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations_json: Mapped[str] = mapped_column(Text, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # ── 关系 ─────────────────────────────────────────────────
    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, role={self.role})>"


class Setting(Base):
    """
    系统设置键值存储。

    存储 LLM/Embedding provider 配置、API keys、以及 RAG 参数。
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:
        return f"<Setting(key={self.key})>"


class IndexJob(Base):
    """Persistent state for a document indexing attempt."""

    __tablename__ = "index_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"),
        unique=True, nullable=True, index=True,
    )
    source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        unique=True, nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )


class KnowledgeSource(Base):
    """Common indexable source shared by documents and notes."""

    __tablename__ = "knowledge_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    index_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_indexed", index=True)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    assistant_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    agent_profile: Mapped[str] = mapped_column(String(64), nullable=False, default="standard_research")
    route_tier: Mapped[str] = mapped_column(String(16), nullable=False, default="standard")
    route_name: Mapped[str] = mapped_column(String(32), nullable=False, default="tool_agent")
    route_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    route_reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    route_requires_decomposition: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True)
    web_page_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    web_pages_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ToolExecution(Base):
    __tablename__ = "tool_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    arguments_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, server_default=func.now())


class WebSnapshot(Base):
    __tablename__ = "web_snapshots"
    __table_args__ = (UniqueConstraint("canonical_url", "content_hash", name="uq_web_snapshot_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False, default="text/html")
    http_status: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ResearchRunSnapshot(Base):
    __tablename__ = "research_run_snapshots"
    __table_args__ = (UniqueConstraint("run_id", "snapshot_id", name="uq_run_snapshot"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("web_snapshots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, server_default=func.now())


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    through_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), unique=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    suggested_tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    index_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_indexed", index=True)
    conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Collection(Base):
    __tablename__ = "collections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class NoteTag(Base):
    __tablename__ = "note_tags"
    note_id: Mapped[str] = mapped_column(String(36), ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[str] = mapped_column(String(36), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class NoteCollection(Base):
    __tablename__ = "note_collections"
    note_id: Mapped[str] = mapped_column(String(36), ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(36), ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True)


class DocumentTag(Base):
    __tablename__ = "document_tags"
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[str] = mapped_column(String(36), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class DocumentCollection(Base):
    __tablename__ = "document_collections"
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(36), ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True)


class NoteSource(Base):
    __tablename__ = "note_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    note_id: Mapped[str] = mapped_column(String(36), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    chunk_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("web_snapshots.id", ondelete="SET NULL"), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    citation_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
