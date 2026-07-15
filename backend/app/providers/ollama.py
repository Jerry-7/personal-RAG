# Personal RAG - Ollama Provider 实现
"""
Ollama Provider 模块

通过 ollama-python 官方库实现 LLMProvider 和 EmbeddingProvider 接口。
支持本地 GPU 加速推理，无需 API key。
"""

from collections.abc import AsyncGenerator
from typing import Any, Optional

import json as _json
import logging

import httpx
from ollama import AsyncClient

from app.config import settings
from app.providers.base import (
    AgentResponse,
    EmbeddingProvider,
    LLMProvider,
    LLMResponse,
    ToolCall,
)

logger = logging.getLogger(__name__)


def _parse_arguments_fallback(raw: str) -> dict[str, Any]:
    """
    兜底解析工具参数。

    当模型输出的 arguments JSON 不标准时，
    尝试用正则提取 key-value 对。

    Args:
        raw: 原始参数字符串

    Returns:
        解析后的参数字典，解析失败返回空 dict
    """
    import re
    args = {}
    # 尝试匹配 "key": "value" 或 "key": value 模式
    for match in re.finditer(r'"(\w+)"\s*:\s*("[^"]*"|\d+|true|false|null)', raw):
        key = match.group(1)
        val = match.group(2)
        if val.startswith('"'):
            args[key] = val.strip('"')
        elif val == "true":
            args[key] = True
        elif val == "false":
            args[key] = False
        elif val == "null":
            args[key] = None
        else:
            try:
                args[key] = int(val)
            except ValueError:
                args[key] = val
    return args


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

        使用 Ollama 原生 tools 参数（OpenAI 兼容格式）。
        qwen2.5 等模型支持此功能。如果模型返回格式不标准，
        会尝试正则兜底解析。

        Args:
            messages: 对话消息列表
            tools: OpenAI 格式的工具定义列表
            model: 模型名称
            temperature: 生成温度
            max_tokens: 最大 token 数

        Returns:
            AgentResponse: 包含文本内容或工具调用列表
        """
        try:
            response = await self._client.chat(
                model=model or self._default_model,
                messages=messages,
                tools=tools,
                options={
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            )
        except Exception as e:
            # 模型或 Ollama 版本不支持 tools 参数时回退
            logger.warning("Ollama tool calling failed, falling back: %s", e)
            return await super().chat_with_tools(messages, tools, model, temperature, max_tokens)

        msg = response.get("message", {})
        raw_tool_calls = msg.get("tool_calls", [])

        if raw_tool_calls:
            parsed = []
            for tc in raw_tool_calls:
                # Ollama 返回格式: {"function": {"name": "...", "arguments": {...}}}
                func = tc.get("function", tc)
                name = func.get("name", "")
                raw_args = func.get("arguments", {})

                # arguments 可能是 dict 或 JSON 字符串
                if isinstance(raw_args, str):
                    try:
                        args = _json.loads(raw_args)
                    except _json.JSONDecodeError:
                        args = _parse_arguments_fallback(raw_args)
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    args = {}

                parsed.append(ToolCall(
                    id=f"call_{len(parsed)}",
                    name=name,
                    arguments=args,
                ))

            if parsed:
                return AgentResponse(tool_calls=parsed)

        # 没有 tool_calls，返回纯文本
        content = msg.get("content", "")
        return AgentResponse(content=content)


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
