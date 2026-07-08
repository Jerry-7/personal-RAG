# Personal RAG - OpenAI Provider 实现
"""
OpenAI Provider 模块

通过 openai 官方 SDK 实现 LLMProvider 和 EmbeddingProvider 接口。
支持 GPT-4o、GPT-4o-mini 等模型。
"""

from collections.abc import AsyncGenerator
from typing import Any, Optional

from openai import AsyncOpenAI

from app.config import settings
from app.providers.base import (
    EmbeddingProvider,
    LLMProvider,
    LLMResponse,
)


class OpenAILLMProvider(LLMProvider):
    """
    基于 OpenAI API 的 LLM Provider。

    使用 AsyncOpenAI 客户端进行云端 LLM 调用。
    需要配置 OPENAI_API_KEY 环境变量或通过设置 API 配置。
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        """
        初始化 OpenAI 客户端。

        Args:
            api_key: OpenAI API Key，默认从配置读取

        Raises:
            ValueError: API Key 未配置
        """
        key = api_key or settings.openai_api_key
        if not key:
            raise ValueError("OpenAI API Key 未配置，请在设置中填入或设置 OPENAI_API_KEY 环境变量")
        self._client = AsyncOpenAI(api_key=key)
        self._default_model = settings.openai_llm_model

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """非流式聊天生成。"""
        response = await self._client.chat.completions.create(
            model=model or self._default_model,
            messages=messages,  # type: ignore
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            token_count=response.usage.total_tokens if response.usage else 0,
            model=response.model,
        )

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """流式聊天生成，逐 token yield。"""
        stream = await self._client.chat.completions.create(
            model=model or self._default_model,
            messages=messages,  # type: ignore
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    基于 OpenAI API 的 Embedding Provider。

    使用 text-embedding-3-small 模型生成 1536 维向量。
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        """
        初始化 OpenAI Embedding 客户端。

        Args:
            api_key: OpenAI API Key

        Raises:
            ValueError: API Key 未配置
        """
        key = api_key or settings.openai_api_key
        if not key:
            raise ValueError("OpenAI API Key 未配置")
        self._client = AsyncOpenAI(api_key=key)
        self._default_model = settings.openai_embedding_model

    async def embed(
        self,
        texts: list[str],
        model: Optional[str] = None,
    ) -> list[list[float]]:
        """
        批量生成文本 embedding 向量。

        OpenAI API 支持单次请求批量处理，效率高于逐个请求。

        Args:
            texts: 待嵌入的文本列表
            model: 模型名称

        Returns:
            embedding 向量列表 (1536 维)
        """
        response = await self._client.embeddings.create(
            model=model or self._default_model,
            input=texts,
        )
        # 按输入顺序返回
        sorted_data = sorted(response.data, key=lambda x: x.index)
        return [d.embedding for d in sorted_data]
