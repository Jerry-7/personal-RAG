# Personal RAG - 可用模型列表 API
"""
模型查询 API 模块

返回 Ollama 已安装的模型列表和第三方可用模型。
用于前端 SettingsModal 中的模型选择下拉框。
"""

from fastapi import APIRouter

from app.config import settings

router = APIRouter()


@router.get("/models")
async def list_available_models():
    """
    列出所有可用的 LLM 和 Embedding 模型。

    包括本地 Ollama 已安装的模型，以及第三方 provider 的常用模型列表。

    Returns:
        AvailableModelsResponse: 按 provider 分类的模型列表
    """
    # Ollama 模型列表
    ollama_llm_models = []
    ollama_embed_models = []
    try:
        from ollama import Client
        client = Client(host=settings.ollama_base_url)
        models = client.list()
        for model in models.get("models", []):
            name = model.get("name", "")
            if "embed" in name.lower() or name in ("nomic-embed-text", "mxbai-embed-large", "bge-m3"):
                ollama_embed_models.append(name)
            elif name not in ("", ):
                ollama_llm_models.append(name)
    except Exception:
        # Ollama 不可用时返回空列表
        pass

    return {
        "ollama_llm_models": ollama_llm_models,
        "ollama_embed_models": ollama_embed_models,
        "openai_llm_models": [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-3.5-turbo",
        ],
        "openai_embed_models": [
            "text-embedding-3-small",
            "text-embedding-3-large",
            "text-embedding-ada-002",
        ],
        "anthropic_models": [
            "claude-sonnet-4-20250514",
            "claude-opus-4-20250514",
            "claude-haiku-3.5",
        ],
    }
