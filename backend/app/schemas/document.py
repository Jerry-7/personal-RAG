# Personal RAG - Document 数据模型
"""
文档相关 Pydantic 模型

定义文档上传响应、文档列表、分块信息等 API 数据模型。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DocumentUploadResponse(BaseModel):
    """文件上传成功后返回的响应模型。"""
    id: str = Field(..., description="文档唯一 ID")
    filename: str = Field(..., description="存储的文件名")
    original_name: str = Field(..., description="用户上传的原始文件名")
    file_type: str = Field(..., description="文件类型 (pdf, docx, txt, mp4 等)")
    status: str = Field(..., description="处理状态 (uploaded/processing/indexed/error)")
    created_at: datetime = Field(..., description="上传时间")


class DocumentItem(BaseModel):
    """文档列表中每一项的数据模型。"""
    id: str
    filename: str
    original_name: str
    file_type: str
    file_size_bytes: int
    status: str
    chunk_count: int = 0
    page_count: Optional[int] = None
    duration_secs: Optional[float] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """文档列表接口响应模型。"""
    documents: list[DocumentItem] = Field(default_factory=list)
    total: int = 0


class ChunkItem(BaseModel):
    """分块数据模型。"""
    id: str
    document_id: str
    chunk_index: int
    text: str
    page_number: Optional[int] = None
    start_timestamp: Optional[float] = None
    end_timestamp: Optional[float] = None
    token_count: Optional[int] = None

    class Config:
        from_attributes = True


class DeleteDocumentResponse(BaseModel):
    """文档删除响应。"""
    document_id: str = Field(..., description="被删除的文档 ID")
    chunks_deleted: int = Field(..., description="删除的分块数量")
    message: str = "Document deleted successfully"
