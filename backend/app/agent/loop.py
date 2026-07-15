# Personal RAG - Agent 循环
"""
Agent 循环模块

实现 ReAct (Reasoning + Acting) 模式的 Agent 主循环。
LLM 自主决策何时调用工具、调用哪个工具、何时生成最终回答。

循环流程:
    while iteration < max_iterations:
        1. LLM.chat_with_tools(messages, tools)
        2. 如果有 tool_calls → 执行工具 → 结果加入消息 → 继续
        3. 如果只有 content → 最终回答 → 退出循环
        4. 如果超过最大迭代 → 强制结束

支持 SSE 流式事件输出，前端可实时查看 Agent 思考过程。
"""

import logging
from collections.abc import AsyncGenerator
from typing import Any, Optional

from app.agent.tools import tool_registry
from app.config import settings
from app.providers.base import AgentResponse, LLMProvider

logger = logging.getLogger(__name__)

# Agent System Prompt 模板
AGENT_SYSTEM_PROMPT = """You are a helpful AI assistant with access to document search tools.
You can search uploaded documents to find information that helps answer the user's question.

## Available Tools
{tool_list}

## Rules
1. Carefully analyze the user's question to determine what information you need.
2. Use the tools to search for relevant information. Try different search keywords if needed.
3. When citing information from documents, use [1], [2] etc. to reference sources.
4. If multiple searches don't find relevant info, honestly tell the user.
5. After gathering sufficient information, provide a comprehensive answer.
6. Do NOT make up information not found in the search results.

## Response Format
- If you need to search, just call the tool directly — no need to explain.
- After receiving search results, synthesize a complete answer in the user's language."""


class AgentLoop:
    """
    ReAct Agent 主循环。

    管理 LLM 与工具之间的多轮交互，直到 LLM 给出最终回答
    或达到最大迭代次数。

    Attributes:
        provider: LLM provider 实例
        max_iterations: 最大 think→act→observe 轮次
        tools: 可用工具注册表
    """

    def __init__(
        self,
        provider: LLMProvider,
        max_iterations: Optional[int] = None,
        tools: Optional[Any] = None,
    ) -> None:
        """
        初始化 Agent 循环。

        Args:
            provider: LLM provider 实例
            max_iterations: 最大迭代轮次，默认从配置读取
            tools: 工具注册表，默认使用全局 tool_registry
        """
        self.provider = provider
        self.max_iterations = max_iterations or settings.agent_max_iterations
        self.tools = tools or tool_registry

    async def run(
        self,
        question: str,
        conversation_id: Optional[str] = None,
        chat_history: Optional[list[dict[str, str]]] = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        执行 Agent 主循环，yield SSE 事件。

        事件类型:
            - thinking: Agent 的思考/计划过程
            - tool_call: 工具调用开始 {"name": "...", "arguments": {...}}
            - tool_result: 工具调用结果 {"name": "...", "result": "..."}
            - token: 最终回答的文本片段
            - citation: 引用标记 [N]
            - done: 生成完成
            - error: 错误信息
            - max_iterations: 超过最大迭代次数警告

        Args:
            question: 用户问题
            conversation_id: 对话 ID（用于取消检查）
            chat_history: 历史对话消息

        Yields:
            dict: SSE 事件
        """
        # ── 构建初始消息 ──────────────────────────────────────
        tool_list = self._build_tool_list()
        system_prompt = AGENT_SYSTEM_PROMPT.format(tool_list=tool_list)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]

        # 添加历史对话（最近 3 轮）
        if chat_history:
            messages.extend(chat_history[-6:])

        messages.append({"role": "user", "content": question})

        # ── Agent 循环 ─────────────────────────────────────────
        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1
            logger.debug("Agent iteration %d/%d", iteration, self.max_iterations)

            # 检查取消标志
            if conversation_id:
                from app.api.chat import _cancellation_flags
                if conversation_id in _cancellation_flags and _cancellation_flags[conversation_id].is_set():
                    yield {"event": "token", "data": " [生成已取消]"}
                    break

            # Step 1: LLM 决策
            tools_schema = self.tools.to_openai_format()
            if not tools_schema:
                # 没有工具可用，回退到普通生成
                logger.warning("No tools available, falling back to plain generation")
                yield {"event": "tool_result",
                       "data": {"name": "_system", "result": "无可用工具，直接回答"}}
                break

            try:
                response: AgentResponse = await self.provider.chat_with_tools(
                    messages=messages,
                    tools=tools_schema,
                )
            except Exception as e:
                logger.exception("LLM call failed at iteration %d", iteration)
                yield {"event": "error",
                       "data": {"message": f"LLM 调用失败: {str(e)}"}}
                return  # 不可恢复，终止

            # Step 2: 处理响应
            if response.tool_calls:
                # LLM 选择调用工具
                for tc in response.tool_calls:
                    # 通知前端
                    yield {
                        "event": "tool_call",
                        "data": {"name": tc.name, "arguments": tc.arguments},
                    }

                    # 执行工具
                    result = await self.tools.execute(tc.name, tc.arguments)

                    # 通知前端结果
                    yield {
                        "event": "tool_result",
                        "data": {"name": tc.name, "result": result},
                    }

                    # 将工具调用和结果加入消息历史
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": str(tc.arguments),
                            },
                        }],
                    })
                    messages.append({
                        "role": "tool",
                        "content": result,
                        "tool_call_id": tc.id,
                    })

                # 继续循环，让 LLM 处理工具结果
                continue

            elif response.content:
                # LLM 给出最终文本回答
                # 流式输出最终回答
                from app.services.citation import CitationParser

                parser = CitationParser()
                full_content = ""

                async for token in self.provider.chat_stream(
                    messages=messages,
                ):
                    full_content += token
                    citation_events = parser.feed(token)
                    for evt in citation_events:
                        if evt["type"] == "token":
                            yield {"event": "token", "data": evt["text"]}
                        elif evt["type"] == "citation":
                            yield {"event": "citation", "data": {"index": evt["index"]}}

                # 刷新引用缓冲区
                for evt in parser.flush():
                    if evt["type"] == "token":
                        yield {"event": "token", "data": evt["text"]}
                    elif evt["type"] == "citation":
                        yield {"event": "citation", "data": {"index": evt["index"]}}

                return  # 生成完毕，交由 chat.py 发送 done

            else:
                # 空响应（模型可能卡住了）
                logger.warning("Empty LLM response at iteration %d", iteration)
                yield {"event": "error",
                       "data": {"message": "LLM 返回空响应，请重试"}}
                return

        # ── 超过最大迭代 ─────────────────────────────────────
        logger.warning("Agent exceeded max iterations (%d)", self.max_iterations)
        yield {
            "event": "max_iterations",
            "data": {
                "message": f"Agent 达到最大搜索次数 ({self.max_iterations})，"
                          f"基于已有结果生成回答",
            },
        }

        # 强制生成最终回答
        messages.append({
            "role": "system",
            "content": (
                "You have reached the maximum number of tool calls. "
                "Based on the information gathered so far, provide your best answer "
                "to the user's original question. Cite sources if possible. "
                "Be honest about what you don't know."
            ),
        })

        from app.services.citation import CitationParser

        parser = CitationParser()
        async for token in self.provider.chat_stream(messages=messages):
            citation_events = parser.feed(token)
            for evt in citation_events:
                if evt["type"] == "token":
                    yield {"event": "token", "data": evt["text"]}
                elif evt["type"] == "citation":
                    yield {"event": "citation", "data": {"index": evt["index"]}}

        # 不 yield done —— chat.py 在生成器耗尽后处理

    def _build_tool_list(self) -> str:
        """构建供 system prompt 显示的工具列表。"""
        tools = self.tools.list_all()
        if not tools:
            return "(No tools available)"

        lines = []
        for t in tools:
            params = t.parameters.get("properties", {})
            param_desc = ", ".join(
                f"{k}: {v.get('type', 'string')}"
                for k, v in params.items()
            )
            lines.append(f"- **{t.name}**({param_desc}): {t.description}")
        return "\n".join(lines)
