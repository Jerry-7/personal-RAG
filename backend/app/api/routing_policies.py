"""Read, activate, and roll back versioned complexity routing policies."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import (
    AgentRun,
    AgentRunFeedback,
    GoalNode,
    RoutingPolicyVersion,
    ToolExecution,
)
from app.schemas.routing_policy import (
    RoutingPolicyCreate,
    RoutingPolicyRollback,
    RoutingPolicySimulation,
)
from app.services.routing_policy import (
    RoutingPolicyConflict,
    create_routing_policy,
    get_active_routing_policy,
    list_routing_policies,
    rollback_routing_policy,
    serialize_policy,
)
from app.services.routing_policy_evaluation import build_routing_policy_evaluation


router = APIRouter()


def _load_routing_evidence(db: Session, limit: int):
    runs = db.query(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit).all()
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
    return runs, goals, tools, feedback


@router.get("/routing-policies")
async def get_routing_policies(
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return list_routing_policies(db, limit=limit)


@router.get("/routing-policies/evaluation")
async def get_routing_policy_evaluation(
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    runs, goals, tools, feedback = _load_routing_evidence(db, limit)
    active = get_active_routing_policy(db)
    policies = (
        db.query(RoutingPolicyVersion)
        .order_by(RoutingPolicyVersion.version.desc())
        .limit(100)
        .all()
    )
    return build_routing_policy_evaluation(
        runs,
        goals,
        tools,
        feedback,
        current_policy=active,
        policy_rows=policies,
    )


@router.get("/routing-policies/simulation")
async def simulate_routing_policy(
    standard_min_score: int = Query(..., ge=1, le=9),
    expert_min_score: int = Query(..., ge=2, le=10),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    if standard_min_score >= expert_min_score:
        raise HTTPException(
            status_code=422,
            detail="standard_min_score must be lower than expert_min_score",
        )
    payload = RoutingPolicySimulation(
        standard_min_score=standard_min_score,
        expert_min_score=expert_min_score,
    )
    runs, goals, tools, feedback = _load_routing_evidence(db, limit)
    active = get_active_routing_policy(db)
    policies = (
        db.query(RoutingPolicyVersion)
        .order_by(RoutingPolicyVersion.version.desc())
        .limit(100)
        .all()
    )
    return build_routing_policy_evaluation(
        runs,
        goals,
        tools,
        feedback,
        current_policy=active,
        policy_rows=policies,
        candidate_standard_min_score=payload.standard_min_score,
        candidate_expert_min_score=payload.expert_min_score,
    )["simulation"]


@router.post("/routing-policies", status_code=status.HTTP_201_CREATED)
async def activate_routing_policy(
    payload: RoutingPolicyCreate,
    db: Session = Depends(get_db),
):
    try:
        policy = create_routing_policy(db, **payload.model_dump())
    except RoutingPolicyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return serialize_policy(policy)


@router.post("/routing-policies/{version}/rollback", status_code=status.HTTP_201_CREATED)
async def rollback_to_routing_policy(
    version: int,
    payload: RoutingPolicyRollback,
    db: Session = Depends(get_db),
):
    try:
        policy = rollback_routing_policy(
            db,
            target_version=version,
            **payload.model_dump(),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RoutingPolicyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return serialize_policy(policy)
