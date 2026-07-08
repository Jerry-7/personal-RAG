# Personal RAG - Source/Citation 查询数据模型
"""
来源查询相关 Pydantic 模型

定义引用源内容查询的请求和响应模型，
支持文本来源（高亮显示）和视频来源（时间戳跳转）。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SourceDocumentInfo(BaseModel):
    """来源文档的基本信息。"""
    id: str
    filename: str
    original_name: str
    file_type: str
    page_count: Optional[int] = None
    duration_secs: Optional[float] = None
    created_at: Optional[datetime] = None


class SourceChunkInfo(BaseModel):
    """来源分块的详细信息。"""
    id: str
    text: str = Field(..., description="分块完整文本")
    page_number: Optional[int] = None
    chunk_index: int
    start_timestamp: Optional[float] = None
    end_timestamp: Optional[float] = None
    source_type: str = Field("text", description="来源类型: text | video | audio")


class NeighborChunk(BaseModel):
    """相邻分块（用于上下文显示）。"""
    text: str
    chunk_index: int
    page_number: Optional[int] = None


class SourceResponse(BaseModel):
    """
    引用来源查询的完整响应。

    包含文档信息、目标分块、以及前后相邻分块（上下文）。
    前端根据 source_type 决定渲染 TextCitation 还是 VideoCitation。
    """
    document: SourceDocumentInfo
    chunk: SourceChunkInfo
    surrounding_chunks: list[NeighborChunk] = Field(
        default_factory=list,
        description="前一个和后一个相邻分块，用于提供上下文"
    )
