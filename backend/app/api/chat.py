# Personal RAG - 聊天 API (SSE 流式)
"""
聊天 API 模块

提供基于 SSE 的流式 RAG 问答接口，整合检索、生成和引用解析。
包含查询、对话历史管理和取消生成功能。

支持两种模式：
- Agent 模式 (agent_enabled=True): LLM 自主决策检索策略，支持多轮工具调用
- 经典 RAG 模式 (agent_enabled=False): 固定检索→生成流水线
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
from app.db.models import Conversation, Message
from app.services.retriever import retriever
from app.services.generator import generator

logger = logging.getLogger(__name__)
router = APIRouter()

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
        - top_k: int  检索分块数 (默认 4)

    SSE events (经典模式):
        - event: token    data: {"text": "..."}
        - event: citation data: {"index": N}
        - event: done     data: {"citations": [...], "conversation_id": "...", "message_id": "..."}
        - event: error    data: {"message": "..."}

    SSE events (Agent 模式，额外):
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
    top_k = body.get("top_k", settings.final_top_k)

    # ── 创建或获取对话 ──────────────────────────────────────
    if conversation_id:
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    else:
        conv = None
    # 创建新对话
    if not conv:
        conv = Conversation(
            id=str(uuid.uuid4()),
            title=question[:80],
            model_provider=settings.llm_provider,
            model_name=settings.ollama_llm_model,
            embedding_provider=settings.embedding_provider,
            embedding_model=settings.ollama_embedding_model,
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

    # ── 根据配置选择模式 ──────────────────────────────────────
    if settings.agent_enabled:
        stream = _agent_event_generator(question, conversation_id, db, conv)
    else:
        stream = _classic_event_generator(question, top_k, conversation_id, db, conv)

    return EventSourceResponse(stream)


async def _classic_event_generator(
    question: str,
    top_k: int,
    conversation_id: str,
    db: Session,
    conv: Conversation,
):
    """
    经典 RAG 模式事件生成器。

    固定流水线：embed → 检索 → 拼 prompt → 生成。
    保持与 v0.1 版本完全兼容。
    """
    retrieved_chunks = []
    used_indices = []

    try:
        # Step 1: 检索
        yield {"event": "token", "data": json.dumps({"text": ""})}  # 初始化连接
        retrieved_chunks = await retriever.retrieve(question, db, top_k=top_k)

        if not retrieved_chunks:
            yield {
                "event": "token",
                "data": json.dumps({"text": "未在已上传文档中找到相关信息。请尝试上传相关文档后重试。"}),
            }
            yield {
                "event": "done",
                "data": json.dumps({
                    "citations": [],
                    "conversation_id": conversation_id,
                    "message_id": "",
                }),
            }
            return

        # Step 2 & 3: 流式生成 + 引用解析
        full_content = ""

        async for event in generator.generate_stream(
            question=question,
            retrieved_chunks=retrieved_chunks,
        ):
            # 检查取消标志
            if conversation_id and conversation_id in _cancellation_flags:
                if _cancellation_flags[conversation_id].is_set():
                    full_content += " [生成已取消]"
                    break

            if event["type"] == "token":
                full_content += event["text"]
                yield {"event": "token", "data": json.dumps({"text": event["text"]})}
            elif event["type"] == "citation":
                index = event["index"]
                if index not in used_indices:
                    used_indices.append(index)
                yield {"event": "citation", "data": json.dumps({"index": index})}

        # Step 4: 构建引用元数据
        citations = generator.get_citations_for_chunks(retrieved_chunks, used_indices)

        # Step 5: 保存 AI 消息
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
        db.commit()

        # Step 6: 发送完成事件
        yield {
            "event": "done",
            "data": json.dumps({
                "citations": citations,
                "conversation_id": conversation_id,
                "message_id": ai_msg.id,
            }, ensure_ascii=False),
        }

    except Exception as e:
        logger.exception("Classic RAG generation failed")
        yield {
            "event": "error",
            "data": json.dumps({"message": f"生成失败: {str(e)}"}),
        }
    finally:
        # 清理取消标志
        if conversation_id and conversation_id in _cancellation_flags:
            del _cancellation_flags[conversation_id]


async def _agent_event_generator(
    question: str,
    conversation_id: str,
    db: Session,
    conv: Conversation,
):
    """
    Agent 模式事件生成器。

    LLM 自主决策：何时检索、检索什么、是否需要多轮检索。
    通过 tool_call/tool_result 事件向前端展示思考过程。
    """
    from app.agent.loop import AgentLoop
    from app.agent.builtin_tools import set_db_context
    from app.services.generator import generator as gen_service

    # 设置当前请求的数据库上下文（供内置工具使用）
    set_db_context(db)

    # 创建 LLM provider
    llm_provider = await gen_service._get_provider()

    # 创建 Agent 循环
    agent = AgentLoop(provider=llm_provider)

    used_indices: list[int] = []
    full_content = ""

    try:
        # 初始化连接
        yield {"event": "token", "data": json.dumps({"text": ""})}

        # 运行 Agent 循环
        async for event in agent.run(
            question=question,
            conversation_id=conversation_id,
        ):
            evt_type = event.get("event", "")
            data = event.get("data", "")

            if evt_type == "token":
                # 文本 token（来自最终回答的流式输出）
                # AgentLoop 的 token data 是裸字符串，包装为前端期望的格式
                token_text = data if isinstance(data, str) else data.get("text", "")
                full_content += token_text
                yield {"event": "token", "data": json.dumps({"text": token_text})}
                continue

            elif evt_type == "citation":
                # 引用标记 [N]
                idx = data.get("index", 0) if isinstance(data, dict) else data
                if isinstance(idx, int) and idx not in used_indices:
                    used_indices.append(idx)

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
            # Agent 模式下引用元数据为简化版（多轮检索难以精确追踪来源）
            citations = [
                {"index": idx, "document_id": "", "chunk_id": "",
                 "snippet": f"来源 [{idx}]", "filename": "", "source_type": "text"}
                for idx in sorted(used_indices)
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
            db.commit()

            # 发送完成事件
            yield {
                "event": "done",
                "data": json.dumps({
                    "citations": citations,
                    "conversation_id": conversation_id,
                    "message_id": ai_msg.id,
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
                }),
            }

    except Exception as e:
        logger.exception("Agent generation failed")
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
