# Personal RAG - 引用来源查询 API
"""
来源查询 API 模块

提供引用来源的详细信息查询，包括文本来源的高亮内容和
视频来源的时间戳定位信息。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db

router = APIRouter()


@router.get("/sources/{doc_id}/chunks/{chunk_id}")
async def get_source_chunk(
    doc_id: str,
    chunk_id: str,
    db: Session = Depends(get_db),
):
    """
    获取引用来源的详细信息。

    用于 Citation Sidebar 展示：
    - 文本来源：返回高亮分块 + 上下文
    - 视频来源：返回时间戳 + 转录文本

    Args:
        doc_id: 文档 ID
        chunk_id: 分块 ID

    Returns:
        SourceResponse: 包含文档信息、分块内容和相邻上下文

    Raises:
        HTTPException 404: 文档或分块不存在
    """
    # TODO: Phase 2 完整实现
    from app.db.models import Chunk, Document
    from app.db.vector_store import vector_store

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    chunk_record = db.query(Chunk).filter(
        Chunk.id == chunk_id, Chunk.document_id == doc_id
    ).first()
    if not chunk_record:
        # 尝试从 ChromaDB 查询
        vec_data = vector_store.get_chunk(chunk_id)
        if not vec_data:
            raise HTTPException(status_code=404, detail="分块不存在")
        return {
            "document": {
                "id": doc.id,
                "filename": doc.filename,
                "original_name": doc.original_name,
                "file_type": doc.file_type,
                "page_count": doc.page_count,
                "duration_secs": doc.duration_secs,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
            },
            "chunk": {
                "id": chunk_id,
                "text": vec_data["text"],
                "page_number": vec_data["metadata"].get("page_number"),
                "chunk_index": vec_data["metadata"].get("chunk_index", 0),
                "start_timestamp": vec_data["metadata"].get("start_timestamp"),
                "end_timestamp": vec_data["metadata"].get("end_timestamp"),
                "source_type": vec_data["metadata"].get("source_type", "text"),
            },
            "surrounding_chunks": [],
        }

    # 从 ChromaDB 获取相邻分块（上下文）
    neighbors = vector_store.get_neighboring_chunks(
        document_id=doc_id,
        chunk_index=chunk_record.chunk_index,
        count=1,
    )
    surrounding = [
        {
            "text": n["text"][:500],
            "chunk_index": n["metadata"].get("chunk_index", 0),
            "page_number": n["metadata"].get("page_number"),
        }
        for n in neighbors
    ]

    return {
        "document": {
            "id": doc.id,
            "filename": doc.filename,
            "original_name": doc.original_name,
            "file_type": doc.file_type,
            "page_count": doc.page_count,
            "duration_secs": doc.duration_secs,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        },
        "chunk": {
            "id": chunk_record.id,
            "text": chunk_record.text,
            "page_number": chunk_record.page_number,
            "chunk_index": chunk_record.chunk_index,
            "start_timestamp": chunk_record.start_timestamp,
            "end_timestamp": chunk_record.end_timestamp,
            "source_type": "video" if chunk_record.start_timestamp is not None else "text",
        },
        "surrounding_chunks": surrounding,
    }
