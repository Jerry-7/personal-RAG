# Personal RAG - 后台索引工作器
"""
后台索引工作器模块

在 TaskManager 管理的后台任务中运行索引流水线。
使用独立的 DB 会话，通过 EventBus 实时推送进度。

此模块是 API 层和服务层的胶水代码：
- 从 documents.py 的 upload 端点调用 run_indexing()
- 通过 event_bus.publish() 推送进度到 SSE 端点
- 使用 SessionLocal() 创建独立 DB 会话
"""

import asyncio
import json
import logging

from app.db.database import SessionLocal
from app.config import settings
from app.db.models import Document, IndexJob
from app.services.event_bus import event_bus
from app.services.indexer import indexing_pipeline
from app.services.knowledge_sources import ensure_document_source

logger = logging.getLogger(__name__)


def index_config_snapshot() -> str:
    """Serialize settings that determine index compatibility."""
    model = (
        settings.openai_embedding_model
        if settings.embedding_provider == "openai"
        else settings.ollama_embedding_model
    )
    return json.dumps({
        "embedding_provider": settings.embedding_provider,
        "embedding_model": model,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
    }, ensure_ascii=False)


def ensure_index_job(db, doc_id: str) -> IndexJob:
    document = db.query(Document).filter(Document.id == doc_id).first()
    source_id = None
    if document:
        source_id = ensure_document_source(db, document).id
    job = db.query(IndexJob).filter(IndexJob.document_id == doc_id).first()
    if job is None:
        job = IndexJob(
            document_id=doc_id,
            source_id=source_id,
            status="queued",
            config_json=index_config_snapshot(),
        )
        db.add(job)
    else:
        job.source_id = source_id
        job.status = "queued"
        job.config_json = index_config_snapshot()
        job.error_message = None
    db.commit()
    return job


async def run_indexing(
    doc_id: str,
    file_path: str,
    original_name: str,
    file_type: str,
    file_hash: str,
) -> None:
    """
    在后台运行完整的文档索引流水线。

    此函数在 asyncio.create_task 中执行，有自己的 DB 会话。
    通过 EventBus 将进度实时推送给 SSE 订阅者。

    Args:
        doc_id: 文档唯一 ID（已在 upload 端点创建）
        file_path: 上传文件的本地路径
        original_name: 用户上传的原始文件名
        file_type: 文件类型扩展名
        file_hash: SHA-256 文件哈希值
    """
    db = SessionLocal()
    try:
        job = ensure_index_job(db, doc_id)
        job.status = "running"
        job.attempts += 1
        db.commit()

        async def progress_callback(status: str, message: str) -> None:
            """每步进度回调：发布 SSE 事件 + 更新数据库状态。"""
            event_bus.publish(doc_id, {
                "event": "progress",
                "data": {
                    "doc_id": doc_id,
                    "status": status,
                    "message": message,
                },
            })
            # 同步更新数据库状态，保证 GET /api/documents 也反映实时状态
            try:
                doc = db.query(Document).filter(Document.id == doc_id).first()
                if doc:
                    doc.status = status
                    db.commit()
            except Exception:
                logger.exception(f"更新文档状态失败, doc_id={doc_id}, status={status}")

        await indexing_pipeline.index_document(
            doc_id=doc_id,
            file_path=file_path,
            original_name=original_name,
            file_type=file_type,
            file_hash=file_hash,
            db=db,
            progress_callback=progress_callback,
        )

        # 最终成功事件
        # 查询最终的 chunk_count
        doc = db.query(Document).filter(Document.id == doc_id).first()
        chunk_count = doc.chunk_count if doc else 0

        job.status = "completed"
        job.error_message = None
        db.commit()
        event_bus.publish(doc_id, {
            "event": "done",
            "data": {
                "doc_id": doc_id,
                "status": "indexed",
                "chunk_count": chunk_count,
            },
        })

    except asyncio.CancelledError:
        db.rollback()
        job = db.query(IndexJob).filter(IndexJob.document_id == doc_id).first()
        if job:
            job.status = "queued"
            db.commit()
        raise
    except Exception as e:
        logger.exception(f"后台索引失败, doc_id={doc_id}")
        db.rollback()
        job = db.query(IndexJob).filter(IndexJob.document_id == doc_id).first()
        if job:
            job.status = "failed"
            job.error_message = str(e)
            db.commit()
        event_bus.publish(doc_id, {
            "event": "error",
            "data": {
                "doc_id": doc_id,
                "status": "error",
                "message": str(e),
            },
        })
    finally:
        db.close()


async def recover_pending_index_jobs() -> int:
    """Requeue jobs left unfinished by a previous process."""
    from app.services.task_manager import task_manager

    db = SessionLocal()
    submitted = 0
    try:
        jobs = db.query(IndexJob).filter(IndexJob.status.in_(("queued", "running"))).all()
        for job in jobs:
            if not task_manager.can_accept():
                break
            doc = db.query(Document).filter(Document.id == job.document_id).first()
            if not doc or not doc.file_path:
                job.status = "failed"
                job.error_message = "文档或源文件信息不存在"
                continue
            task_args = {
                "doc_id": doc.id,
                "file_path": doc.file_path,
                "original_name": doc.original_name,
                "file_type": doc.file_type,
                "file_hash": doc.file_hash,
            }
            await task_manager.submit(
                doc.id,
                lambda args=task_args: run_indexing(**args),
            )
            submitted += 1
        db.commit()
    finally:
        db.close()
    return submitted
