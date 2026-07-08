# Personal RAG - Ollama Provider 实现
"""
Ollama Provider 模块

通过 ollama-python 官方库实现 LLMProvider 和 EmbeddingProvider 接口。
支持本地 GPU 加速推理，无需 API key。
"""

from collections.abc import AsyncGenerator
from typing import Any, Optional

import httpx
from ollama import AsyncClient

from app.config import settings
from app.providers.base import (
    EmbeddingProvider,
    LLMProvider,
    LLMResponse,
)


class OllamaLLMProvider(LLMProvider):
    """
    基于 Ollama 的 LLM Provider。

    使用 ollama-python AsyncClient 进行本地 LLM 调用。
    支持所有 Ollama 管理的模型（llama3.2, qwen2.5 等）。
    GPU 加速由 Ollama 服务端自动管理。
    """

    def __init__(self, base_url: Optional[str] = None) -> None:
        """
        初始化 Ollama 客户端。

        Args:
            base_url: Ollama 服务地址，默认从配置读取
        """
        self._client = AsyncClient(host=base_url or settings.ollama_base_url)
        self._default_model = settings.ollama_llm_model

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """
        非流式聊天生成。

        Args:
            messages: 对话消息列表
            model: 模型名称，默认 qwen2.5:14b
            temperature: 生成温度
            max_tokens: 最大 token 数

        Returns:
            LLMResponse 包含生成内容和元数据
        """
        response = await self._client.chat(
            model=model or self._default_model,
            messages=messages,
            options={
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        )
        return LLMResponse(
            content=response["message"]["content"],
            token_count=response.get("eval_count", 0),
            model=response.get("model", model or self._default_model),
        )

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """
        流式聊天生成。

        逐 token yield LLM 输出，适合 SSE 推送给前端。

        Args:
            messages: 对话消息列表
            model: 模型名称
            temperature: 生成温度
            max_tokens: 最大 token 数

        Yields:
            str: 每次 yield 一个文本片段
        """
        stream = await self._client.chat(
            model=model or self._default_model,
            messages=messages,
            stream=True,
            options={
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        )
        async for chunk in stream:
            content = chunk["message"]["content"]
            if content:
                yield content


class OllamaEmbeddingProvider(EmbeddingProvider):
    """
    基于 Ollama 的 Embedding Provider。

    使用本地 nomic-embed-text 模型生成 768 维文本向量。
    """

    def __init__(self, base_url: Optional[str] = None) -> None:
        """
        初始化 Ollama Embedding 客户端。

        Args:
            base_url: Ollama 服务地址，默认从配置读取
        """
        self._client = AsyncClient(host=base_url or settings.ollama_base_url)
        self._default_model = settings.ollama_embedding_model

    async def embed(
        self,
        texts: list[str],
        model: Optional[str] = None,
    ) -> list[list[float]]:
        """
        批量生成文本 embedding 向量。

        当前 Ollama embed API 不支持批量，因此逐个请求。
        对于大批量处理，建议上层控制并发数。

        Args:
            texts: 待嵌入的文本列表
            model: 模型名称，默认 nomic-embed-text

        Returns:
            embedding 向量列表，每项为 768 维 float 列表
        """
        embeddings = []
        for text in texts:
            response = await self._client.embed(
                model=model or self._default_model,
                input=text,
            )
            embeddings.append(response["embeddings"][0])
        return embeddings
