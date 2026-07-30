# Personal RAG - Agent 循环
"""
Agent 循环模块

实现 ReAct (Reasoning + Acting) 模式的 Agent 主循环。
LLM 自主决策何时调用工具、调用哪个工具、何时生成最终回答。

循环流程:
    while iteration < max_iterations:
        1. LLM.chat_with_tools_stream(messages, tools)
           → 流式接收文本 token 和 tool_use 事件
        2. 如果有 tool_calls → 执行工具 → 结果加入消息 → 继续
        3. 如果只有文本 → 最终回答 → CitationParser 流式输出 → 退出
        4. 如果超过最大迭代 → 强制结束

支持 SSE 流式事件输出，前端可实时查看 Agent 思考过程。
"""

import logging
from collections.abc import AsyncGenerator
from typing import Any, Optional

from app.agent.tools import tool_registry
from app.config import settings
from app.providers.base import LLMProvider

logger = logging.getLogger(__name__)

# Agent System Prompt 模板
AGENT_SYSTEM_PROMPT = """You are a helpful AI assistant with access to document search tools.
You can search uploaded documents to find information that helps answer the user's question.

## Available Tools
{tool_list}

## Rules
1. Carefully analyze the user's question to determine what information you need.
2. Use the tools to search for relevant information. Try different search keywords if needed.
3. When citing information from search results, use the exact [N] numbers shown
   in the tool output. For example, if a result is marked "[3] (from report.pdf)",
   cite it as [3] in your answer. Do NOT renumber or create your own numbers.
4. If multiple searches don't find relevant info, honestly tell the user.
5. After gathering sufficient information, provide a comprehensive answer.
6. Do NOT make up information not found in the search results.

## Response Format
- If you need to search, just call the tool directly — no need to explain.
- After receiving search results, synthesize a complete answer in the user's language.
- Always include citation numbers like [1], [2] when using information from search results."""


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
    _cancellation_flags=None) -> AsyncGenerator[dict[str, Any], None]:
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
        from app.services.citation import CitationParser

        iteration = 0
        force_answer_reason: str = ""  # 空字符串 = 未触发强制模式

        while iteration < self.max_iterations and not force_answer_reason:
            iteration += 1
            logger.debug("Agent iteration %d/%d", iteration, self.max_iterations)

            # 检查取消标志
            if conversation_id:
                from app.api.chat import _cancellation_flags
                if conversation_id in _cancellation_flags and _cancellation_flags[conversation_id].is_set():
                    yield {"event": "token", "data": " [生成已取消]"}
                    force_answer_reason = "cancelled"
                    break

            # Step 1: 检查工具可用性
            tools_schema = self.tools.to_openai_format()
            if not tools_schema:
                logger.warning("No tools available, falling back to plain generation")
                yield {"event": "tool_result",
                       "data": {"name": "_system", "result": "无可用工具，直接回答"}}
                force_answer_reason = "no_tools"
                break

            # Step 2: 流式 LLM 决策 — 文本实时推送，tool_use 收集
            parser = CitationParser()
            tool_calls_in_turn: list[dict[str, Any]] = []
            has_any_output = False

            try:
                async for event in self.provider.chat_with_tools_stream(
                    messages=messages,
                    tools=tools_schema,
                    max_tokens=4096,
                ):
                    if event["type"] == "token":
                        has_any_output = True
                        # 实时解析引用标记并流式推送
                        for evt in parser.feed(event["text"]):
                            if evt["type"] == "token":
                                yield {"event": "token", "data": evt["text"]}
                            elif evt["type"] == "citation":
                                yield {"event": "citation", "data": {"index": evt["index"]}}
                                yield {"event": "token", "data": f"[{evt['index']}]"}
                    elif event["type"] == "tool_use":
                        tool_calls_in_turn.append(event)
            except Exception as e:
                logger.exception("LLM call failed at iteration %d", iteration)
                yield {"event": "error",
                       "data": {"message": f"LLM 调用失败: {str(e)}"}}
                return  # 不可恢复，终止

            # Step 3: 处理流式结果
            if tool_calls_in_turn:
                # LLM 选择调用工具 — 流中已推送的文本为思考过程
                # 清空 parser 残留缓冲（思考文本中的半截 [N 不进入下一轮）
                parser.reset()

                for tc in tool_calls_in_turn:
                    yield {
                        "event": "tool_call",
                        "data": {"name": tc["name"], "arguments": tc["arguments"]},
                    }

                    result = await self.tools.execute(tc["name"], tc["arguments"])

                    yield {
                        "event": "tool_result",
                        "data": {"name": tc["name"], "result": result},
                    }

                    # 将工具调用和结果加入消息历史
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            },
                        }],
                    })
                    messages.append({
                        "role": "tool",
                        "content": result,
                        "tool_call_id": tc["id"],
                    })

                continue  # 继续循环，让 LLM 处理工具结果

            # Step 4: 没有 tool_calls → 最终回答已实时推送，flush 残留
            for evt in parser.flush():
                if evt["type"] == "token":
                    yield {"event": "token", "data": evt["text"]}
                elif evt["type"] == "citation":
                    yield {"event": "citation", "data": {"index": evt["index"]}}
                    yield {"event": "token", "data": f"[{evt['index']}]"}

            if has_any_output:
                # 有内容产出 → 正常回答
                return  # 生成完毕，交由 chat.py 发送 done

            # 完全空响应（模型偶尔返回空消息）
            logger.warning(
                "Empty LLM response at iteration %d, forcing final answer",
                iteration,
            )
            yield {
                "event": "tool_result",
                "data": {
                    "name": "_system",
                    "result": "LLM 返回空响应，基于已收集的信息生成回答",
                },
            }
            force_answer_reason = "empty_response"
            break

        # ── 强制生成最终回答 ─────────────────────────────────
        # 以下三种情况会到达此处:
        #   1. 超过最大迭代次数
        #   2. LLM 返回空响应
        #   3. 没有可用工具
        if force_answer_reason == "empty_response":
            logger.info("Forcing final answer due to empty LLM response")
            yield {
                "event": "max_iterations",
                "data": {"message": "模型未正常返回，基于已收集的信息生成回答"},
            }
            force_prompt = (
                "Based on the tool results above, provide your best answer "
                "to the user's original question. Cite sources if possible "
                "using [1], [2] markers. Be honest about what you don't know."
            )
        elif force_answer_reason == "no_tools":
            logger.info("Forcing final answer due to missing tools")
            force_prompt = (
                "Answer the user's question based on the conversation context. "
                "Cite sources if you have any, using [1], [2] markers."
            )
        else:
            # 超过最大迭代次数
            logger.warning("Agent exceeded max iterations (%d)", self.max_iterations)
            yield {
                "event": "max_iterations",
                "data": {
                    "message": f"Agent 达到最大搜索次数 ({self.max_iterations})，"
                              f"基于已有结果生成回答",
                },
            }
            force_prompt = (
                "You have reached the maximum number of tool calls. "
                "Based on the information gathered so far, provide your best answer "
                "to the user's original question. Cite sources if possible. "
                "Be honest about what you don't know."
            )

        messages.append({"role": "system", "content": force_prompt})

        parser = CitationParser()
        async for token in self.provider.chat_stream(
            messages=messages,
            max_tokens=4096,
        ):
            citation_events = parser.feed(token)
            for evt in citation_events:
                if evt["type"] == "token":
                    yield {"event": "token", "data": evt["text"]}
                elif evt["type"] == "citation":
                    yield {"event": "citation", "data": {"index": evt["index"]}}
                    # 重插 [N] 为 token，确保最终文本包含引用标记
                    yield {"event": "token", "data": f"[{evt['index']}]"}

        # 刷新缓冲区
        for evt in parser.flush():
            if evt["type"] == "token":
                yield {"event": "token", "data": evt["text"]}
            elif evt["type"] == "citation":
                yield {"event": "citation", "data": {"index": evt["index"]}}
                yield {"event": "token", "data": f"[{evt['index']}]"}

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
