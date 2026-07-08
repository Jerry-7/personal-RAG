# Personal RAG - SQLAlchemy ORM 模型定义
"""
数据库 ORM 模型模块

定义文档、分块、对话、消息和设置五个核心表。
每个模型映射到 SQLite 中的对应表。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
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
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
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
