# Personal RAG - 路由聚合器
"""
API 路由聚合模块

将所有子路由注册到统一的 FastAPI APIRouter 上，
方便在 main.py 中一次性挂载。
"""

from fastapi import APIRouter

from app.api import chat, documents, models, settings, sources

api_router = APIRouter(prefix="/api")

# 注册各模块路由
api_router.include_router(documents.router, tags=["Documents"])
api_router.include_router(chat.router, tags=["Chat"])
api_router.include_router(sources.router, tags=["Sources"])
api_router.include_router(models.router, tags=["Models"])
api_router.include_router(settings.router, tags=["Settings"])
