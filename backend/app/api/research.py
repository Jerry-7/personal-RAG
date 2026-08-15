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
    GoalNode,
    ResearchRunSnapshot,
    RunEvent,
    ToolExecution,
    WebSnapshot,
)
from app.services.goal_runtime import serialize_event, serialize_goal
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
    children: Counter[str | None] = Counter(goal.parent_id for goal in goals)
    parents = {goal.id: goal.parent_id for goal in goals}
    max_depth = 0
    for goal in goals:
        depth = 0
        parent_id = goal.parent_id
        visited = {goal.id}
        while parent_id and parent_id not in visited:
            visited.add(parent_id)
            depth += 1
            parent_id = parents.get(parent_id)
        max_depth = max(max_depth, depth)
    return max(children.values(), default=0), max_depth


def _metrics(
    run: AgentRun,
    goals: list[GoalNode],
    tools: list[ToolExecution],
) -> dict[str, Any]:
    goal_statuses = Counter(goal.status for goal in goals)
    return {
        "duration_ms": _duration_ms(run.started_at, run.completed_at),
        "goal_count": len(goals),
        "agent_count": sum(goal.kind == "agent" for goal in goals),
        "goals_completed": goal_statuses["completed"],
        "goals_failed": goal_statuses["failed"],
        "goals_cancelled": goal_statuses["cancelled"],
        "tool_calls_used": len(tools),
        "tool_calls_failed": sum(tool.status == "failed" for tool in tools),
        "tool_duration_ms": sum(tool.duration_ms or 0 for tool in tools),
        "tool_call_budget": sum(
            goal.tool_call_budget for goal in goals if goal.kind == "agent"
        ),
        "web_pages_used": run.web_pages_used,
        "web_page_budget": run.web_page_budget,
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
        "requires_decomposition": run.route_requires_decomposition,
        "max_children": max_children,
        "max_depth": max_depth,
        "tier_preference": run.route_tier_preference,
    }


def _summary(
    run: AgentRun,
    goals: list[GoalNode],
    tools: list[ToolExecution],
    *,
    retry_count: int = 0,
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
        "metrics": _metrics(run, goals, tools),
        "error_message": run.error_message,
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
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
    retry_counts = Counter(
        child.retry_of_run_id
        for child in db.query(AgentRun)
        .filter(AgentRun.retry_of_run_id.in_(run_ids))
        .all()
    ) if run_ids else Counter()
    goals_by_run: dict[str, list[GoalNode]] = {run_id: [] for run_id in run_ids}
    tools_by_run: dict[str, list[ToolExecution]] = {run_id: [] for run_id in run_ids}
    for goal in goals:
        goals_by_run[goal.run_id].append(goal)
    for tool in tools:
        tools_by_run[tool.run_id].append(tool)
    return {
        "runs": [
            _summary(
                run,
                goals_by_run[run.id],
                tools_by_run[run.id],
                retry_count=retry_counts[run.id],
            )
            for run in runs
        ]
    }


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
    return {
        **_summary(run, goals, executions, retry_count=len(retried_by_run_ids)),
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
