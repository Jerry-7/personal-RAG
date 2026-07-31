# Personal RAG - 检索服务
"""
检索服务模块

实现查询嵌入 → FAISS 向量搜索 → 元数据填充的完整检索流程。
从 FAISS 获取相似向量 ID 后，通过 SQLite 补充文本和元数据。
"""

import logging
import re
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.vector_store import vector_store
from app.services.embedder import embedding_service

logger = logging.getLogger(__name__)


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

        candidate_k = max(k * 2, k)
        vector_ids: list[str] = []
        vector_scores: dict[str, float] = {}
        try:
            query_vec = await self._embedder.embed_single(query)
            results = self._vector_store.query(query_vec, n_results=candidate_k)
            vector_ids = results["ids"][0] if results["ids"] else []
            distances = results["distances"][0] if results["distances"] else []
            vector_scores = {
                chunk_id: (distances[index] + 1.0) / 2.0
                for index, chunk_id in enumerate(vector_ids)
                if index < len(distances)
            }
        except Exception:
            logger.exception("Vector retrieval failed; continuing with lexical recall")

        lexical_ids = self._lexical_search(query, db, candidate_k)
        chunk_ids, fused_scores = self._reciprocal_rank_fusion(vector_ids, lexical_ids)
        chunk_ids = chunk_ids[:candidate_k]
        if not chunk_ids:
            return []

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
            score_normalized = fused_scores.get(chunk_id, vector_scores.get(chunk_id, 0.0))

            retrieved.append({
                "chunk_id": chunk_id,
                "source_id": chunk_record.source_id or chunk_record.document_id,
                "document_id": chunk_record.document_id,
                "text": chunk_record.text,
                "filename": "",  # 从 document 表填充
                "page_number": chunk_record.page_number,
                "start_timestamp": chunk_record.start_timestamp,
                "end_timestamp": chunk_record.end_timestamp,
                "source_type": "video" if chunk_record.start_timestamp is not None else "text",
                "score": round(score_normalized, 4),
            })

        # Fill display names for both legacy documents and indexed notes.
        if retrieved:
            from app.db.models import Document, KnowledgeSource
            doc_ids = list({r["document_id"] for r in retrieved if r["document_id"]})
            docs = db.query(Document).filter(Document.id.in_(doc_ids)).all()
            doc_name_map = {d.id: d.original_name for d in docs}
            source_ids = list({r["source_id"] for r in retrieved if r["source_id"]})
            sources = db.query(KnowledgeSource).filter(KnowledgeSource.id.in_(source_ids)).all()
            source_map = {source.id: source for source in sources}
            for r in retrieved:
                source = source_map.get(r["source_id"])
                r["filename"] = doc_name_map.get(r["document_id"], source.title if source else "")
                if source and source.kind == "note":
                    r["source_type"] = "note"

        # 按相似度排序
        retrieved.sort(key=lambda x: x["score"], reverse=True)
        return retrieved[:k]

    def _lexical_search(self, query: str, db: Session, limit: int) -> list[str]:
        """Recall exact terms through FTS5, with LIKE as a portable fallback."""
        normalized = query.strip()
        if not normalized:
            return []
        try:
            fts_query = self._build_fts_query(normalized)
            if not fts_query:
                raise ValueError("query is too short for trigram FTS")
            rows = db.execute(text(
                "SELECT chunks.id FROM chunks_fts "
                "JOIN chunks ON chunks.rowid = chunks_fts.rowid "
                "WHERE chunks_fts MATCH :query ORDER BY bm25(chunks_fts) LIMIT :limit"
            ), {"query": fts_query, "limit": limit}).all()
            return [row[0] for row in rows]
        except Exception:
            db.rollback()
            escaped = normalized.replace("%", "\\%").replace("_", "\\_")
            rows = db.execute(text(
                "SELECT id FROM chunks WHERE text LIKE :query ESCAPE '\\' LIMIT :limit"
            ), {"query": f"%{escaped}%", "limit": limit}).all()
            return [row[0] for row in rows]

    @staticmethod
    def _build_fts_query(query: str) -> str:
        """Build a broad trigram OR query that works for Chinese and English."""
        grams: list[str] = []
        for segment in re.findall(r"[\w\u4e00-\u9fff]+", query.lower()):
            if len(segment) < 3:
                continue
            grams.extend(segment[index:index + 3] for index in range(len(segment) - 2))
        unique_grams = list(dict.fromkeys(grams))[:16]
        return " OR ".join(f'"{gram}"' for gram in unique_grams)

    @staticmethod
    def _reciprocal_rank_fusion(
        vector_ids: list[str],
        lexical_ids: list[str],
        rank_constant: int = 60,
    ) -> tuple[list[str], dict[str, float]]:
        scores: dict[str, float] = {}
        for ranking in (vector_ids, lexical_ids):
            for rank, chunk_id in enumerate(ranking, start=1):
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rank_constant + rank)
        ordered = sorted(scores, key=scores.get, reverse=True)
        if not scores:
            return [], {}
        max_score = max(scores.values())
        normalized = {chunk_id: score / max_score for chunk_id, score in scores.items()}
        return ordered, normalized


# 全局单例
retriever = Retriever()
