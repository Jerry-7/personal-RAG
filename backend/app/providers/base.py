# Personal RAG - LLM/Embedding Provider 抽象基类
"""
Provider 抽象基类模块

定义 LLMProvider 和 EmbeddingProvider 两个抽象基类。
所有具体的 provider（Ollama, OpenAI, Anthropic）都继承并实现这些接口，
使得上层服务无需关心底层调用细节。
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LLMResponse:
    """
    LLM 返回的完整响应。

    Attributes:
        content: 生成的文本内容
        citations: 引用列表，每项包含 index, doc_id, chunk_id, snippet
        token_count: 消耗的 token 数（估算）
        model: 使用的模型名称
    """
    content: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    token_count: int = 0
    model: str = ""


class LLMProvider(ABC):
    """
    LLM Provider 抽象基类。

    定义了 LLM 聊天生成的标准接口。所有 LLM provider
    (Ollama, OpenAI, Anthropic) 都需要实现此接口。

    支持普通生成和流式生成两种模式。
    """

    @abstractmethod
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
            messages: 对话消息列表 [{"role": "user"/"assistant"/"system", "content": "..."}]
            model: 模型名称，None 则使用默认模型
            temperature: 生成温度 (0.0-2.0)
            max_tokens: 最大生成 token 数

        Returns:
            LLMResponse 包含完整生成内容
        """
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """
        流式聊天生成。

        以异步生成器方式逐 token 返回生成内容。

        Args:
            messages: 对话消息列表
            model: 模型名称，None 则使用默认模型
            temperature: 生成温度 (0.0-2.0)
            max_tokens: 最大生成 token 数

        Yields:
            str: 每次 yield 一个文本片段（可能是单个 token 或短词组）
        """
        ...


class EmbeddingProvider(ABC):
    """
    Embedding Provider 抽象基类。

    定义了文本向量化的标准接口。所有 embedding provider
    (Ollama, OpenAI) 都需要实现此接口。
    """

    @abstractmethod
    async def embed(
        self,
        texts: list[str],
        model: Optional[str] = None,
    ) -> list[list[float]]:
        """
        将文本列表转换为 embedding 向量列表。

        Args:
            texts: 待转换的文本列表
            model: 模型名称，None 则使用默认模型

        Returns:
            embedding 向量列表，每个向量为 float 列表
            (nomic-embed-text: 768维, text-embedding-3-small: 1536维)
        """
        ...
