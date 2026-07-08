# Personal RAG - 文档管理 API
"""
文档管理 API 模块

提供文件上传、文档列表、删除等 REST 接口。
上传文件后触发后台异步索引流水线。
"""

import hashlib
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.db.models import Document
from app.schemas.document import (
    DeleteDocumentResponse,
    DocumentItem,
    DocumentListResponse,
    DocumentUploadResponse,
)
from app.services.indexer import indexing_pipeline
from app.services.parser.registry import parser_registry

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
    content = await file.read()
    file_size = len(content)

    if file_size > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超出限制 ({settings.max_upload_size_mb}MB)",
        )

    file_hash = hashlib.sha256(content).hexdigest()
    safe_name = f"{file_hash}_{file.filename}"
    dest_path = settings.upload_dir / safe_name
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(content)

    # ── 触发后台索引 ─────────────────────────────────────────
    try:
        doc_id = await indexing_pipeline.index_document(
            file_path=str(dest_path),
            original_name=file.filename,
            file_type=ext,
            file_hash=file_hash,
            db=db,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"索引失败: {str(e)}")

    # ── 查询文档信息 ─────────────────────────────────────────
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
