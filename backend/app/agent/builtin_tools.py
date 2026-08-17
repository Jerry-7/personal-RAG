# Personal RAG - 内置 Agent 工具
"""
内置工具模块

将现有 RAG 检索服务包装为 Agent 可调用的工具。
内置工具通过显式的 AgentRunContext 获取请求级状态。

注册的工具：
- search_knowledge_base: 在已上传文档中搜索
- list_documents: 列出所有已索引文档
- read_chunk: 读取指定分块的完整文本

引用追踪：
    每次 search_knowledge_base 调用时，所有检索到的 chunk 会被
    注册到全局引用表中，分配唯一编号。LLM 在回答中使用 [N] 格式
    引用来源，chat.py 从引用表构建完整的 CitationData。
"""

import logging
from typing import Any

from app.agent.context import AgentRunContext
from app.agent.tools import tool_registry
from app.services.retriever import retriever
from app.services.text_utils import clip_to_sentence

logger = logging.getLogger(__name__)

def _register_chunks(
    context: AgentRunContext,
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    将检索到的 chunks 注册到全局引用表，分配唯一编号。

    Returns:
        带 citation_index 的 chunk 列表
    """
    registered = []
    for chunk in chunks:
        context.citation_counter += 1
        context.citations.append({
            "index": context.citation_counter,
            "document_id": chunk.get("document_id", ""),
            "chunk_id": chunk.get("chunk_id", ""),
            "source_id": chunk.get("source_id", ""),
            "snippet": clip_to_sentence(chunk.get("text", ""), 200),
            "filename": chunk.get("filename", ""),
            "page_number": chunk.get("page_number"),
            "start_timestamp": chunk.get("start_timestamp"),
            "end_timestamp": chunk.get("end_timestamp"),
            "source_type": chunk.get("source_type", "text"),
        })
        registered.append({**chunk, "_citation_index": context.citation_counter})
    return registered


async def _search_knowledge_base(
    query: str,
    top_k: int = 4,
    *,
    context: AgentRunContext,
) -> str:
    """
    在已上传文档中搜索相关内容。

    将用户的问题或关键词转为向量，在 FAISS 中检索最相似的分块，
    返回格式化的上下文文本供 LLM 使用。结果以全局编号 [N] 标记，
    LLM 在最终回答中应使用 [N] 引用来源。

    Args:
        query: 搜索关键词或问题
        top_k: 返回结果数量，默认 4
    """
    chunks = await retriever.retrieve(query, context.db, top_k=top_k)

    if not chunks:
        return "未找到相关文档。请尝试不同的搜索关键词。"

    # 注册到全局引用表，分配唯一编号
    registered = _register_chunks(context, chunks)

    # 格式化为 LLM 易读的格式，使用全局引用编号
    parts = []
    for chunk in registered:
        idx = chunk["_citation_index"]
        source_label = f"[{idx}] (from {chunk.get('filename', 'unknown')}"
        if chunk.get("page_number"):
            source_label += f", page {chunk['page_number']}"
        if chunk.get("start_timestamp") is not None:
            start = chunk["start_timestamp"]
            end = chunk.get("end_timestamp", start)
            m1, s1 = divmod(int(start), 60)
            m2, s2 = divmod(int(end), 60)
            source_label += f", {m1:02d}:{s1:02d}-{m2:02d}:{s2:02d}"
        source_label += ")"
        parts.append(f"{source_label}:\n{chunk['text']}")

    return "\n\n".join(parts)


async def _list_documents(*, context: AgentRunContext) -> str:
    """
    列出所有已上传且已索引的文档。

    返回文档 ID、文件名、类型、页数/时长等信息。
    """
    from app.db.models import Document

    docs = (
        context.db.query(Document)
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


async def _read_chunk(chunk_id: str, *, context: AgentRunContext) -> str:
    """
    读取指定分块的完整文本内容。

    用于在检索后获取更多上下文，或查看特定分块的详细信息。

    Args:
        chunk_id: 分块 UUID
    """
    from app.db.models import Chunk

    chunk = context.db.query(Chunk).filter(Chunk.id == chunk_id).first()

    if not chunk:
        return f"未找到分块: {chunk_id}"

    # 获取文档信息
    from app.db.models import Document, KnowledgeSource
    doc = context.db.query(Document).filter(Document.id == chunk.document_id).first()
    source = context.db.query(KnowledgeSource).filter(KnowledgeSource.id == chunk.source_id).first()
    doc_name = doc.original_name if doc else (source.title if source else "未知来源")

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
