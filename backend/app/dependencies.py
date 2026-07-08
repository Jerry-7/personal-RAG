# Personal RAG - FastAPI 依赖注入
"""
依赖注入模块

提供 FastAPI 依赖注入函数，包括数据库会话、
向量存储、以及各种服务实例的获取。
"""

from app.db.database import get_db
from app.db.vector_store import VectorStore, vector_store
from app.services.embedder import EmbeddingService, embedding_service

# 复导出
__all__ = [
    "get_db",
    "get_vector_store",
    "get_embedding_service",
]


def get_vector_store() -> VectorStore:
    """获取向量存储单例实例。"""
    return vector_store


def get_embedding_service() -> EmbeddingService:
    """获取 Embedding 服务单例实例。"""
    return embedding_service
