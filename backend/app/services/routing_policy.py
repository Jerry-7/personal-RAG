"""Persistence and activation rules for versioned complexity routing policies."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.routing import RoutingPolicy
from app.db.models import RoutingPolicyVersion


DEFAULT_ROUTING_POLICY = RoutingPolicy()


class RoutingPolicyConflict(ValueError):
    """Raised when a policy update is based on a stale active version."""


def get_active_routing_policy(db: Session) -> RoutingPolicy:
    row = (
        db.query(RoutingPolicyVersion)
        .filter(RoutingPolicyVersion.is_active.is_(True))
        .order_by(RoutingPolicyVersion.version.desc())
        .first()
    )
    if row is None:
        return DEFAULT_ROUTING_POLICY
    return RoutingPolicy(
        version=row.version,
        standard_min_score=row.standard_min_score,
        expert_min_score=row.expert_min_score,
    )


def serialize_policy(
    policy: RoutingPolicy | RoutingPolicyVersion,
) -> dict[str, Any]:
    created_at: datetime | None = getattr(policy, "created_at", None)
    return {
        "version": policy.version,
        "standard_min_score": policy.standard_min_score,
        "expert_min_score": policy.expert_min_score,
        "source": getattr(policy, "source", "default"),
        "based_on_version": getattr(policy, "based_on_version", None),
        "note": getattr(policy, "note", None),
        "is_active": getattr(policy, "is_active", True),
        "created_at": created_at.isoformat() if created_at is not None else None,
    }


def list_routing_policies(db: Session, *, limit: int = 50) -> dict[str, Any]:
    active = get_active_routing_policy(db)
    rows = (
        db.query(RoutingPolicyVersion)
        .order_by(RoutingPolicyVersion.version.desc())
        .limit(limit)
        .all()
    )
    return {
        "current": (
            serialize_policy(active)
            if active.version == 0
            else serialize_policy(next(row for row in rows if row.version == active.version))
        ),
        "versions": [serialize_policy(row) for row in rows],
    }


def create_routing_policy(
    db: Session,
    *,
    standard_min_score: int,
    expert_min_score: int,
    expected_active_version: int,
    note: str | None = None,
    source: str = "manual",
    based_on_version: int | None = None,
) -> RoutingPolicyVersion:
    RoutingPolicy(
        standard_min_score=standard_min_score,
        expert_min_score=expert_min_score,
    )
    active = get_active_routing_policy(db)
    if active.version != expected_active_version:
        raise RoutingPolicyConflict(
            f"active policy changed from version {expected_active_version} "
            f"to {active.version}"
        )
    next_version = int(
        db.query(func.coalesce(func.max(RoutingPolicyVersion.version), 0)).scalar()
    ) + 1
    db.query(RoutingPolicyVersion).filter(
        RoutingPolicyVersion.is_active.is_(True)
    ).update({"is_active": False}, synchronize_session=False)
    row = RoutingPolicyVersion(
        version=next_version,
        standard_min_score=standard_min_score,
        expert_min_score=expert_min_score,
        source=source,
        based_on_version=based_on_version,
        note=note.strip() if note and note.strip() else None,
        is_active=True,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        current = get_active_routing_policy(db)
        raise RoutingPolicyConflict(
            f"routing policy changed concurrently; active version is {current.version}"
        ) from exc
    db.refresh(row)
    return row


def rollback_routing_policy(
    db: Session,
    *,
    target_version: int,
    expected_active_version: int,
    note: str | None = None,
) -> RoutingPolicyVersion:
    if target_version == 0:
        target = DEFAULT_ROUTING_POLICY
    else:
        target = db.get(RoutingPolicyVersion, target_version)
        if target is None:
            raise LookupError(f"routing policy version {target_version} does not exist")
    return create_routing_policy(
        db,
        standard_min_score=target.standard_min_score,
        expert_min_score=target.expert_min_score,
        expected_active_version=expected_active_version,
        note=note,
        source="rollback",
        based_on_version=target_version,
    )
