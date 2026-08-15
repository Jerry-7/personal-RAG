import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import AgentRun, GoalNode, ResearchRunSnapshot, RunEvent, ToolExecution, WebSnapshot
from app.services.goal_runtime import serialize_event, serialize_goal
from app.services.web_search import search_provider

router = APIRouter()


@router.get("/research-runs/{run_id}")
async def get_research_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="研究运行不存在")
    has_active_run = db.query(AgentRun.id).filter(
        AgentRun.conversation_id == run.conversation_id,
        AgentRun.status == "running",
    ).first() is not None
    executions = db.query(ToolExecution).filter(ToolExecution.run_id == run_id).order_by(ToolExecution.created_at).all()
    goals = db.query(GoalNode).filter(GoalNode.run_id == run_id).order_by(GoalNode.sequence).all()
    events = db.query(RunEvent).filter(RunEvent.run_id == run_id).order_by(RunEvent.sequence).all()
    snapshots = (
        db.query(WebSnapshot).join(ResearchRunSnapshot, ResearchRunSnapshot.snapshot_id == WebSnapshot.id)
        .filter(ResearchRunSnapshot.run_id == run_id).all()
    )
    return {
        "id": run.id,
        "retry_of_run_id": run.retry_of_run_id,
        "retryable": (
            run.status in {"failed", "cancelled", "interrupted"}
            and not has_active_run
        ),
        "conversation_id": run.conversation_id,
        "mode": run.mode,
        "routing": {
            "agent_profile": run.agent_profile,
            "tier": run.route_tier,
            "route": run.route_name,
            "score": run.route_score,
            "reasons": json.loads(run.route_reasons_json or "[]"),
            "requires_decomposition": run.route_requires_decomposition,
        },
        "status": run.status,
        "web_page_budget": run.web_page_budget,
        "web_pages_used": run.web_pages_used,
        "max_depth": run.max_depth,
        "error_message": run.error_message,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "goals": [serialize_goal(item) for item in goals],
        "events": [serialize_event(item) for item in events],
        "tools": [{
            "id": item.id,
            "node_id": item.node_id,
            "name": item.tool_name,
            "arguments": json.loads(item.arguments_json or "{}"),
            "status": item.status,
            "duration_ms": item.duration_ms,
            "error_message": item.error_message,
        } for item in executions],
        "snapshots": [{
            "id": item.id,
            "url": item.canonical_url,
            "title": item.title,
            "fetched_at": item.fetched_at,
            "content_hash": item.content_hash,
        } for item in snapshots],
    }


@router.get("/web-search/health")
async def web_search_health():
    try:
        await search_provider.search("searxng", max_results=1)
        return {"status": "healthy", "provider": "searxng", "url": getattr(search_provider, "base_url", "")}
    except Exception as exc:
        return {
            "status": "unavailable", "provider": "searxng",
            "url": getattr(search_provider, "base_url", ""), "error": str(exc),
        }
