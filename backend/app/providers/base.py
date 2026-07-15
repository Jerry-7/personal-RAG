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


@dataclass
class ToolCall:
    """
    LLM 返回的工具调用请求。

    Attributes:
        id: 工具调用唯一标识（用于匹配结果）
        name: 工具名称
        arguments: 工具参数，已解析为 dict
    """
    id: str = ""
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResponse:
    """
    Agent 模式下 LLM 的单轮响应。

    可能是纯文本（最终回答或思考过程），也可能是工具调用请求。
    两者不会同时非空：有 tool_calls 时 content 为空，反之亦然。

    Attributes:
        content: 纯文本输出（最终回答或思考）
        tool_calls: 工具调用列表（LLM 决定调用工具时）
    """
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


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

    async def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AgentResponse:
        """
        支持 tool calling 的聊天生成（Agent 模式）。

        默认实现：尝试调用 chat() 并解析 tool_calls。
        子类可覆盖以使用原生 tool calling API。

        Args:
            messages: 对话消息列表
            tools: OpenAI 格式的工具定义列表
            model: 模型名称，None 则使用默认模型
            temperature: 生成温度
            max_tokens: 最大生成 token 数

        Returns:
            AgentResponse: 包含文本内容或工具调用列表
        """
        # 默认实现：构建带有 tool 指令的 system prompt
        # 子类（Ollama/OpenAI/Anthropic）应覆盖此方法使用原生 tool calling
        tool_descriptions = "\n".join(
            f"- {t['function']['name']}: {t['function']['description']}"
            for t in tools
        )
        system_msg = (
            "You have access to the following tools:\n"
            f"{tool_descriptions}\n\n"
            "To use a tool, respond with JSON in this exact format:\n"
            '{"tool_calls": [{"name": "tool_name", "arguments": {...}}]}\n\n'
            "After receiving tool results, continue answering naturally."
        )
        messages = [{"role": "system", "content": system_msg}] + messages

        response = await self.chat(messages, model, temperature, max_tokens)
        content = response.content

        # 尝试解析 JSON tool_calls
        import json as _json
        try:
            # 提取可能的 JSON 块
            import re as _re
            match = _re.search(r'\{[^{}]*"tool_calls"[^{}]*\}', content, _re.DOTALL)
            if match:
                data = _json.loads(match.group(0))
                calls = data.get("tool_calls", [])
                if calls:
                    return AgentResponse(tool_calls=[
                        ToolCall(
                            id=c.get("id", f"call_{i}"),
                            name=c["name"],
                            arguments=c.get("arguments", {}),
                        )
                        for i, c in enumerate(calls)
                    ])
        except (_json.JSONDecodeError, KeyError, TypeError):
            pass

        return AgentResponse(content=content)


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
