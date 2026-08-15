"""Read, activate, and roll back versioned complexity routing policies."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.routing_policy import RoutingPolicyCreate, RoutingPolicyRollback
from app.services.routing_policy import (
    RoutingPolicyConflict,
    create_routing_policy,
    list_routing_policies,
    rollback_routing_policy,
    serialize_policy,
)


router = APIRouter()


@router.get("/routing-policies")
async def get_routing_policies(
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return list_routing_policies(db, limit=limit)


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
