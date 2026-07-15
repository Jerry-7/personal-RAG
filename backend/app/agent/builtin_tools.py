# Personal RAG - 内置 Agent 工具
"""
内置工具模块

将现有 RAG 检索服务包装为 Agent 可调用的工具。
使用 contextvars 获取当前请求的数据库会话。

注册的工具：
- search_knowledge_base: 在已上传文档中搜索
- list_documents: 列出所有已索引文档
- read_chunk: 读取指定分块的完整文本
"""

import logging
from contextvars import ContextVar
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.agent.tools import tool_registry
from app.services.retriever import retriever

logger = logging.getLogger(__name__)

# 当前请求的数据库会话（由 AgentLoop 设置）
_current_db: ContextVar[Optional[Session]] = ContextVar("agent_db", default=None)


def set_db_context(db: Session) -> None:
    """设置当前请求的数据库会话上下文。"""
    _current_db.set(db)


def _get_db() -> Session:
    """获取当前请求的数据库会话。"""
    db = _current_db.get()
    if db is None:
        raise RuntimeError("数据库会话未设置，请先调用 set_db_context()")
    return db


async def _search_knowledge_base(query: str, top_k: int = 4) -> str:
    """
    在已上传文档中搜索相关内容。

    将用户的问题或关键词转为向量，在 FAISS 中检索最相似的分块，
    返回格式化的上下文文本供 LLM 使用。

    Args:
        query: 搜索关键词或问题
        top_k: 返回结果数量，默认 4
    """
    db = _get_db()
    chunks = await retriever.retrieve(query, db, top_k=top_k)

    if not chunks:
        return "未找到相关文档。请尝试不同的搜索关键词。"

    # 格式化为 LLM 易读的格式（复用 generator 的格式逻辑）
    from app.services.generator import generator

    return generator.build_context(chunks)


async def _list_documents() -> str:
    """
    列出所有已上传且已索引的文档。

    返回文档 ID、文件名、类型、页数/时长等信息。
    """
    from app.db.models import Document

    db = _get_db()
    docs = (
        db.query(Document)
        .filter(Document.status == "indexed")
        .order_by(Document.updated_at.desc())
        .all()
    )

    if not docs:
        return "暂无已索引的文档。请先上传文档。"

    lines = ["已索引的文档列表:"]
    for i, doc in enumerate(docs, start=1):
        name = doc.original_name
        ftype = doc.file_type
        extra = ""
        if doc.page_count:
            extra = f", {doc.page_count}页"
        elif doc.duration_secs:
            extra = f", {doc.duration_secs:.0f}秒"
        lines.append(
            f"{i}. [{doc.id}] {name} ({ftype}{extra})"
        )

    return "\n".join(lines)


async def _read_chunk(chunk_id: str) -> str:
    """
    读取指定分块的完整文本内容。

    用于在检索后获取更多上下文，或查看特定分块的详细信息。

    Args:
        chunk_id: 分块 UUID
    """
    from app.db.models import Chunk

    db = _get_db()
    chunk = db.query(Chunk).filter(Chunk.id == chunk_id).first()

    if not chunk:
        return f"未找到分块: {chunk_id}"

    # 获取文档信息
    from app.db.models import Document
    doc = db.query(Document).filter(Document.id == chunk.document_id).first()
    doc_name = doc.original_name if doc else "未知文档"

    parts = [f"文档: {doc_name}"]
    if chunk.page_number:
        parts.append(f"页码: {chunk.page_number}")
    if chunk.start_timestamp is not None:
        parts.append(f"时间: {chunk.start_timestamp:.1f}s - {chunk.end_timestamp:.1f}s")
    parts.append(f"\n完整文本:\n{chunk.text}")

    return "\n".join(parts)


def register_builtin_tools() -> None:
    """
    注册所有内置工具到全局 tool_registry。

    该函数在模块首次导入时调用一次。
    重复调用安全（同名工具会覆盖更新）。
    """
    tool_registry.register(
        name="search_knowledge_base",
        description="在已上传文档中搜索相关内容。输入搜索关键词，返回匹配的文档片段。"
                    "可以多次调用，使用不同的关键词来获取更多信息。",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或问题。使用具体的术语或短语，而非完整句子。",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回的搜索结果数量，默认 4。如果预期信息分散在多个文档中可适当增大。",
                },
            },
            "required": ["query"],
        },
        handler=_search_knowledge_base,
        source="builtin",
    )

    tool_registry.register(
        name="list_documents",
        description="列出所有已上传且已索引的文档，返回文档ID、文件名、类型、页数/时长等信息。"
                    "在用户询问\"有哪些文档\"或需要选择特定文档时使用。",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=_list_documents,
        source="builtin",
    )

    tool_registry.register(
        name="read_chunk",
        description="读取指定分块的完整文本内容。在需要查看某个搜索结果的更多上下文时使用。",
        parameters={
            "type": "object",
            "properties": {
                "chunk_id": {
                    "type": "string",
                    "description": "分块的 UUID（从 search_knowledge_base 结果中获取）",
                },
            },
            "required": ["chunk_id"],
        },
        handler=_read_chunk,
        source="builtin",
    )

    logger.info("Built-in agent tools registered: %d tools", 3)


# 模块导入时自动注册
register_builtin_tools()
