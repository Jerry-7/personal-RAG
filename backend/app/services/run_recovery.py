"""Reconcile interrupted Agent runs and validate durable retry requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import AgentRun, Conversation, GoalNode, Message
from app.services.goal_runtime import GoalRuntime


INTERRUPTED_MESSAGE = "应用进程在运行完成前中断"
RETRYABLE_RUN_STATUSES = frozenset({"failed", "cancelled", "interrupted"})


@dataclass(frozen=True)
class RetrySource:
    run: AgentRun
    conversation: Conversation
    user_message: Message


def resolve_retry_source(db: Session, run_id: str) -> RetrySource:
    run = db.get(AgentRun, run_id)
    if run is None:
        raise LookupError("研究运行不存在")
    if run.status not in RETRYABLE_RUN_STATUSES:
        raise ValueError(f"状态为 {run.status} 的运行不可重试")
    active_run = (
        db.query(AgentRun)
        .filter(
            AgentRun.conversation_id == run.conversation_id,
            AgentRun.status.in_(("running", "paused")),
        )
        .first()
    )
    if active_run is not None:
        raise ValueError("该对话已有正在执行的运行")
    if not run.user_message_id:
        raise ValueError("原运行缺少用户消息，无法重试")

    conversation = db.get(Conversation, run.conversation_id)
    user_message = db.get(Message, run.user_message_id)
    if conversation is None or user_message is None or user_message.role != "user":
        raise ValueError("原运行上下文不完整，无法重试")
    if user_message.conversation_id != conversation.id:
        raise ValueError("原运行消息不属于目标对话")
    return RetrySource(run=run, conversation=conversation, user_message=user_message)


def recover_interrupted_agent_runs(db: Session) -> int:
    """Mark runs left active by a stopped process as durably interrupted."""
    runs = db.query(AgentRun).filter(
        AgentRun.status.in_(("running", "paused"))
    ).all()
    for run in runs:
        runtime = GoalRuntime(db, run.id)
        goals = (
            db.query(GoalNode)
            .filter(GoalNode.run_id == run.id)
            .order_by(GoalNode.sequence.desc())
            .all()
        )
        for goal in goals:
            if goal.status == "running":
                runtime.transition(
                    goal,
                    "failed",
                    error_message=INTERRUPTED_MESSAGE,
                )
            elif goal.status == "pending":
                runtime.transition(
                    goal,
                    "cancelled",
                    error_message=INTERRUPTED_MESSAGE,
                )
        run.status = "interrupted"
        run.error_message = INTERRUPTED_MESSAGE
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
    return len(runs)
