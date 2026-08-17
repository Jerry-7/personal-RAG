# Personal RAG - Agent 对话执行服务
"""
对话执行服务模块

从 api/chat.py 拆分出的执行编排层，包含两部分职责：
1. ChatRunManager：管理进行中对话的取消/暂停运行状态（模块级单例）。
2. agent_event_generator：Agent 模式 SSE 事件生成器，编排路由决策、
   目标树、Agent/Supervisor 执行、引用映射与消息持久化。

HTTP 层（app/api/chat.py）只负责请求解析与响应包装，调用本模块完成执行。
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AgentRun, Conversation, Message
from app.services.conversation_memory import conversation_memory
from app.services.context_compression import ContextCompressionError

logger = logging.getLogger(__name__)

# 字符级流式输出的间隔秒数
STREAM_CHARACTER_DELAY_SECONDS = 0.006


def _running_pause_event() -> asyncio.Event:
    """创建一个"运行中"的暂停事件（默认已 set，wait_if_paused 不阻塞）。"""
    event = asyncio.Event()
    event.set()
    return event


class ChatRunManager:
    """
    管理对话级 Agent 运行的取消/暂停标志与生命周期。

    每个进行中的 conversation_id 维护一对 asyncio.Event：
    - cancellation_event: 取消请求标志
    - pause_event: 暂停/恢复请求标志（默认已 set = 运行中）

    与 TaskManager/EventBus 一致，作为模块级单例使用。
    """

    def __init__(self) -> None:
        self._cancellation_flags: dict[str, asyncio.Event] = {}
        self._pause_flags: dict[str, asyncio.Event] = {}

    # ── 只读状态访问（供测试注入/清理）─────────────────────
    @property
    def cancellation_flags(self) -> dict[str, asyncio.Event]:
        """conversation_id → 取消标志 映射。"""
        return self._cancellation_flags

    @property
    def pause_flags(self) -> dict[str, asyncio.Event]:
        """conversation_id → 暂停标志 映射。"""
        return self._pause_flags

    # ── 生命周期 ─────────────────────────────────────────
    def register(self, conversation_id: str) -> None:
        """创建对话时初始化取消/暂停标志。"""
        self._cancellation_flags[conversation_id] = asyncio.Event()
        self._pause_flags[conversation_id] = _running_pause_event()

    def get_or_create_events(
        self, conversation_id: str
    ) -> tuple[asyncio.Event, asyncio.Event]:
        """返回对话对应的 (取消, 暂停) 事件；缺失时按运行中状态补建。"""
        cancellation_event = self._cancellation_flags.setdefault(
            conversation_id, asyncio.Event()
        )
        pause_event = self._pause_flags.get(conversation_id)
        if pause_event is None:
            pause_event = _running_pause_event()
            self._pause_flags[conversation_id] = pause_event
        return cancellation_event, pause_event

    def cleanup(
        self,
        conversation_id: str,
        cancellation_event: asyncio.Event,
        pause_event: asyncio.Event,
    ) -> None:
        """
        清理对话的运行标志。

        仅当标志仍属于本次运行时才移除（is 身份守卫）：保证同一
        conversation_id 上若已有更新的 run 覆盖了标志，旧 run 的
        finally 不会误删新 run 的状态。
        """
        if self._cancellation_flags.get(conversation_id) is cancellation_event:
            self._cancellation_flags.pop(conversation_id, None)
        if self._pause_flags.get(conversation_id) is pause_event:
            self._pause_flags.pop(conversation_id, None)

    # ── 端点逻辑（原 chat.py cancel/pause/resume 端点）─────
    def cancel(self, conversation_id: str) -> dict[str, str]:
        """取消正在进行的对话生成。"""
        if conversation_id and conversation_id in self._cancellation_flags:
            pause_event = self._pause_flags.get(conversation_id)
            if pause_event is not None:
                pause_event.set()
            self._cancellation_flags[conversation_id].set()
            return {"status": "cancelled", "conversation_id": conversation_id}
        return {"status": "not_found", "message": "没有正在进行的生成或对话 ID 无效"}

    def pause(self, db: Session, conversation_id: str) -> dict[str, str]:
        """在下一个协作点暂停进行中的 Agent 运行。"""
        pause_event = self._pause_flags.get(conversation_id)
        if pause_event is None:
            return {"status": "not_found", "message": "No active run for this conversation"}

        agent_run = (
            db.query(AgentRun)
            .filter(
                AgentRun.conversation_id == conversation_id,
                AgentRun.status.in_(("running", "paused")),
            )
            .order_by(AgentRun.started_at.desc())
            .first()
        )
        if agent_run is None:
            return {"status": "not_found", "message": "No active run for this conversation"}

        pause_event.clear()
        agent_run.status = "paused"
        db.commit()
        return {
            "status": "paused",
            "conversation_id": conversation_id,
            "run_id": agent_run.id,
        }

    def resume(self, db: Session, conversation_id: str) -> dict[str, str]:
        """恢复协作暂停的 Agent 运行。"""
        pause_event = self._pause_flags.get(conversation_id)
        if pause_event is None:
            return {"status": "not_found", "message": "No paused run for this conversation"}

        agent_run = (
            db.query(AgentRun)
            .filter(
                AgentRun.conversation_id == conversation_id,
                AgentRun.status == "paused",
            )
            .order_by(AgentRun.started_at.desc())
            .first()
        )
        if agent_run is None:
            return {"status": "not_found", "message": "No paused run for this conversation"}

        agent_run.status = "running"
        db.commit()
        pause_event.set()
        return {
            "status": "running",
            "conversation_id": conversation_id,
            "run_id": agent_run.id,
        }


async def agent_event_generator(
    question: str,
    conversation_id: str,
    db: Session,
    conv: Conversation,
    chat_history: list[dict[str, str]],
    mode: str,
    user_message_id: str,
    tier_preference: str = "auto",
    retry_of_run_id: str | None = None,
):
    """
    Agent 模式事件生成器。

    LLM 自主决策：何时检索、检索什么、是否需要多轮检索。
    通过 tool_call/tool_result 事件向前端展示思考过程。

    体内 import 保持懒加载：避免 agent/supervisor 等重子模块在
    应用启动时被急切导入，防止将来出现循环导入。
    """
    from app.agent.loop import AgentLoop
    from app.agent.context import AgentRunContext
    from app.agent.model_selection import select_agent_model
    from app.agent.adaptive_routing import AdaptiveComplexityRouter
    from app.agent.routing import build_default_agent_registry
    from app.agent.supervisor import Supervisor
    from app.services.generator import generator as gen_service
    from app.services.goal_runtime import GoalRuntime, serialize_event
    from app.services.routing_policy import get_active_routing_policy

    cancellation_event, pause_event = chat_run_manager.get_or_create_events(
        conversation_id
    )
    # dict[str , agent_profile] fast/standard/expert/expert_supervisor/local_retriever/web_researcher/expert_synthesizer
    agent_registry = build_default_agent_registry()
    # provider: ollama/openai/anthropic
    routing_provider = await gen_service._get_provider()
    # version, standard_min_score, expert_min_score
    routing_policy = get_active_routing_policy(db)
    classifier_selection = select_agent_model(agent_registry.require("fast_general"))
    route_decision = await AdaptiveComplexityRouter(
        routing_policy,
        routing_provider,
        classifier_model=classifier_selection.model,
    ).route(
        question,
        mode=mode,
        history=chat_history,
        tier_preference=tier_preference,
    )
    agent_profile = agent_registry.for_decision(route_decision)
    model_selection = select_agent_model(agent_profile)
    # 构建数据库AgentRun对象
    agent_run = AgentRun(
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        retry_of_run_id=retry_of_run_id,
        mode=mode,
        route_tier_preference=tier_preference,
        route_policy_version=route_decision.policy_version,
        agent_profile=agent_profile.name,
        route_tier=route_decision.tier,
        route_name=route_decision.route,
        route_score=route_decision.score,
        route_reasons_json=json.dumps(route_decision.reasons),
        route_decision_source=route_decision.decision_source,
        route_confidence=route_decision.confidence,
        route_classifier_model=route_decision.classifier_model,
        route_classifier_original_tokens=route_decision.classifier_original_tokens,
        route_classifier_compressed_tokens=route_decision.classifier_compressed_tokens,
        route_classifier_calls=route_decision.classifier_calls,
        route_requires_decomposition=route_decision.requires_decomposition,
        route_max_children=route_decision.max_children,
        route_max_depth=route_decision.max_depth,
        model_provider=model_selection.provider,
        model_name=model_selection.model,
        status="running",
        web_page_budget=settings.web_page_budget,
        max_depth=settings.web_crawl_max_depth,
    )
    db.add(agent_run)
    db.commit()
    goal_runtime = GoalRuntime(db, agent_run.id)
    root_goal, initial_goal_events = goal_runtime.create_root(
        title=question,
        agent_profile=agent_profile.name,
        input_data={"question": question, "mode": mode, "agent_tier": tier_preference},
        tool_call_budget=0,
    )
    agent_goal, agent_goal_events = goal_runtime.create_child(
        parent=root_goal,
        title="执行用户请求",
        kind="agent",
        agent_profile=agent_profile.name,
        input_data={"question": question, "route": route_decision.route},
        tool_call_budget=agent_profile.tool_call_budget,
        tool_repeat_limit=agent_profile.tool_repeat_limit,
        model_provider=model_selection.provider,
        model_name=model_selection.model,
    )
    initial_goal_events.extend(agent_goal_events)
    # 构建上下文
    run_context = AgentRunContext(
        db=db,
        conversation_id=conversation_id,
        run_id=agent_run.id,
        goal_node_id=agent_goal.id,
        mode=mode,
        cancellation_event=cancellation_event,
        pause_event=pause_event,
        agent_profile=agent_profile.name,
        tool_call_budget=agent_profile.tool_call_budget,
        tool_repeat_limit=agent_profile.tool_repeat_limit,
        web_page_budget=agent_run.web_page_budget,
        max_crawl_depth=agent_run.max_depth,
    )

    # 创建 LLM provider
    llm_provider = routing_provider

    # 创建 Agent 循环
    agent = AgentLoop(
        provider=llm_provider,
        max_iterations=agent_profile.max_iterations,
        model_name=model_selection.model,
    )

    # [regist_citation_index, display_citation_index]
    citation_index_map: dict[int, int] = {}
    pending_citation_token: tuple[int, int | None] | None = None
    full_content = ""
    run_error_message = ""

    try:
        yield {
            "event": "run_started",
            "data": json.dumps({
                "run_id": agent_run.id,
                "retry_of_run_id": retry_of_run_id,
                "conversation_id": conversation_id,
                "mode": mode,
                "web_page_budget": agent_run.web_page_budget,
                "max_depth": agent_run.max_depth,
                **model_selection.to_dict(),
            }),
        }

        # 运行 Agent 循环
        yield {
            "event": "route_selected",
            "data": json.dumps({
                **route_decision.to_dict(),
                "agent_profile": agent_profile.name,
                "tool_call_budget": agent_profile.tool_call_budget,
                "tool_repeat_limit": agent_profile.tool_repeat_limit,
                **model_selection.to_dict(),
            }, ensure_ascii=False),
        }

        for goal_event in initial_goal_events:
            yield {
                "event": goal_event.event_type,
                "data": json.dumps(serialize_event(goal_event), ensure_ascii=False),
            }

        if route_decision.requires_decomposition:
            supervisor = Supervisor(
                provider=llm_provider,
                registry=agent_registry,
                goal_runtime=goal_runtime,
                parent_goal=agent_goal,
                context=run_context,
            )
            execution_stream = supervisor.run(
                question=question,
                mode=mode,
                chat_history=chat_history,
            )
        else:
            execution_stream = agent.run(
                question=question,
                conversation_id=conversation_id,
                chat_history=chat_history,
                context=run_context,
            )

        async for event in execution_stream:
            evt_type = event.get("event", "")
            data = event.get("data", "")

            if evt_type == "token":
                # 将raw_index 转换为display_index
                token_text = data if isinstance(data, str) else data.get("text", "")
                if pending_citation_token is not None:
                    raw_index, display_index = pending_citation_token
                    if token_text == f"[{raw_index}]":
                        token_text = f"[{display_index}]" if display_index is not None else ""
                    pending_citation_token = None
                if not token_text:
                    continue
                full_content += token_text
                is_citation_marker = bool(re.fullmatch(r"\[\d+\]", token_text))
                chunks = [token_text] if is_citation_marker else token_text
                for character in chunks:
                    await run_context.wait_if_paused()
                    if run_context.is_cancelled():
                        break
                    yield {"event": "token", "data": json.dumps({"text": character})}
                    if not is_citation_marker:
                        await asyncio.sleep(STREAM_CHARACTER_DELAY_SECONDS)
                continue

            elif evt_type == "citation":
                idx = data.get("index", 0) if isinstance(data, dict) else data
                registered_indices = {item["index"] for item in run_context.citations}
                if isinstance(idx, int) and idx in registered_indices:
                    if idx not in citation_index_map:
                        citation_index_map[idx] = len(citation_index_map) + 1
                    display_index = citation_index_map[idx]
                    pending_citation_token = (idx, display_index)
                    yield {
                        "event": "citation",
                        "data": json.dumps({"index": display_index}),
                    }
                else:
                    logger.warning("Dropping unregistered citation index: %r", idx)
                    pending_citation_token = (idx, None) if isinstance(idx, int) else None
                continue

            elif evt_type == "tool_call":
                # Agent 调用工具
                logger.debug("Agent tool call: %s", data.get("name", "?"))

            elif evt_type == "tool_result":
                # 工具执行结果
                logger.debug("Agent tool result: %s (%d chars)",
                           data.get("name", "?"),
                           len(data.get("result", "")))

            elif evt_type in {"context_compressed", "context_compression_failed"}:
                payload = data if isinstance(data, dict) else {"message": str(data)}
                runtime_event = goal_runtime.record_runtime_event(
                    evt_type,
                    payload,
                    node_id=str(payload.get("node_id") or "") or None,
                )
                data = serialize_event(runtime_event)

            elif evt_type == "error":
                # 错误事件直接转发
                run_error_message = str(data.get("message", "Agent 执行失败")) if isinstance(data, dict) else str(data)
                yield {"event": "error", "data": json.dumps(data)}
                # 错误发生后仍尝试保存已有内容
                continue

            elif evt_type == "max_iterations":
                logger.warning("Agent reached max iterations for conv %s", conversation_id)

            else:
                logger.debug("Unknown agent event: %s", evt_type)

            # 转发事件给前端
            yield {
                "event": evt_type,
                "data": json.dumps(data, ensure_ascii=False)
                if isinstance(data, (dict, list)) else data,
            }

        # ── 保存 AI 消息 ──────────────────────────────────────
        if full_content.strip():
            # Agent 模式下：从全局引用注册表构建引用元数据
            # 只保留 LLM 实际使用的引用编号（通过 [N] 检测到的）
            all_registered = run_context.citations
            registered_by_index = {c["index"]: c for c in all_registered}
            citations = [
                {**registered_by_index[raw_index], "index": display_index}
                for raw_index, display_index in sorted(
                    citation_index_map.items(), key=lambda item: item[1]
                )
                if raw_index in registered_by_index
            ]

            ai_msg = Message(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                role="assistant",
                content=full_content,
                citations_json=json.dumps(citations, ensure_ascii=False),
                token_count=len(full_content) // 4,
            )
            db.add(ai_msg)
            conv.updated_at = datetime.now(timezone.utc)
            agent_run.assistant_message_id = ai_msg.id
            agent_run.status = "failed" if run_error_message else ("cancelled" if cancellation_event.is_set() else "completed")
            agent_run.error_message = run_error_message or None
            agent_run.web_pages_used = run_context.web_pages_used
            agent_run.completed_at = datetime.now(timezone.utc)
            db.commit()
            try:
                summary_update = await conversation_memory.update_summary(
                    db,
                    conversation_id,
                    llm_provider,
                    model_name=model_selection.model,
                )
                if summary_update and summary_update.stats.compressed:
                    payload = {
                        "scope": "conversation_memory",
                        "node_id": agent_goal.id,
                        **summary_update.stats.to_dict(),
                    }
                    runtime_event = goal_runtime.record_runtime_event(
                        "context_compressed",
                        payload,
                        node_id=agent_goal.id,
                    )
                    yield {
                        "event": "context_compressed",
                        "data": json.dumps(serialize_event(runtime_event)),
                    }
            except ContextCompressionError as exc:
                logger.exception("Conversation memory compression failed")
                payload = {
                    "scope": "conversation_memory",
                    "node_id": agent_goal.id,
                    "message": str(exc),
                }
                runtime_event = goal_runtime.record_runtime_event(
                    "context_compression_failed",
                    payload,
                    node_id=agent_goal.id,
                )
                yield {
                    "event": "context_compression_failed",
                    "data": json.dumps(serialize_event(runtime_event), ensure_ascii=False),
                }
            goal_events = [
                goal_runtime.transition(
                    agent_goal,
                    agent_run.status,
                    output={"message_id": ai_msg.id},
                    error_message=agent_run.error_message,
                ),
                goal_runtime.transition(
                    root_goal,
                    agent_run.status,
                    output={"message_id": ai_msg.id},
                    error_message=agent_run.error_message,
                ),
            ]
            for goal_event in goal_events:
                yield {
                    "event": goal_event.event_type,
                    "data": json.dumps(serialize_event(goal_event), ensure_ascii=False),
                }

            # 发送完成事件
            yield {
                "event": "done",
                "data": json.dumps({
                    "citations": citations,
                    "conversation_id": conversation_id,
                    "message_id": ai_msg.id,
                    "run_id": agent_run.id,
                }, ensure_ascii=False),
            }
        else:
            # 没有生成内容
            agent_run.status = "failed" if run_error_message else ("cancelled" if cancellation_event.is_set() else "completed")
            agent_run.error_message = run_error_message or None
            agent_run.web_pages_used = run_context.web_pages_used
            agent_run.completed_at = datetime.now(timezone.utc)
            db.commit()
            goal_events = [
                goal_runtime.transition(
                    agent_goal,
                    agent_run.status,
                    output={"message_id": ""},
                    error_message=agent_run.error_message,
                ),
                goal_runtime.transition(
                    root_goal,
                    agent_run.status,
                    output={"message_id": ""},
                    error_message=agent_run.error_message,
                ),
            ]
            for goal_event in goal_events:
                yield {
                    "event": goal_event.event_type,
                    "data": json.dumps(serialize_event(goal_event), ensure_ascii=False),
                }
            yield {
                "event": "done",
                "data": json.dumps({
                    "citations": [],
                    "conversation_id": conversation_id,
                    "message_id": "",
                    "run_id": agent_run.id,
                }),
            }

    except Exception as e:
        logger.exception("Agent generation failed")
        agent_run.status = "failed"
        agent_run.error_message = str(e)
        agent_run.web_pages_used = run_context.web_pages_used
        agent_run.completed_at = datetime.now(timezone.utc)
        db.commit()
        for goal in (agent_goal, root_goal):
            if goal.status == "running":
                goal_event = goal_runtime.transition(
                    goal,
                    "failed",
                    error_message=str(e),
                )
                yield {
                    "event": goal_event.event_type,
                    "data": json.dumps(serialize_event(goal_event), ensure_ascii=False),
                }
        yield {
            "event": "error",
            "data": json.dumps({"message": f"Agent 生成失败: {str(e)}"}),
        }
    finally:
        # 清理取消标志
        chat_run_manager.cleanup(conversation_id, cancellation_event, pause_event)


# 模块级单例
chat_run_manager = ChatRunManager()
