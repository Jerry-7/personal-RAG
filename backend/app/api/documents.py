# Personal RAG - 文档管理 API
"""
文档管理 API 模块

提供文件上传、文档列表、删除等 REST 接口。
上传文件后触发后台异步索引流水线。
"""

import asyncio
import hashlib
import json
import uuid
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.db.database import SessionLocal
from app.db.models import Document, IndexJob
from app.schemas.document import (
    DeleteDocumentResponse,
    DocumentItem,
    DocumentListResponse,
    DocumentUploadResponse,
)
from app.services.event_bus import event_bus
from app.services.indexer import indexing_pipeline
from app.services.indexing_worker import ensure_index_job, run_indexing
from app.services.knowledge_sources import ensure_document_source
from app.services.parser.registry import parser_registry
from app.services.task_manager import task_manager
from app.utils.file_utils import get_safe_filename

router = APIRouter()


@router.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    上传文档文件并触发异步索引。

    支持的格式：PDF, DOCX, TXT, MD, CSV, MP4, MP3, JPG, PNG 等。
    文件保存后立即返回文档 ID，索引在后台异步执行。

    Args:
        file: 上传的文件 (multipart/form-data)
        db: 数据库会话

    Returns:
        DocumentUploadResponse: 文档基本信息

    Raises:
        HTTPException 400: 不支持的文件格式或文件过大
    """
    # ── 验证文件扩展名 ───────────────────────────────────────
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    ext = Path(file.filename).suffix.lower().lstrip(".")
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: .{ext}。支持: {', '.join(settings.allowed_extensions)}",
        )

    if not parser_registry.is_supported(ext):
        raise HTTPException(
            status_code=400,
            detail=f"该文件格式暂无解析器支持: .{ext}",
        )

    # ── 保存文件 ─────────────────────────────────────────────
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path = settings.upload_dir / f".{uuid.uuid4()}.uploading"
    hasher = hashlib.sha256()
    file_size = 0
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    try:
        async with aiofiles.open(temp_path, "wb") as output:
            while chunk := await file.read(1024 * 1024):
                file_size += len(chunk)
                if file_size > max_bytes:
                    raise HTTPException(
                        status_code=400,
                        detail=f"文件大小超出限制 ({settings.max_upload_size_mb}MB)",
                    )
                hasher.update(chunk)
                await output.write(chunk)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    file_hash = hasher.hexdigest()
    safe_name = get_safe_filename(file.filename, file_hash)
    dest_path = settings.upload_dir / safe_name
    destination_existed = dest_path.exists()
    temp_path.replace(dest_path)

    # ── 去重检查 ──────────────────────────────────────────────
    existing = db.query(Document).filter(Document.file_hash == file_hash).first()
    if existing and existing.status == "indexed":
        return DocumentUploadResponse(
            id=existing.id,
            filename=existing.filename,
            original_name=existing.original_name,
            file_type=existing.file_type,
            status=existing.status,
            created_at=existing.created_at,
        )

    # ── 检查队列容量 ─────────────────────────────────────────
    if not task_manager.can_accept():
        if not destination_existed and existing is None:
            dest_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=429,
            detail=f"索引队列已满 ({task_manager.active_count}/{task_manager.max_concurrent})，请稍后再试",
        )

    if existing:
        # 存在但未成功索引，重用记录
        doc_id = existing.id
    else:
        # 创建文档记录（indexer 不再负责创建）
        doc_id = str(uuid.uuid4())
        from app.db.models import KnowledgeSource
        db.add(KnowledgeSource(id=doc_id, kind="document", title=file.filename))
        doc = Document(
            id=doc_id,
            source_id=doc_id,
            filename=safe_name,
            original_name=file.filename,
            file_type=ext,
            file_size_bytes=file_size,
            file_hash=file_hash,
            file_path=str(dest_path),
            status="uploaded",
        )
        db.add(doc)
        db.commit()

    if existing:
        ensure_document_source(db, existing)
        db.commit()

    # ── 提交后台索引任务 ─────────────────────────────────────
    ensure_index_job(db, doc_id)
    file_path_str = str(dest_path)
    await task_manager.submit(
        doc_id,
        lambda: run_indexing(
            doc_id=doc_id,
            file_path=file_path_str,
            original_name=file.filename,
            file_type=ext,
            file_hash=file_hash,
        ),
    )

    # ── 立即返回 ─────────────────────────────────────────────
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=500, detail="文档创建失败")

    return DocumentUploadResponse(
        id=doc.id,
        filename=doc.filename,
        original_name=doc.original_name,
        file_type=doc.file_type,
        status=doc.status,
        created_at=doc.created_at,
    )


@router.get("/documents/{doc_id}/progress")
async def stream_document_progress(doc_id: str):
    """
    通过 SSE 流式推送单个文档的索引进度。

    前端上传文件后立即连接此端点，接收实时进度事件。
    事件类型：
      - progress: 索引进度更新（parsing/chunking/embedding/storing）
      - done: 索引成功完成
      - error: 索引失败

    Args:
        doc_id: 文档唯一 ID

    Returns:
        StreamingResponse (text/event-stream)
    """
    queue = event_bus.subscribe(doc_id)

    async def event_generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=2.0)
                except TimeoutError:
                    with SessionLocal() as status_db:
                        job = status_db.query(IndexJob).filter(IndexJob.document_id == doc_id).first()
                        doc = status_db.query(Document).filter(Document.id == doc_id).first()
                        if not doc:
                            yield "event: error\ndata: {\"status\":\"error\",\"message\":\"文档不存在\"}\n\n"
                            break
                        if (job and job.status == "completed") or doc.status == "indexed":
                            data = json.dumps({
                                "doc_id": doc_id,
                                "status": "indexed",
                                "chunk_count": doc.chunk_count,
                            }, ensure_ascii=False)
                            yield f"event: done\ndata: {data}\n\n"
                            break
                        if (job and job.status == "failed") or doc.status == "error":
                            message = (job.error_message if job else None) or doc.error_message or "索引失败"
                            data = json.dumps({
                                "doc_id": doc_id,
                                "status": "error",
                                "message": message,
                            }, ensure_ascii=False)
                            yield f"event: error\ndata: {data}\n\n"
                            break
                    continue
                event_type = event.get("event", "progress")
                data = json.dumps(event.get("data", {}), ensure_ascii=False)
                yield f"event: {event_type}\ndata: {data}\n\n"
                if event_type in ("done", "error"):
                    break
        except asyncio.CancelledError:
            # 客户端断开连接
            pass
        finally:
            event_bus.unsubscribe(doc_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    status: Optional[str] = None,
    file_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    获取已上传文档列表。

    支持按状态和文件类型过滤。

    Args:
        status: 过滤状态 (uploaded/indexed/error)
        file_type: 过滤文件类型 (pdf/docx/txt/...)
        db: 数据库会话

    Returns:
        DocumentListResponse: 文档列表和总数
    """
    query = db.query(Document)
    if status:
        query = query.filter(Document.status == status)
    if file_type:
        query = query.filter(Document.file_type == file_type)

    docs = query.order_by(Document.created_at.desc()).all()
    return DocumentListResponse(
        documents=[DocumentItem.model_validate(d) for d in docs],
        total=len(docs),
    )


@router.delete("/documents/{doc_id}", response_model=DeleteDocumentResponse)
async def delete_document(doc_id: str, db: Session = Depends(get_db)):
    """
    删除指定文档及其关联数据。

    清理 SQLite 记录、ChromaDB 向量和磁盘文件。

    Args:
        doc_id: 文档唯一 ID
        db: 数据库会话

    Returns:
        DeleteDocumentResponse: 删除结果

    Raises:
        HTTPException 404: 文档不存在
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    chunks_deleted = await indexing_pipeline.delete_document(doc_id, db)
    return DeleteDocumentResponse(
        document_id=doc_id,
        chunks_deleted=chunks_deleted,
    )
