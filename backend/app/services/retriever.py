# Personal RAG - 检索服务
"""
检索服务模块

实现查询嵌入 → FAISS 向量搜索 → 元数据填充的完整检索流程。
从 FAISS 获取相似向量 ID 后，通过 SQLite 补充文本和元数据。
"""

import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.db.vector_store import vector_store
from app.services.embedder import embedding_service


class Retriever:
    """
    RAG 检索器。

    将用户查询转为 embedding 向量，在 FAISS 中执行相似度搜索，
    通过 SQLite 补充完整的分块文本和元数据。
    """

    def __init__(self) -> None:
        """初始化检索器。"""
        self._vector_store = vector_store
        self._embedder = embedding_service

    async def retrieve(
        self,
        query: str,
        db: Session,
        top_k: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """
        执行 RAG 检索。

        完整流程：
        1. 将查询文本转为 embedding
        2. 在 FAISS 中搜索最相似的 top_k 个向量
        3. 通过 SQLite chunks 表获取完整文本和元数据

        Args:
            query: 用户查询文本
            db: SQLAlchemy 数据库会话
            top_k: 检索数量，默认从配置读取

        Returns:
            检索结果列表，每项包含:
                - chunk_id: 分块 ID
                - text: 分块完整文本
                - filename: 来源文件名
                - page_number: 页码 (PDF)
                - start_timestamp/end_timestamp: 时间戳 (视频)
                - source_type: 来源类型 (text/video/audio)
                - score: 相似度分数 (0-1, 越高越相似)
        """
        from app.db.models import Chunk

        k = top_k or settings.retrieval_top_k

        # Step 1: 查询嵌入
        query_vec = await self._embedder.embed_single(query)

        # Step 2: FAISS 向量搜索
        results = self._vector_store.query(query_vec, n_results=k)

        if not results["ids"] or not results["ids"][0]:
            return []

        chunk_ids = results["ids"][0]
        distances = results["distances"][0] if results["distances"] else []

        # Step 3: 从 SQLite 获取元数据和文本
        chunks_map = {}
        if chunk_ids:
            db_chunks = db.query(Chunk).filter(Chunk.id.in_(chunk_ids)).all()
            for ch in db_chunks:
                chunks_map[ch.id] = ch

        # 组装结果
        retrieved = []
        for i, chunk_id in enumerate(chunk_ids):
            chunk_record = chunks_map.get(chunk_id)
            if not chunk_record:
                continue

            # 相似度: FAISS IndexFlatIP 返回的是内积 (归一化向量 = cosine)
            # 范围 [-1, 1]，转换为 [0, 1]
            score = distances[i] if i < len(distances) else 0.0
            score_normalized = (score + 1.0) / 2.0  # [-1,1] → [0,1]

            retrieved.append({
                "chunk_id": chunk_id,
                "document_id": chunk_record.document_id,
                "text": chunk_record.text,
                "filename": "",  # 从 document 表填充
                "page_number": chunk_record.page_number,
                "start_timestamp": chunk_record.start_timestamp,
                "end_timestamp": chunk_record.end_timestamp,
                "source_type": "video" if chunk_record.start_timestamp is not None else "text",
                "score": round(score_normalized, 4),
            })

        # 填充文件名
        if retrieved:
            from app.db.models import Document
            doc_ids = list({r["document_id"] for r in retrieved if r["document_id"]})
            docs = db.query(Document).filter(Document.id.in_(doc_ids)).all()
            doc_name_map = {d.id: d.original_name for d in docs}
            for r in retrieved:
                r["filename"] = doc_name_map.get(r["document_id"], "")

        # 按相似度排序
        retrieved.sort(key=lambda x: x["score"], reverse=True)
        return retrieved[:k]


# 全局单例
retriever = Retriever()
