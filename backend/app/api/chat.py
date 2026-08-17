# Personal RAG - 聊天 API (SSE 流式)
"""
聊天 API 模块

提供基于 SSE 的流式 RAG 问答接口，整合检索、生成和引用解析。
包含查询、对话历史管理和取消生成功能。

聊天请求统一由 Agent 执行，支持本地检索、网页研究和多轮工具调用。

执行编排（Agent 路由、目标树、SSE 事件流、消息持久化）已抽到
app/services/chat_execution.py，本模块只保留 HTTP 请求解析与响应包装。
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.db.database import get_db
from app.db.models import Conversation, Message
from app.services.chat_execution import agent_event_generator, chat_run_manager
from app.services.conversation_memory import conversation_memory

router = APIRouter()


def _stream_error(message: str) -> EventSourceResponse:
    async def generate_error():
        yield {"event": "error", "data": json.dumps({"message": message})}

    return EventSourceResponse(generate_error())


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
        - retry_run_id: str|null  失败、中断或取消的运行 ID；提供时复用原问题

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

    retry_run_id = str(body.get("retry_run_id") or "").strip() or None
    if retry_run_id:
        from app.services.run_recovery import resolve_retry_source

        try:
            retry_source = resolve_retry_source(db, retry_run_id)
        except (LookupError, ValueError) as exc:
            return _stream_error(str(exc))
        question = retry_source.user_message.content.strip()
        conversation_id = retry_source.conversation.id
        mode = retry_source.run.mode
        tier_preference = retry_source.run.route_tier_preference
        conv = retry_source.conversation
        user_msg = retry_source.user_message
        chat_history = conversation_memory.get_context_before(
            db,
            conversation_id,
            user_msg,
        )
    else:
        question = str(body.get("question") or "").strip()
        if not question:
            return _stream_error("问题不能为空")

        conversation_id = body.get("conversation_id")
        mode = body.get("mode", "auto")
        if mode not in {"auto", "local", "web"}:
            return _stream_error("mode 必须是 auto、local 或 web")
        tier_preference = body.get("agent_tier", "auto")
        if tier_preference not in {"auto", "fast", "standard", "expert"}:
            return _stream_error("agent_tier 必须是 auto、fast、standard 或 expert")

        # ── 创建或获取对话 ──────────────────────────────────
        if conversation_id:
            conv = db.query(Conversation).filter(
                Conversation.id == conversation_id
            ).first()
        else:
            conv = None
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

        user_msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="user",
            content=question,
        )
        db.add(user_msg)
        db.commit()
        chat_history = conversation_memory.get_context(
            db, conversation_id, exclude_message_id=user_msg.id
        )

    # 初始化取消/暂停运行标志
    chat_run_manager.register(conversation_id)

    # ── 启动 Agent ────────────────────────────────────────────
    stream = agent_event_generator(
        question,
        conversation_id,
        db,
        conv,
        chat_history,
        mode,
        user_msg.id,
        tier_preference=tier_preference,
        retry_of_run_id=retry_run_id,
    )

    return EventSourceResponse(stream)


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
    return chat_run_manager.cancel(conversation_id)


@router.post("/chat/pause")
async def pause_chat(request: Request, db: Session = Depends(get_db)):
    """Pause an active Agent run at its next cooperative boundary."""
    body = await request.json()
    conversation_id = str(body.get("conversation_id") or "")
    return chat_run_manager.pause(db, conversation_id)


@router.post("/chat/resume")
async def resume_chat(request: Request, db: Session = Depends(get_db)):
    """Resume a cooperatively paused Agent run."""
    body = await request.json()
    conversation_id = str(body.get("conversation_id") or "")
    return chat_run_manager.resume(db, conversation_id)


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
