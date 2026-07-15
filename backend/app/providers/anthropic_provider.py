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
    AgentResponse,
    LLMProvider,
    LLMResponse,
    ToolCall,
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

    async def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AgentResponse:
        """
        支持 tool calling 的聊天生成。

        使用 Anthropic 原生 tool_use API。

        Args:
            messages: 对话消息列表
            tools: OpenAI 格式的工具定义列表
            model: 模型名称
            temperature: 生成温度
            max_tokens: 最大 token 数

        Returns:
            AgentResponse: 包含文本内容或工具调用列表
        """
        # 提取 system 消息（Anthropic 单独处理）
        system_msg = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg += msg["content"] + "\n"
            else:
                chat_messages.append(msg)

        # 转换 tools 格式: OpenAI → Anthropic
        anthropic_tools = []
        for t in tools:
            func = t.get("function", t)
            anthropic_tools.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })

        response = await self._client.messages.create(
            model=model or self._default_model,
            system=system_msg.strip() or None,
            messages=chat_messages,  # type: ignore
            tools=anthropic_tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        tool_calls = []
        text_parts = []
        for block in response.content:
            if block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))
            elif block.type == "text":
                text_parts.append(block.text)

        if tool_calls:
            return AgentResponse(tool_calls=tool_calls)
        return AgentResponse(content="".join(text_parts))
