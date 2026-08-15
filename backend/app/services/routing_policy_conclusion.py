"""Transactional human conclusions for guarded routing policy experiments."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import RoutingPolicyConclusion, RoutingPolicyVersion
from app.services.routing_policy import (
    RoutingPolicyConflict,
    get_active_routing_policy,
    rollback_routing_policy,
)


class RoutingPolicyConclusionConflict(ValueError):
    """Raised when experiment evidence does not permit the requested conclusion."""


def serialize_policy_conclusion(
    conclusion: RoutingPolicyConclusion,
) -> dict[str, Any]:
    created_at: datetime | None = conclusion.created_at
    return {
        "id": conclusion.id,
        "policy_version": conclusion.policy_version,
        "baseline_version": conclusion.baseline_version,
        "decision": conclusion.decision,
        "resulting_policy_version": conclusion.resulting_policy_version,
        "evidence": json.loads(conclusion.evidence_json),
        "note": conclusion.note,
        "created_at": created_at.isoformat() if created_at is not None else None,
    }


def conclude_routing_policy_experiment(
    db: Session,
    *,
    policy_version: int,
    decision: Literal["keep", "rollback"],
    expected_active_version: int,
    experiment: dict[str, Any],
    note: str | None = None,
) -> tuple[RoutingPolicyConclusion, RoutingPolicyVersion | None]:
    active = get_active_routing_policy(db)
    if active.version != expected_active_version or active.version != policy_version:
        raise RoutingPolicyConclusionConflict(
            f"routing policy v{policy_version} is no longer active; "
            f"active version is {active.version}"
        )
    policy = db.get(RoutingPolicyVersion, policy_version)
    if policy is None:
        raise LookupError(f"routing policy version {policy_version} does not exist")
    existing = db.query(RoutingPolicyConclusion.id).filter(
        RoutingPolicyConclusion.policy_version == policy_version
    ).first()
    if existing is not None:
        raise RoutingPolicyConclusionConflict(
            f"routing policy v{policy_version} already has a conclusion"
        )
    if experiment.get("current_policy_version") != policy_version:
        raise RoutingPolicyConclusionConflict("experiment evidence is stale")
    status = experiment.get("status")
    recommendation = experiment.get("recommendation")
    if status not in {"ready", "operational_alert"}:
        raise RoutingPolicyConclusionConflict(
            f"experiment is not ready for conclusion: {status}"
        )
    if status == "operational_alert" and decision != "rollback":
        raise RoutingPolicyConclusionConflict(
            "operational alert only permits rollback"
        )
    normalized_note = note.strip() if note and note.strip() else None
    if recommendation in {"keep", "rollback"} and decision != recommendation:
        if normalized_note is None:
            raise RoutingPolicyConclusionConflict(
                "a note is required when overriding the guarded recommendation"
            )
    if recommendation == "review" and normalized_note is None:
        raise RoutingPolicyConclusionConflict(
            "a note is required for a manually reviewed conclusion"
        )
    baseline_version = experiment.get("baseline_policy_version")
    if baseline_version is None:
        raise RoutingPolicyConclusionConflict("experiment has no baseline policy")

    resulting_policy = None
    if decision == "rollback":
        try:
            resulting_policy = rollback_routing_policy(
                db,
                target_version=baseline_version,
                expected_active_version=policy_version,
                note=normalized_note or f"试验 v{policy_version} 结论回滚",
                commit=False,
            )
        except RoutingPolicyConflict as exc:
            raise RoutingPolicyConclusionConflict(str(exc)) from exc

    conclusion = RoutingPolicyConclusion(
        policy_version=policy_version,
        baseline_version=baseline_version,
        decision=decision,
        resulting_policy_version=(
            resulting_policy.version if resulting_policy is not None else None
        ),
        evidence_json=json.dumps(experiment, ensure_ascii=False, sort_keys=True),
        note=normalized_note,
    )
    db.add(conclusion)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise RoutingPolicyConclusionConflict(
            "routing policy conclusion conflicted with another update"
        ) from exc
    db.refresh(conclusion)
    if resulting_policy is not None:
        db.refresh(resulting_policy)
    return conclusion, resulting_policy
