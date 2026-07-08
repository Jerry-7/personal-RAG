# Personal RAG - LLM 生成服务
"""
生成服务模块

负责 RAG Prompt 构建、LLM provider 选择调用，
以及流式输出的引用解析编排。
"""

import json
from collections.abc import AsyncGenerator
from typing import Any, Optional

from app.config import settings
from app.providers.base import LLMProvider
from app.providers.ollama import OllamaLLMProvider
from app.services.citation import CitationParser


# ── RAG Prompt 模板 ──────────────────────────────────────────────

RAG_SYSTEM_PROMPT = """You are a helpful AI assistant with access to uploaded documents.
Answer the user's question based ONLY on the provided context below.
When you reference information from the context, cite it using the source number in square brackets: [1], [2], etc.
If multiple sources support the same point, cite all relevant ones: [1][3].
If the context doesn't contain enough information to answer, say so honestly.
Do NOT use citations for information not from the provided context.

{context}"""

RAG_USER_PROMPT = "Question: {question}\nAnswer:"


class Generator:
    """
    RAG 生成器。

    管理 LLM provider 创建、prompt 构建和流式生成。
    集成 CitationParser 实时检测引用标记。

    Attributes:
        provider_name: 当前使用的 LLM provider
    """

    def __init__(self, provider_name: Optional[str] = None) -> None:
        """
        初始化生成器。

        Args:
            provider_name: Provider 名称，默认从配置读取
        """
        self.provider_name = provider_name or settings.llm_provider
        self._provider: Optional[LLMProvider] = None

    async def _get_provider(self) -> LLMProvider:
        """
        获取或创建 LLM provider 实例。

        根据 provider_name 动态选择后端。

        Returns:
            LLMProvider 实例

        Raises:
            ValueError: 不支持的 provider
        """
        if self._provider is not None:
            return self._provider

        if self.provider_name == "ollama":
            self._provider = OllamaLLMProvider()
        elif self.provider_name == "openai":
            from app.providers.openai_provider import OpenAILLMProvider
            self._provider = OpenAILLMProvider()
        elif self.provider_name == "anthropic":
            from app.providers.anthropic_provider import AnthropicLLMProvider
            self._provider = AnthropicLLMProvider()
        else:
            raise ValueError(f"不支持的 LLM provider: {self.provider_name}")

        return self._provider

    def build_context(
        self,
        retrieved_chunks: list[dict[str, Any]],
    ) -> str:
        """
        将检索结果格式化为 RAG 上下文文本。

        每个 chunk 用 [Source N] 标记，包含文档名、页码和时间戳信息。

        Args:
            retrieved_chunks: retriever.retrieve() 返回的结果列表

        Returns:
            格式化的上下文字符串
        """
        if not retrieved_chunks:
            return "No relevant documents found in the knowledge base."

        parts = []
        for i, chunk in enumerate(retrieved_chunks, start=1):
            # 构建来源描述
            source_label = f"[Source {i}] (from {chunk.get('filename', 'unknown')}"
            if chunk.get("page_number"):
                source_label += f", page {chunk['page_number']}"
            if chunk.get("start_timestamp") is not None:
                start = chunk["start_timestamp"]
                end = chunk.get("end_timestamp", start)
                source_label += f", {self._fmt_time(start)}-{self._fmt_time(end)}"
            source_label += ")"

            parts.append(f"{source_label}:\n{chunk['text']}")

        return "\n\n".join(parts)

    async def generate_stream(
        self,
        question: str,
        retrieved_chunks: list[dict[str, Any]],
        chat_history: Optional[list[dict[str, str]]] = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        执行 RAG 流式生成。

        完整流程：
        1. 构建 RAG Prompt (system + context + user question)
        2. 调用 LLM stream
        3. 通过 CitationParser 实时检测 [N] 引用
        4. Yield SSE 事件 (token / citation)

        Args:
            question: 用户问题
            retrieved_chunks: 检索结果列表
            chat_history: 历史对话消息

        Yields:
            dict: SSE 事件 {"type": "token", "text": "..."} 或
                 {"type": "citation", "index": N}
        """
        # Step 1: 构建 context
        context = self.build_context(retrieved_chunks)

        # Step 2: 构建 messages
        messages = [{"role": "system", "content": RAG_SYSTEM_PROMPT.format(context=context)}]

        # 添加历史对话（最近几轮）
        if chat_history:
            messages.extend(chat_history[-6:])  # 最多保留最近 3 轮

        messages.append({"role": "user", "content": RAG_USER_PROMPT.format(question=question)})

        # Step 3: 流式生成 + 引用解析
        provider = await self._get_provider()
        parser = CitationParser()

        async for token in provider.chat_stream(messages=messages):
            events = parser.feed(token)
            for event in events:
                yield event

        # 刷新缓冲区
        for event in parser.flush():
            yield event

    def get_citations_for_chunks(
        self,
        retrieved_chunks: list[dict[str, Any]],
        used_indices: list[int],
    ) -> list[dict[str, Any]]:
        """
        根据 LLM 实际使用的引用索引构建 CitationData 列表。

        Args:
            retrieved_chunks: 检索结果列表
            used_indices: LLM 实际引用的索引列表 [1, 2, ...]

        Returns:
            引用元数据列表，用于前端 CitationMark 和 Sidebar
        """
        citations = []
        for idx in used_indices:
            if 1 <= idx <= len(retrieved_chunks):
                chunk = retrieved_chunks[idx - 1]
                citations.append({
                    "index": idx,
                    "document_id": chunk.get("document_id", ""),
                    "chunk_id": chunk.get("chunk_id", ""),
                    "snippet": chunk.get("text", "")[:200],
                    "filename": chunk.get("filename", ""),
                    "page_number": chunk.get("page_number"),
                    "start_timestamp": chunk.get("start_timestamp"),
                    "end_timestamp": chunk.get("end_timestamp"),
                    "source_type": chunk.get("source_type", "text"),
                })
        return citations

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        """格式化秒数为 mm:ss 格式。"""
        m, s = divmod(int(seconds), 60)
        return f"{m:02d}:{s:02d}"


# 全局单例
generator = Generator()
