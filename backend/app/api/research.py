"""Persisted Agent-run observability and web-search health APIs."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import (
    AgentRun,
    AgentRunFeedback,
    GoalNode,
    ResearchRunSnapshot,
    RunEvent,
    ToolExecution,
    WebSnapshot,
)
from app.schemas.research import RunFeedbackUpdate
from app.services.goal_runtime import serialize_event, serialize_goal
from app.services.routing_analytics import build_routing_analytics
from app.services.routing_policy import get_active_routing_policy
from app.services.web_search import search_provider

router = APIRouter()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _duration_ms(started_at: datetime | None, completed_at: datetime | None) -> int | None:
    if started_at is None:
        return None
    if completed_at is None:
        completed_at = (
            datetime.now(timezone.utc)
            if started_at.tzinfo is not None
            else datetime.now()
        )
    return max(0, round((completed_at - started_at).total_seconds() * 1000))


def _tree_shape(goals: list[GoalNode]) -> tuple[int, int]:
    primary_agents = sorted(
        (goal for goal in goals if goal.kind == "agent"),
        key=lambda goal: goal.sequence,
    )
    if not primary_agents:
        return 0, 0

    primary_id = primary_agents[0].id
    parents = {goal.id: goal.parent_id for goal in goals}
    descendants: list[GoalNode] = []
    max_depth = 0
    for goal in goals:
        if goal.id == primary_id:
            continue
        depth = 0
        parent_id = goal.parent_id
        visited = {goal.id}
        while parent_id and parent_id not in visited:
            visited.add(parent_id)
            depth += 1
            if parent_id == primary_id:
                descendants.append(goal)
                max_depth = max(max_depth, depth)
                break
            parent_id = parents.get(parent_id)
    descendant_ids = {goal.id for goal in descendants}
    children = Counter(
        goal.parent_id
        for goal in descendants
        if goal.parent_id == primary_id or goal.parent_id in descendant_ids
    )
    return max(children.values(), default=0), max_depth


def _compression_metrics(events: list[RunEvent]) -> dict[str, int | float]:
    compressed_count = 0
    failure_count = 0
    agent_calls = 0
    protected_anchors = 0
    anchor_retries = 0
    original_tokens = 0
    compressed_tokens = 0
    for event in events:
        if event.event_type == "context_compression_failed":
            failure_count += 1
            continue
        if event.event_type != "context_compressed":
            continue
        payload = json.loads(event.payload_json or "{}")
        compressed_count += 1
        agent_calls += max(0, int(payload.get("calls") or 0))
        protected_anchors += max(0, int(payload.get("protected_anchors") or 0))
        anchor_retries += max(0, int(payload.get("anchor_retries") or 0))
        original_tokens += max(0, int(payload.get("original_tokens") or 0))
        compressed_tokens += max(0, int(payload.get("compressed_tokens") or 0))
    tokens_saved = max(0, original_tokens - compressed_tokens)
    compression_ratio = (
        round(tokens_saved * 100 / original_tokens, 1)
        if original_tokens > 0
        else 0.0
    )
    return {
        "context_compressions": compressed_count,
        "context_compression_failures": failure_count,
        "context_compression_calls": agent_calls,
        "context_protected_anchors": protected_anchors,
        "context_anchor_retries": anchor_retries,
        "context_original_tokens": original_tokens,
        "context_compressed_tokens": compressed_tokens,
        "context_tokens_saved": tokens_saved,
        "context_compression_ratio": compression_ratio,
    }


def _metrics(
    run: AgentRun,
    goals: list[GoalNode],
    tools: list[ToolExecution],
    events: list[RunEvent] | None = None,
) -> dict[str, Any]:
    goal_statuses = Counter(goal.status for goal in goals)
    terminal_goals = sum(
        goal_statuses[status] for status in ("completed", "failed", "cancelled")
    )
    progress_percent = round(terminal_goals * 100 / len(goals)) if goals else 0
    return {
        "duration_ms": _duration_ms(run.started_at, run.completed_at),
        "goal_count": len(goals),
        "agent_count": sum(goal.kind == "agent" for goal in goals),
        "goals_completed": goal_statuses["completed"],
        "goals_failed": goal_statuses["failed"],
        "goals_cancelled": goal_statuses["cancelled"],
        "goals_pending": goal_statuses["pending"],
        "goals_running": goal_statuses["running"],
        "goal_retry_attempts": sum(max(0, goal.attempt - 1) for goal in goals),
        "progress_percent": progress_percent,
        "tool_calls_used": len(tools),
        "tool_calls_failed": sum(tool.status == "failed" for tool in tools),
        "tool_duration_ms": sum(tool.duration_ms or 0 for tool in tools),
        "tool_call_budget": sum(
            goal.tool_call_budget for goal in goals if goal.kind == "agent"
        ),
        "web_pages_used": run.web_pages_used,
        "web_page_budget": run.web_page_budget,
        **_compression_metrics(events or []),
    }


def _routing(run: AgentRun, goals: list[GoalNode]) -> dict[str, Any]:
    agent_goals = sorted(
        (goal for goal in goals if goal.kind == "agent"),
        key=lambda goal: goal.sequence,
    )
    max_children, max_depth = _tree_shape(goals)
    return {
        "agent_profile": run.agent_profile,
        "model_provider": run.model_provider,
        "model_name": run.model_name,
        "tool_call_budget": agent_goals[0].tool_call_budget if agent_goals else 0,
        "tier": run.route_tier,
        "route": run.route_name,
        "score": run.route_score,
        "reasons": json.loads(run.route_reasons_json or "[]"),
        "decision_source": getattr(run, "route_decision_source", "heuristic"),
        "confidence": getattr(run, "route_confidence", 1.0),
        "classifier_model": getattr(run, "route_classifier_model", ""),
        "classifier_original_tokens": getattr(
            run, "route_classifier_original_tokens", 0
        ),
        "classifier_compressed_tokens": getattr(
            run, "route_classifier_compressed_tokens", 0
        ),
        "classifier_calls": getattr(run, "route_classifier_calls", 0),
        "requires_decomposition": run.route_requires_decomposition,
        "max_children": run.route_max_children,
        "max_depth": run.route_max_depth,
        "observed_max_children": max_children,
        "observed_max_depth": max_depth,
        "tier_preference": run.route_tier_preference,
        "policy_version": run.route_policy_version,
    }


def _feedback(value: AgentRunFeedback | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "rating": value.rating,
        "reason": value.reason,
        "created_at": _iso(value.created_at),
        "updated_at": _iso(value.updated_at),
    }


def _summary(
    run: AgentRun,
    goals: list[GoalNode],
    tools: list[ToolExecution],
    events: list[RunEvent] | None = None,
    *,
    retry_count: int = 0,
    feedback: AgentRunFeedback | None = None,
) -> dict[str, Any]:
    return {
        "id": run.id,
        "conversation_id": run.conversation_id,
        "retry_of_run_id": run.retry_of_run_id,
        "retry_count": retry_count,
        "mode": run.mode,
        "status": run.status,
        "model_provider": run.model_provider,
        "model_name": run.model_name,
        "routing": _routing(run, goals),
        "metrics": _metrics(run, goals, tools, events),
        "error_message": run.error_message,
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
        "feedback": _feedback(feedback),
    }


@router.get("/research-runs")
async def list_research_runs(
    conversation_id: str,
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    runs = (
        db.query(AgentRun)
        .filter(AgentRun.conversation_id == conversation_id)
        .order_by(AgentRun.started_at.desc())
        .limit(limit)
        .all()
    )
    run_ids = [run.id for run in runs]
    goals = (
        db.query(GoalNode)
        .filter(GoalNode.run_id.in_(run_ids))
        .order_by(GoalNode.sequence)
        .all()
        if run_ids else []
    )
    tools = (
        db.query(ToolExecution)
        .filter(ToolExecution.run_id.in_(run_ids))
        .order_by(ToolExecution.created_at)
        .all()
        if run_ids else []
    )
    events = (
        db.query(RunEvent)
        .filter(
            RunEvent.run_id.in_(run_ids),
            RunEvent.event_type.in_((
                "context_compressed",
                "context_compression_failed",
            )),
        )
        .order_by(RunEvent.sequence)
        .all()
        if run_ids else []
    )
    retry_counts = Counter(
        child.retry_of_run_id
        for child in db.query(AgentRun)
        .filter(AgentRun.retry_of_run_id.in_(run_ids))
        .all()
    ) if run_ids else Counter()
    feedback_by_run = {
        item.run_id: item
        for item in db.query(AgentRunFeedback)
        .filter(AgentRunFeedback.run_id.in_(run_ids))
        .all()
    } if run_ids else {}
    goals_by_run: dict[str, list[GoalNode]] = {run_id: [] for run_id in run_ids}
    tools_by_run: dict[str, list[ToolExecution]] = {run_id: [] for run_id in run_ids}
    events_by_run: dict[str, list[RunEvent]] = {run_id: [] for run_id in run_ids}
    for goal in goals:
        goals_by_run[goal.run_id].append(goal)
    for tool in tools:
        tools_by_run[tool.run_id].append(tool)
    for event in events:
        events_by_run[event.run_id].append(event)
    return {
        "runs": [
            _summary(
                run,
                goals_by_run[run.id],
                tools_by_run[run.id],
                events_by_run[run.id],
                retry_count=retry_counts[run.id],
                feedback=feedback_by_run.get(run.id),
            )
            for run in runs
        ]
    }


@router.get("/research-runs/analytics")
async def get_routing_analytics(
    conversation_id: str | None = None,
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(AgentRun)
    if conversation_id:
        query = query.filter(AgentRun.conversation_id == conversation_id)
    runs = query.order_by(AgentRun.started_at.desc()).limit(limit).all()
    run_ids = [run.id for run in runs]
    goals = (
        db.query(GoalNode)
        .filter(GoalNode.run_id.in_(run_ids))
        .order_by(GoalNode.sequence)
        .all()
        if run_ids else []
    )
    tools = (
        db.query(ToolExecution)
        .filter(ToolExecution.run_id.in_(run_ids))
        .order_by(ToolExecution.created_at)
        .all()
        if run_ids else []
    )
    feedback = (
        db.query(AgentRunFeedback)
        .filter(AgentRunFeedback.run_id.in_(run_ids))
        .all()
        if run_ids else []
    )
    active_policy = get_active_routing_policy(db)
    return build_routing_analytics(
        runs,
        goals,
        tools,
        feedback,
        active_policy_version=active_policy.version,
    )


@router.get("/research-runs/{run_id}")
async def get_research_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="研究运行不存在")
    has_active_run = db.query(AgentRun.id).filter(
        AgentRun.conversation_id == run.conversation_id,
        AgentRun.status.in_(("running", "paused")),
    ).first() is not None
    goals = (
        db.query(GoalNode)
        .filter(GoalNode.run_id == run_id)
        .order_by(GoalNode.sequence)
        .all()
    )
    executions = (
        db.query(ToolExecution)
        .filter(ToolExecution.run_id == run_id)
        .order_by(ToolExecution.created_at)
        .all()
    )
    events = (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run_id)
        .order_by(RunEvent.sequence)
        .all()
    )
    snapshots = (
        db.query(WebSnapshot)
        .join(ResearchRunSnapshot, ResearchRunSnapshot.snapshot_id == WebSnapshot.id)
        .filter(ResearchRunSnapshot.run_id == run_id)
        .all()
    )
    retried_by_run_ids = [
        item.id
        for item in db.query(AgentRun.id)
        .filter(AgentRun.retry_of_run_id == run_id)
        .order_by(AgentRun.started_at)
        .all()
    ]
    feedback = db.get(AgentRunFeedback, run_id)
    return {
        **_summary(
            run,
            goals,
            executions,
            events,
            retry_count=len(retried_by_run_ids),
            feedback=feedback,
        ),
        "retryable": (
            run.status in {"failed", "cancelled", "interrupted"}
            and not has_active_run
        ),
        "retried_by_run_ids": retried_by_run_ids,
        "web_page_budget": run.web_page_budget,
        "web_pages_used": run.web_pages_used,
        "max_depth": run.max_depth,
        "goals": [serialize_goal(item) for item in goals],
        "events": [serialize_event(item) for item in events],
        "tools": [{
            "id": item.id,
            "node_id": item.node_id,
            "iteration": item.iteration,
            "name": item.tool_name,
            "arguments": json.loads(item.arguments_json or "{}"),
            "status": item.status,
            "duration_ms": item.duration_ms,
            "error_message": item.error_message,
            "created_at": _iso(item.created_at),
        } for item in executions],
        "snapshots": [{
            "id": item.id,
            "url": item.canonical_url,
            "title": item.title,
            "fetched_at": _iso(item.fetched_at),
            "content_hash": item.content_hash,
        } for item in snapshots],
    }


@router.put("/research-runs/{run_id}/feedback")
async def update_run_feedback(
    run_id: str,
    payload: RunFeedbackUpdate,
    db: Session = Depends(get_db),
):
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="研究运行不存在")
    if run.status != "completed":
        raise HTTPException(status_code=409, detail="只能评价已完成的运行")
    feedback = db.get(AgentRunFeedback, run_id)
    if feedback is None:
        feedback = AgentRunFeedback(run_id=run_id, rating=payload.rating)
        db.add(feedback)
    feedback.rating = payload.rating
    feedback.reason = payload.reason if payload.rating == "negative" else None
    db.commit()
    db.refresh(feedback)
    return _feedback(feedback)


@router.delete("/research-runs/{run_id}/feedback")
async def delete_run_feedback(run_id: str, db: Session = Depends(get_db)):
    if db.get(AgentRun, run_id) is None:
        raise HTTPException(status_code=404, detail="研究运行不存在")
    feedback = db.get(AgentRunFeedback, run_id)
    if feedback is not None:
        db.delete(feedback)
        db.commit()
    return {"status": "removed"}


@router.get("/web-search/health")
async def web_search_health():
    try:
        await search_provider.search("searxng", max_results=1)
        return {
            "status": "healthy",
            "provider": "searxng",
            "url": getattr(search_provider, "base_url", ""),
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "provider": "searxng",
            "url": getattr(search_provider, "base_url", ""),
            "error": str(exc),
        }
