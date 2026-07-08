# Personal RAG - Settings 配置数据模型
"""
设置相关 Pydantic 模型

定义 Provider 配置、模型选择、API key 管理等 API 数据模型。
"""

from typing import Optional

from pydantic import BaseModel, Field, SecretStr


class OllamaConfig(BaseModel):
    """Ollama provider 配置。"""
    base_url: str = Field("http://localhost:11434", description="Ollama 服务地址")
    llm_model: str = Field("qwen2.5:14b", description="默认 LLM 模型")
    embedding_model: str = Field("nomic-embed-text", description="默认 Embedding 模型")


class OpenAIConfig(BaseModel):
    """OpenAI provider 配置。"""
    api_key: Optional[SecretStr] = Field(None, description="OpenAI API Key")
    llm_model: str = Field("gpt-4o-mini", description="默认 LLM 模型")
    embedding_model: str = Field("text-embedding-3-small", description="默认 Embedding 模型")


class AnthropicConfig(BaseModel):
    """Anthropic provider 配置。"""
    api_key: Optional[SecretStr] = Field(None, description="Anthropic API Key")
    llm_model: str = Field("claude-sonnet-4-20250514", description="默认 LLM 模型")


class RAGConfig(BaseModel):
    """RAG 参数配置。"""
    chunk_size: int = Field(1000, description="分块大小 (字符数)", ge=100, le=10000)
    chunk_overlap: int = Field(200, description="分块重叠 (字符数)", ge=0, le=5000)
    retrieval_top_k: int = Field(8, description="初次检索分块数", ge=1, le=50)
    final_top_k: int = Field(4, description="最终使用的分块数", ge=1, le=20)


class AppSettingsResponse(BaseModel):
    """应用完整设置响应。"""
    llm_provider: str = Field("ollama", description="当前 LLM provider")
    embedding_provider: str = Field("ollama", description="当前 Embedding provider")
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)


class AppSettingsUpdate(BaseModel):
    """部分更新设置的请求模型（所有字段可选）。"""
    llm_provider: Optional[str] = None
    embedding_provider: Optional[str] = None
    ollama: Optional[OllamaConfig] = None
    openai: Optional[OpenAIConfig] = None
    anthropic: Optional[AnthropicConfig] = None
    rag: Optional[RAGConfig] = None


class AvailableModelsResponse(BaseModel):
    """可用的模型列表响应。"""
    ollama_llm_models: list[str] = Field(default_factory=list, description="Ollama 已安装的 LLM 模型")
    ollama_embed_models: list[str] = Field(default_factory=list, description="Ollama 已安装的 Embedding 模型")
    openai_llm_models: list[str] = Field(default_factory=list, description="OpenAI 可用 LLM 模型")
    openai_embed_models: list[str] = Field(default_factory=list, description="OpenAI 可用 Embedding 模型")
    anthropic_models: list[str] = Field(default_factory=list, description="Anthropic 可用模型")
