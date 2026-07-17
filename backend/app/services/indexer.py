# Personal RAG - 文档索引编排服务
"""
文档索引编排模块

编排解析 → 分块 → 嵌入 → 存储的完整流水线。
是 RAG 系统的核心入口，在后台异步运行，通过 SSE 通知前端进度。
"""

import asyncio
import hashlib
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.db.vector_store import vector_store
from app.services.chunker import chunker
from app.services.embedder import embedding_service
from app.services.parser.registry import parser_registry


class IndexingPipeline:
    """
    文档索引流水线。

    编排从文件上传到向量存储的全过程：
    parse → chunk → embed → store

    使用 FastAPI BackgroundTasks 异步执行，不阻塞 HTTP 响应。
    通过回调函数通知前端进度。
    """

    def __init__(self) -> None:
        """初始化索引流水线，使用全局单例服务。"""
        self._chunker = chunker
        self._embedder = embedding_service
        self._vector_store = vector_store

    async def index_document(
        self,
        *,
        doc_id: str,
        file_path: str,
        original_name: str,
        file_type: str,
        file_hash: str,
        db: Session,
        progress_callback: Optional[callable] = None,
    ) -> str:
        """
        执行完整的文档索引流程。

        Document 记录由调用方（upload 端点）预先创建，
        此方法只负责解析→分块→嵌入→存储→标记完成。

        Args:
            doc_id: 文档唯一 ID（由调用方创建）
            file_path: 上传文件的本地路径
            original_name: 用户上传的原始文件名
            file_type: 文件类型扩展名
            file_hash: SHA-256 文件哈希值
            db: SQLAlchemy 数据库会话
            progress_callback: 进度回调 async fn(status: str, message: str)

        Returns:
            文档 UUID

        Raises:
            ValueError: 文件类型不受支持
            RuntimeError: 索引过程中发生错误
        """
        from app.db.models import Document, Chunk

        # ── Step 1: 解析 ────────────────────────────────────
        await self._notify(progress_callback, "parsing", "正在解析文件...")
        parser = parser_registry.get_parser(file_type)
        if parser is None:
            self._mark_error(db, doc_id, f"不支持的文件类型: {file_type}")
            raise ValueError(f"不支持的文件类型: {file_type}")

        try:
            parsed_doc = parser.parse(file_path)
        except Exception as e:
            self._mark_error(db, doc_id, f"解析失败: {str(e)}")
            raise RuntimeError(f"解析文件失败: {e}") from e

        # 更新文档元数据
        doc_record = db.query(Document).filter(Document.id == doc_id).first()
        if doc_record:
            doc_record.status = "parsing"
            if parsed_doc.metadata.get("page_count"):
                doc_record.page_count = parsed_doc.metadata["page_count"]
            db.commit()

        # ── Step 2: 分块 ────────────────────────────────────
        await self._notify(progress_callback, "chunking", "正在文本分块...")
        chunks = self._chunker.chunk_parsed_document(parsed_doc)

        # ── Step 3: 嵌入 ────────────────────────────────────
        await self._notify(progress_callback, "embedding", f"正在生成向量 ({len(chunks)} 块)...")
        texts = [c["text"] for c in chunks]
        try:
            embeddings = await self._embedder.embed_batch(texts)
        except Exception as e:
            self._mark_error(db, doc_id, f"Embedding 失败: {str(e)}")
            raise RuntimeError(f"生成向量失败: {e}") from e

        # ── Step 4: 存储到 ChromaDB ─────────────────────────
        await self._notify(progress_callback, "storing", "正在存储向量...")
        chunk_ids = [str(uuid.uuid4()) for _ in chunks]
        metadatas = []
        for i, ch in enumerate(chunks):
            meta = {
                "document_id": doc_id,
                "chunk_id": chunk_ids[i],
                "chunk_index": ch["chunk_index"],
                "filename": original_name,
                "file_type": file_type,
                "page_number": ch["metadata"].get("page_number"),
                "start_timestamp": ch["metadata"].get("start_timestamp"),
                "end_timestamp": ch["metadata"].get("end_timestamp"),
                "source_type": ch["metadata"].get("source_type", "text"),
                "char_count": len(ch["text"]),
            }
            metadatas.append(meta)

        self._vector_store.add_chunks(
            chunk_ids=chunk_ids,
            texts=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        # ── Step 5: 存储 Chunk 记录到 SQLite ────────────────
        for i, ch in enumerate(chunks):
            chunk_record = Chunk(
                id=chunk_ids[i],
                document_id=doc_id,
                chunk_index=ch["chunk_index"],
                text=ch["text"],
                page_number=ch["metadata"].get("page_number"),
                start_timestamp=ch["metadata"].get("start_timestamp"),
                end_timestamp=ch["metadata"].get("end_timestamp"),
                token_count=len(ch["text"]) // 4,  # 粗略估算
                embedding_model=settings.ollama_embedding_model,
            )
            db.add(chunk_record)

        # ── Step 6: 更新文档状态 ────────────────────────────
        if doc_record:
            doc_record.status = "indexed"
            doc_record.chunk_count = len(chunks)
            doc_record.updated_at = __import__("datetime").datetime.now()
        db.commit()

        await self._notify(progress_callback, "indexed", f"索引完成 ({len(chunks)} 块)")
        return doc_id

    def _mark_error(self, db: Session, doc_id: str, message: str) -> None:
        """标记文档处理失败。"""
        from app.db.models import Document
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.status = "error"
            doc.error_message = message
            db.commit()

    async def delete_document(self, doc_id: str, db: Session) -> int:
        """
        删除文档及其所有关联数据。

        清理 SQLite 记录、ChromaDB 向量和磁盘文件。

        Args:
            doc_id: 要删除的文档 ID
            db: 数据库会话

        Returns:
            删除的向量分块数量
        """
        from app.db.models import Document, Chunk

        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return 0

        # 清理 ChromaDB 向量
        chunks_deleted = self._vector_store.delete_document(doc_id)

        # 清理 SQLite 记录（CASCADE 自动清理 chunks 和 messages 引用）
        db.query(Chunk).filter(Chunk.document_id == doc_id).delete()
        db.delete(doc)
        db.commit()

        # 清理磁盘文件（如果存在）
        file_path = Path(doc.file_path) if doc.file_path else None
        if file_path and file_path.exists():
            file_path.unlink()

        return chunks_deleted

    async def _notify(
        self,
        callback: Optional[callable],
        status: str,
        message: str,
    ) -> None:
        """发送进度通知。"""
        if callback:
            try:
                await callback(status, message)
            except Exception:
                pass  # 静默忽略通知失败


# 全局单例
indexing_pipeline = IndexingPipeline()
