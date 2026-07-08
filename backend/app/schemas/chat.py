# Personal RAG - Chat/Citation 数据模型
"""
聊天相关 Pydantic 模型

定义聊天请求、SSE 流事件、引用等 API 数据模型。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ChatQueryRequest(BaseModel):
    """聊天查询请求模型。"""
    question: str = Field(..., description="用户问题", min_length=1, max_length=10000)
    conversation_id: Optional[str] = Field(None, description="已有对话 ID，不提供则创建新对话")
    top_k: int = Field(4, description="检索的分块数量", ge=1, le=20)


class CitationData(BaseModel):
    """单条引用元数据。"""
    index: int = Field(..., description="引用编号 [1], [2]...")
    document_id: str = Field(..., description="来源文档 ID")
    chunk_id: str = Field(..., description="来源分块 ID")
    snippet: str = Field(..., description="来源文本摘要（前 200 字符）")
    filename: str = Field(..., description="来源文件名")
    page_number: Optional[int] = Field(None, description="PDF 页码")
    start_timestamp: Optional[float] = Field(None, description="视频开始时间(秒)")
    end_timestamp: Optional[float] = Field(None, description="视频结束时间(秒)")
    source_type: str = Field("text", description="来源类型: text | video | audio")


class ChatHistoryItem(BaseModel):
    """对话历史列表中的每一项。"""
    id: str
    title: Optional[str]
    model_provider: str
    model_name: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    class Config:
        from_attributes = True


class ChatHistoryResponse(BaseModel):
    """对话历史列表响应。"""
    conversations: list[ChatHistoryItem] = Field(default_factory=list)
    total: int = 0


class MessageItem(BaseModel):
    """单条消息。"""
    id: str
    role: str
    content: str
    citations: list[CitationData] = Field(default_factory=list)
    token_count: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationDetail(BaseModel):
    """对话详情（含所有消息）。"""
    id: str
    title: Optional[str]
    model_provider: str
    model_name: str
    messages: list[MessageItem] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
