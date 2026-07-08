# Personal RAG - Embedding 服务
"""
Embedding 服务模块

封装文本向量化操作，支持批量处理和 provider 切换。
提供 Ollama（本地）和 OpenAI（云端）两种 embedding 后端。
"""

import asyncio
from typing import Optional

from app.config import settings
from app.providers.base import EmbeddingProvider
from app.providers.ollama import OllamaEmbeddingProvider


class EmbeddingService:
    """
    Embedding 服务。

    管理 embedding provider 的创建和缓存，
    提供批量嵌入功能以优化性能。

    Attributes:
        provider_name: 当前使用的 provider ("ollama" | "openai")
        batch_size: 嵌入时的批处理大小
    """

    def __init__(
        self,
        provider_name: Optional[str] = None,
        batch_size: int = 32,
    ) -> None:
        """
        初始化 Embedding 服务。

        Args:
            provider_name: Provider 名称，默认从配置读取
            batch_size: 每批处理的文本数量
        """
        self.provider_name = provider_name or settings.embedding_provider
        self.batch_size = batch_size
        self._provider: Optional[EmbeddingProvider] = None

    async def _get_provider(self) -> EmbeddingProvider:
        """
        获取或创建 Embedding provider 实例（延迟初始化）。

        根据 provider_name 动态选择后端。

        Returns:
            EmbeddingProvider 实例

        Raises:
            ValueError: 不支持的 provider 类型
        """
        if self._provider is not None:
            return self._provider

        if self.provider_name == "ollama":
            self._provider = OllamaEmbeddingProvider()
        elif self.provider_name == "openai":
            # 延迟导入，避免未安装 openai 时的错误
            from app.providers.openai_provider import OpenAIEmbeddingProvider
            self._provider = OpenAIEmbeddingProvider()
        else:
            raise ValueError(f"不支持的 Embedding provider: {self.provider_name}")

        return self._provider

    async def embed_single(self, text: str) -> list[float]:
        """
        将单条文本转换为 embedding 向量。

        Args:
            text: 要嵌入的文本

        Returns:
            embedding 向量列表
        """
        provider = await self._get_provider()
        results = await provider.embed([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        批量将文本转换为 embedding 向量。

        内部按 batch_size 分批处理，避免 Ollama 单次请求过载。

        Args:
            texts: 要嵌入的文本列表

        Returns:
            embedding 向量列表，与输入顺序一致
        """
        provider = await self._get_provider()
        all_embeddings = []

        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            embeddings = await provider.embed(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings


# 默认单例
embedding_service = EmbeddingService()
