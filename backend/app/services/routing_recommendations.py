"""Conservative routing recommendations derived from aggregated run evidence."""

from __future__ import annotations

from typing import Any


MIN_TERMINAL_RUNS = 10
MIN_RATED_RUNS = 5
MIN_TOOL_CALLS = 5

QUALITY_ACTIONS = frozenset({
    "upgrade_tier",
    "review_planning",
    "investigate_quality",
    "optimize_latency",
    "simplify_route",
    "downgrade_tier",
    "keep_policy",
})


def _confidence(group: dict[str, Any], action: str) -> str:
    terminal = int(group["terminal_run_count"])
    rated = int(group["rated_run_count"])
    if action in QUALITY_ACTIONS:
        if terminal >= 30 and rated >= 15:
            return "high"
        if terminal >= 20 and rated >= 10:
            return "medium"
        return "low"
    if terminal >= 30:
        return "high"
    if terminal >= 20:
        return "medium"
    return "low"


def _dominant_negative_reason(group: dict[str, Any]) -> str | None:
    reasons = group.get("negative_reason_counts") or {}
    if not reasons:
        return None
    reason, count = max(reasons.items(), key=lambda item: item[1])
    negative_count = int(group["negative_feedback_count"])
    return reason if count >= 2 and count * 2 >= negative_count else None


def _recommend_group(group: dict[str, Any]) -> dict[str, Any] | None:
    operational_ready = group["terminal_run_count"] >= MIN_TERMINAL_RUNS
    feedback_ready = group["rated_run_count"] >= MIN_RATED_RUNS
    reasons: list[str] = []
    action: str | None = None

    if operational_ready:
        if group["operational_success_rate"] < 80:
            reasons.append("low_operational_success")
        if (
            group["tool_call_count"] >= MIN_TOOL_CALLS
            and group["tool_failure_rate"] >= 25
        ):
            reasons.append("high_tool_failure")
        if reasons:
            action = "investigate_reliability"

    if action is None and feedback_ready and group["user_satisfaction_rate"] < 60:
        reasons.append("low_user_satisfaction")
        dominant_reason = _dominant_negative_reason(group)
        if dominant_reason:
            reasons.append(dominant_reason)
        if dominant_reason == "too_slow":
            action = "optimize_latency"
        elif dominant_reason == "over_complicated":
            action = "simplify_route"
        elif group["tier"] != "expert":
            action = "upgrade_tier"
        elif group["route"] == "supervisor":
            action = "review_planning"
        else:
            action = "investigate_quality"

    if (
        action is None
        and operational_ready
        and feedback_ready
        and group["tier"] != "fast"
        and group["operational_success_rate"] >= 95
        and group["user_satisfaction_rate"] >= 90
        and group["tool_budget_utilization"] < 40
    ):
        action = "downgrade_tier"
        reasons.append("high_quality_low_utilization")

    if action is None and operational_ready and feedback_ready:
        action = "keep_policy"
        reasons.append("stable_policy")
    if action is None:
        return None

    return {
        "policy_version": group.get("policy_version", 0),
        "tier": group["tier"],
        "route": group["route"],
        "planning_source": group["planning_source"],
        "action": action,
        "confidence": _confidence(group, action),
        "reason_codes": reasons,
        "evidence": {
            "terminal_run_count": group["terminal_run_count"],
            "rated_run_count": group["rated_run_count"],
            "operational_success_rate": group["operational_success_rate"],
            "user_satisfaction_rate": group["user_satisfaction_rate"],
            "tool_failure_rate": group["tool_failure_rate"],
            "tool_budget_utilization": group["tool_budget_utilization"],
        },
    }


def build_routing_recommendations(
    analytics: dict[str, Any],
    *,
    policy_version: int | None = None,
) -> dict[str, Any]:
    groups = [
        group
        for group in analytics["groups"]
        if policy_version is None or group.get("policy_version", 0) == policy_version
    ]
    summary = (
        analytics["summary"]
        if policy_version is None
        else {
            "terminal_run_count": sum(group["terminal_run_count"] for group in groups),
            "rated_run_count": sum(group["rated_run_count"] for group in groups),
        }
    )
    items = [
        recommendation
        for group in groups
        if (recommendation := _recommend_group(group)) is not None
    ]
    return {
        "policy_version": policy_version,
        "readiness": {
            "minimum_terminal_runs": MIN_TERMINAL_RUNS,
            "minimum_rated_runs": MIN_RATED_RUNS,
            "terminal_run_count": summary["terminal_run_count"],
            "rated_run_count": summary["rated_run_count"],
            "operational_ready": summary["terminal_run_count"] >= MIN_TERMINAL_RUNS,
            "feedback_ready": summary["rated_run_count"] >= MIN_RATED_RUNS,
        },
        "items": items,
    }
