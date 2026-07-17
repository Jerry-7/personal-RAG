# Personal RAG - FastAPI 应用入口
"""
FastAPI 应用主模块

创建和配置 FastAPI 应用实例，注册路由、中间件、
启动事件等。应用使用 lifespan 机制管理生命周期。
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.config import settings
from app.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理。

    启动时：创建数据目录、初始化数据库。
    关闭时：清理资源（如有需要）。
    """
    # ── 启动 ──────────────────────────────────────────────────
    # 确保数据目录存在
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    settings.transcript_dir.mkdir(parents=True, exist_ok=True)

    # 初始化数据库表
    init_db()

    # 注册内置文档解析器
    from app.services.parser.pdf import PDFParser
    from app.services.parser.docx import DocxParser
    from app.services.parser.text import TextParser
    from app.services.parser.registry import parser_registry

    parser_registry.register(PDFParser())
    parser_registry.register(DocxParser())
    parser_registry.register(TextParser())

    # 注册图片 OCR 解析器（可选依赖 Tesseract/PaddleOCR）
    try:
        from app.services.parser.image import ImageParser
        parser_registry.register(ImageParser())
        print(f" 图片 OCR 解析器已注册 (支持: {ImageParser._SUPPORTED_EXTENSIONS})")
    except ImportError as e:
        print(f" 图片 OCR 解析器不可用 (缺少依赖): {e}")

    # 注册音视频解析器（可选依赖 faster-whisper + ffmpeg）
    try:
        from app.services.parser.media import MediaParser
        parser_registry.register(MediaParser())
        print(f" 音视频解析器已注册 (支持: {MediaParser._SUPPORTED_EXTENSIONS})")
    except ImportError as e:
        print(f" 音视频解析器不可用 (缺少依赖): {e}")

    print(f" 全部已注册解析器: {parser_registry.supported_extensions}")

    yield

    # ── 关闭 ──────────────────────────────────────────────────
    from app.services.task_manager import task_manager
    await task_manager.shutdown(timeout=settings.indexing_shutdown_timeout_secs)


# ── 创建 FastAPI 应用 ──────────────────────────────────────────

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="个人 RAG 系统 - 支持多格式文件上传、本地 Ollama 检索增强生成、引用来源追踪",
    lifespan=lifespan,
)

# ── CORS 中间件（允许前端开发服务器跨域）───────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 注册 API 路由 ──────────────────────────────────────────────

app.include_router(api_router)

# ── 静态文件服务（上传的文件）───────────────────────────────────

uploads_path = str(settings.upload_dir)
if Path(uploads_path).exists():
    app.mount("/files", StaticFiles(directory=uploads_path), name="files")


# ── 健康检查端点 ────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
async def health_check():
    """
    健康检查端点。

    Returns:
        包含状态和版本信息的字典
    """
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
    }
