# Personal RAG - 设置管理 API
"""
设置管理 API 模块

提供读取和更新应用配置的接口。
设置存储在 SQLite settings 表和 .env 文件中。
"""

import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.db.database import get_db
from app.db.models import Setting

router = APIRouter()


@router.get("/settings")
async def get_settings(db: Session = Depends(get_db)):
    """
    获取当前应用的完整设置。

    从 SQLite settings 表读取持久化配置，未配置项使用默认值。

    Returns:
        AppSettingsResponse: 当前配置
    """
    # 从数据库读取持久化设置，合并默认值
    db_settings = {}
    for s in db.query(Setting).all():
        db_settings[s.key] = json.loads(s.value_json)

    return {
        "llm_provider": db_settings.get("llm_provider", app_settings.llm_provider),
        "embedding_provider": db_settings.get("embedding_provider", app_settings.embedding_provider),
        "ollama": {
            "base_url": db_settings.get("ollama_base_url", app_settings.ollama_base_url),
            "llm_model": db_settings.get("ollama_llm_model", app_settings.ollama_llm_model),
            "embedding_model": db_settings.get("ollama_embedding_model", app_settings.ollama_embedding_model),
        },
        "openai": {
            "api_key": None,  # 不返回 API key
            "llm_model": db_settings.get("openai_llm_model", app_settings.openai_llm_model),
            "embedding_model": db_settings.get("openai_embedding_model", app_settings.openai_embedding_model),
        },
        "anthropic": {
            "api_key": None,  # 不返回 API key
            "llm_model": db_settings.get("anthropic_llm_model", app_settings.anthropic_llm_model),
        },
        "rag": {
            "chunk_size": int(db_settings.get("chunk_size", app_settings.chunk_size)),
            "chunk_overlap": int(db_settings.get("chunk_overlap", app_settings.chunk_overlap)),
            "retrieval_top_k": int(db_settings.get("retrieval_top_k", app_settings.retrieval_top_k)),
            "final_top_k": int(db_settings.get("final_top_k", app_settings.final_top_k)),
        },
    }


@router.put("/settings")
async def update_settings(updates: dict, db: Session = Depends(get_db)):
    """
    更新应用设置。

    支持部分更新，只更新提供的字段。

    Args:
        updates: 要更新的设置键值对字典

    Returns:
        更新确认
    """
    for key, value in updates.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                composite_key = f"{key}_{sub_key}"
                _upsert_setting(db, composite_key, sub_value)
        else:
            _upsert_setting(db, key, value)

    db.commit()

    # 刷新全局 settings 对象中的部分值
    if "llm_provider" in updates:
        app_settings.llm_provider = updates["llm_provider"]
    if "embedding_provider" in updates:
        app_settings.embedding_provider = updates["embedding_provider"]

    return {"status": "updated"}


def _upsert_setting(db: Session, key: str, value) -> None:
    """插入或更新单条设置。API key 类型需要特殊处理。"""
    s = db.query(Setting).filter(Setting.key == key).first()
    # 特殊处理：SecretStr → 字符串
    if hasattr(value, "get_secret_value"):
        json_value = json.dumps(value.get_secret_value())
    elif value is None:
        return  # 跳过 None 值
    else:
        json_value = json.dumps(value)

    if s:
        s.value_json = json_value
    else:
        db.add(Setting(key=key, value_json=json_value))
