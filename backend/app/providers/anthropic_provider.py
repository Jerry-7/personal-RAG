# Personal RAG - Anthropic Provider 实现
"""
Anthropic Provider 模块

通过 anthropic 官方 SDK 实现 LLMProvider 接口。
支持 Claude Sonnet/Opus/Haiku 系列模型。
Anthropic 不提供独立的 Embedding API，因此不实现 EmbeddingProvider。
"""

from collections.abc import AsyncGenerator
from typing import Any, Optional

from anthropic import AsyncAnthropic

from app.config import settings
from app.providers.base import (
    LLMProvider,
    LLMResponse,
)


class AnthropicLLMProvider(LLMProvider):
    """
    基于 Anthropic API 的 LLM Provider。

    使用 AsyncAnthropic 客户端进行云端 LLM 调用。
    需要配置 ANTHROPIC_API_KEY 环境变量。
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        """
        初始化 Anthropic 客户端。

        Args:
            api_key: Anthropic API Key

        Raises:
            ValueError: API Key 未配置
        """
        key = api_key or settings.anthropic_api_key
        if not key:
            raise ValueError("Anthropic API Key 未配置，请在设置中填入或设置 ANTHROPIC_API_KEY 环境变量")
        self._client = AsyncAnthropic(api_key=key)
        self._default_model = settings.anthropic_llm_model

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """非流式聊天生成。"""
        # 提取 system 消息（Anthropic 单独处理）
        system_msg = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg += msg["content"] + "\n"
            else:
                chat_messages.append(msg)

        response = await self._client.messages.create(
            model=model or self._default_model,
            system=system_msg.strip() or None,
            messages=chat_messages,  # type: ignore
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text
        return LLMResponse(
            content=text,
            token_count=response.usage.input_tokens + response.usage.output_tokens,
            model=response.model,
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

        Anthropic 通过 Messages API 的 streaming 模式实现流式输出。

        Args:
            messages: 对话消息列表
            model: 模型名称
            temperature: 生成温度
            max_tokens: 最大 token 数

        Yields:
            str: 每次 yield 一个文本片段
        """
        # 提取 system 消息
        system_msg = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg += msg["content"] + "\n"
            else:
                chat_messages.append(msg)

        async with self._client.messages.stream(
            model=model or self._default_model,
            system=system_msg.strip() or None,
            messages=chat_messages,  # type: ignore
            max_tokens=max_tokens,
            temperature=temperature,
        ) as stream:
            async for text in stream.text_stream:
                yield text
