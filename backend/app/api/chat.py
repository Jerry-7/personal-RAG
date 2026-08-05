# Personal RAG - 聊天 API (SSE 流式)
"""
聊天 API 模块

提供基于 SSE 的流式 RAG 问答接口，整合检索、生成和引用解析。
包含查询、对话历史管理和取消生成功能。

聊天请求统一由 Agent 执行，支持本地检索、网页研究和多轮工具调用。
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.db.database import get_db
from app.db.models import AgentRun, Conversation, Message
from app.services.conversation_memory import conversation_memory

logger = logging.getLogger(__name__)
router = APIRouter()

STREAM_CHARACTER_DELAY_SECONDS = 0.006

# 取消生成的事件标志 (key: conversation_id)
_cancellation_flags: dict[str, asyncio.Event] = {}


@router.post("/chat/query")
async def chat_query(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    RAG 问答 SSE 流式接口。

    接收用户问题，执行检索增强生成流水线，通过 SSE 流式返回结果。
    每条 SSE 事件包含 token 文本或 citation 引用标记。

    Request body (JSON):
        - question: str  用户问题
        - conversation_id: str|null  已有对话 ID，None 则创建新对话

    SSE events:
        - event: token    data: {"text": "..."}
        - event: citation data: {"index": N}
        - event: done     data: {"citations": [...], "conversation_id": "...", "message_id": "..."}
        - event: error    data: {"message": "..."}

    Additional Agent events:
        - event: tool_call   data: {"name": "...", "arguments": {...}}
        - event: tool_result data: {"name": "...", "result": "..."}
        - event: max_iterations data: {"message": "..."}
    """
    # 解析请求体
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    question = body.get("question", "").strip()
    if not question:
        async def _error_gen():
            yield {"event": "error", "data": json.dumps({"message": "问题不能为空"})}
        return EventSourceResponse(_error_gen())

    conversation_id = body.get("conversation_id")
    mode = body.get("mode", "auto")
    if mode not in {"auto", "local", "web"}:
        async def _mode_error_gen():
            yield {"event": "error", "data": json.dumps({"message": "mode 必须是 auto、local 或 web"})}
        return EventSourceResponse(_mode_error_gen())

    # ── 创建或获取对话 ──────────────────────────────────────
    if conversation_id:
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    else:
        conv = None
    # 创建新对话
    if not conv:
        llm_model = {
            "openai": settings.openai_llm_model,
            "anthropic": settings.anthropic_llm_model,
        }.get(settings.llm_provider, settings.ollama_llm_model)
        embedding_model = (
            settings.openai_embedding_model
            if settings.embedding_provider == "openai"
            else settings.ollama_embedding_model
        )
        conv = Conversation(
            id=str(uuid.uuid4()),
            title=question[:80],
            model_provider=settings.llm_provider,
            model_name=llm_model,
            embedding_provider=settings.embedding_provider,
            embedding_model=embedding_model,
        )
        db.add(conv)
        db.commit()
        conversation_id = conv.id

    # 保存用户消息
    user_msg = Message(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        role="user",
        content=question,
    )
    db.add(user_msg)
    db.commit()

    # ── 加载历史对话（供 LLM 上下文） ──────────────────────────
    # 查询该对话的历史消息（按时间升序），转换为 [{role, content}, ...]
    chat_history = conversation_memory.get_context(
        db, conversation_id, exclude_message_id=user_msg.id
    )

    _cancellation_flags[conversation_id] = asyncio.Event()

    # ── 启动 Agent ────────────────────────────────────────────
    stream = _agent_event_generator(
        question, conversation_id, db, conv, chat_history, mode, user_msg.id
    )

    return EventSourceResponse(stream)


async def _agent_event_generator(
    question: str,
    conversation_id: str,
    db: Session,
    conv: Conversation,
    chat_history: list[dict[str, str]],
    mode: str,
    user_message_id: str,
):
    """
    Agent 模式事件生成器。

    LLM 自主决策：何时检索、检索什么、是否需要多轮检索。
    通过 tool_call/tool_result 事件向前端展示思考过程。
    """
    from app.agent.loop import AgentLoop
    from app.agent.context import AgentRunContext
    from app.services.generator import generator as gen_service

    cancellation_event = _cancellation_flags.setdefault(conversation_id, asyncio.Event())
    agent_run = AgentRun(
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        mode=mode,
        status="running",
        web_page_budget=settings.web_page_budget,
        max_depth=settings.web_crawl_max_depth,
    )
    db.add(agent_run)
    db.commit()
    run_context = AgentRunContext(
        db=db,
        conversation_id=conversation_id,
        run_id=agent_run.id,
        mode=mode,
        cancellation_event=cancellation_event,
        web_page_budget=agent_run.web_page_budget,
        max_crawl_depth=agent_run.max_depth,
    )

    # 创建 LLM provider
    llm_provider = await gen_service._get_provider()

    # 创建 Agent 循环
    agent = AgentLoop(provider=llm_provider)

    citation_index_map: dict[int, int] = {}
    pending_citation_token: tuple[int, int | None] | None = None
    full_content = ""
    run_error_message = ""

    try:
        yield {
            "event": "run_started",
            "data": json.dumps({
                "run_id": agent_run.id,
                "conversation_id": conversation_id,
                "mode": mode,
                "web_page_budget": agent_run.web_page_budget,
                "max_depth": agent_run.max_depth,
            }),
        }

        # 运行 Agent 循环
        async for event in agent.run(
            question=question,
            conversation_id=conversation_id,
            chat_history=chat_history,
            context=run_context,
        ):
            evt_type = event.get("event", "")
            data = event.get("data", "")

            if evt_type == "token":
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

            elif evt_type == "error":
                # 错误事件直接转发
                run_error_message = str(data.get("message", "Agent 执行失败")) if isinstance(data, dict) else str(data)
                yield {"event": "error", "data": json.dumps(data)}
                # 错误发生后仍尝试保存已有内容

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
            conversation_memory.update_summary(db, conversation_id)

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
            yield {
                "event": "done",
                "data": json.dumps({
                    "citations": [],
                    "conversation_id": conversation_id,
                    "message_id": "",
                    "run_id": agent_run.id,
                }),
            }
            agent_run.status = "failed" if run_error_message else ("cancelled" if cancellation_event.is_set() else "completed")
            agent_run.error_message = run_error_message or None
            agent_run.web_pages_used = run_context.web_pages_used
            agent_run.completed_at = datetime.now(timezone.utc)
            db.commit()

    except Exception as e:
        logger.exception("Agent generation failed")
        agent_run.status = "failed"
        agent_run.error_message = str(e)
        agent_run.web_pages_used = run_context.web_pages_used
        agent_run.completed_at = datetime.now(timezone.utc)
        db.commit()
        yield {
            "event": "error",
            "data": json.dumps({"message": f"Agent 生成失败: {str(e)}"}),
        }
    finally:
        # 清理取消标志
        if conversation_id and conversation_id in _cancellation_flags:
            del _cancellation_flags[conversation_id]


@router.post("/chat/cancel")
async def cancel_chat(request: Request):
    """
    取消正在进行的对话生成。

    Request body (JSON):
        - conversation_id: str  要取消的对话 ID

    Returns:
        取消确认
    """
    body = await request.json()
    conversation_id = body.get("conversation_id", "")

    if conversation_id and conversation_id in _cancellation_flags:
        _cancellation_flags[conversation_id].set()
        return {"status": "cancelled", "conversation_id": conversation_id}
    return {"status": "not_found", "message": "没有正在进行的生成或对话 ID 无效"}


@router.get("/chat/history")
async def get_chat_history(db: Session = Depends(get_db)):
    """
    获取对话历史列表（按更新时间倒序）。

    Returns:
        conversations 列表和总数
    """
    conversations = (
        db.query(Conversation)
        .order_by(Conversation.updated_at.desc())
        .limit(50)
        .all()
    )

    result = []
    for conv in conversations:
        msg_count = db.query(Message).filter(Message.conversation_id == conv.id).count()
        result.append({
            "id": conv.id,
            "title": conv.title,
            "model_provider": conv.model_provider,
            "model_name": conv.model_name,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
            "message_count": msg_count,
        })

    return {"conversations": result, "total": len(result)}


@router.get("/chat/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, db: Session = Depends(get_db)):
    """
    获取指定对话的完整消息历史。

    Args:
        conversation_id: 对话 ID

    Returns:
        对话详情（含所有消息和引用）

    Raises:
        HTTPException 404: 对话不存在
    """
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .all()
    )

    return {
        "id": conv.id,
        "title": conv.title,
        "model_provider": conv.model_provider,
        "model_name": conv.model_name,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "citations": json.loads(m.citations_json) if m.citations_json else [],
                "token_count": m.token_count,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }
