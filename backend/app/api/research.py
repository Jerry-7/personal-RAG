import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import AgentRun, ResearchRunSnapshot, ToolExecution, WebSnapshot
from app.services.web_search import search_provider

router = APIRouter()


@router.get("/research-runs/{run_id}")
async def get_research_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="研究运行不存在")
    executions = db.query(ToolExecution).filter(ToolExecution.run_id == run_id).order_by(ToolExecution.created_at).all()
    snapshots = (
        db.query(WebSnapshot).join(ResearchRunSnapshot, ResearchRunSnapshot.snapshot_id == WebSnapshot.id)
        .filter(ResearchRunSnapshot.run_id == run_id).all()
    )
    return {
        "id": run.id,
        "conversation_id": run.conversation_id,
        "mode": run.mode,
        "status": run.status,
        "web_page_budget": run.web_page_budget,
        "web_pages_used": run.web_pages_used,
        "max_depth": run.max_depth,
        "error_message": run.error_message,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "tools": [{
            "id": item.id,
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
