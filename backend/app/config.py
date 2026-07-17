# Personal RAG - Backend Configuration
"""
应用配置模块

使用 pydantic-settings 管理所有配置项，支持 .env 文件和
环境变量覆盖。包含 Ollama、OpenAI、Anthropic 及本地路径配置。
"""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用全局配置，从 .env 文件和环境变量加载。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 应用基础配置 ──────────────────────────────────────────
    app_name: str = "Personal RAG"
    app_version: str = "0.1.0"
    debug: bool = True

    # ── 数据存储路径 ──────────────────────────────────────────
    data_dir: Path = Path(__file__).parent.parent / "data"
    upload_dir: Path = Path(__file__).parent.parent / "data" / "uploads"
    chroma_dir: Path = Path(__file__).parent.parent / "data" / "chroma"
    transcript_dir: Path = Path(__file__).parent.parent / "data" / "transcripts"

    # ── Ollama 配置 ───────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_embedding_model: str = "bge-m3"
    ollama_llm_model: str = "qwen3.5-9b"

    # ── OpenAI 配置 (可选) ────────────────────────────────────
    openai_api_key: Optional[str] = None
    openai_llm_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    # ── Anthropic 配置 (可选) ─────────────────────────────────
    anthropic_api_key: Optional[str] = None
    anthropic_llm_model: str = "claude-sonnet-4-20250514"

    # ── RAG 参数 ──────────────────────────────────────────────
    chunk_size: int = 1000
    chunk_overlap: int = 200
    retrieval_top_k: int = 8
    final_top_k: int = 4
    embedding_batch_size: int = 32

    # ── 后台任务配置 ──────────────────────────────────────────
    max_concurrent_indexing_tasks: int = 10
    indexing_shutdown_timeout_secs: int = 30

    # ── 默认 Provider 选择 ────────────────────────────────────
    llm_provider: str = "ollama"          # "ollama" | "openai" | "anthropic"
    embedding_provider: str = "ollama"    # "ollama" | "openai"

    # ── 文件上传限制 ──────────────────────────────────────────
    max_upload_size_mb: int = 500
    allowed_extensions: list[str] = [
        "pdf", "docx", "doc", "txt", "md", "csv",
        "mp4", "mp3", "avi", "mkv", "mov", "wav",
        "jpg", "jpeg", "png", "bmp", "tiff",
    ]


# 单例实例
settings = Settings()
