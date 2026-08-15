"""Aggregate operational routing metrics from persisted Agent runs."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from app.db.models import AgentRun, AgentRunFeedback, GoalNode, ToolExecution
from app.services.routing_recommendations import build_routing_recommendations


TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})


def _duration_ms(run: AgentRun) -> int | None:
    if run.started_at is None or run.completed_at is None:
        return None
    return max(0, round((run.completed_at - run.started_at).total_seconds() * 1000))


def _percent(numerator: int, denominator: int) -> float:
    return round(numerator * 100 / denominator, 1) if denominator else 0.0


def _planning_source(run: AgentRun, goals: list[GoalNode]) -> str:
    if run.route_name != "supervisor":
        return "not_applicable"
    sources: set[str] = set()
    for goal in goals:
        if goal.kind != "agent":
            continue
        try:
            value = json.loads(goal.input_json or "{}").get("planning_source")
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue
        if value in {"model", "fallback"}:
            sources.add(value)
    if not sources:
        return "fallback"
    return next(iter(sources)) if len(sources) == 1 else "mixed"


def _summarize(
    runs: list[AgentRun],
    goals_by_run: dict[str, list[GoalNode]],
    tools_by_run: dict[str, list[ToolExecution]],
    feedback_by_run: dict[str, AgentRunFeedback],
) -> dict[str, Any]:
    statuses = Counter(run.status for run in runs)
    terminal_runs = [run for run in runs if run.status in TERMINAL_STATUSES]
    durations = [
        duration
        for run in runs
        if (duration := _duration_ms(run)) is not None
    ]
    goals = [goal for run in runs for goal in goals_by_run.get(run.id, [])]
    tools = [tool for run in runs for tool in tools_by_run.get(run.id, [])]
    tool_budget = sum(goal.tool_call_budget for goal in goals if goal.kind == "agent")
    failed_tools = sum(tool.status == "failed" for tool in tools)
    feedback = [feedback_by_run[run.id] for run in runs if run.id in feedback_by_run]
    positive_feedback = sum(item.rating == "positive" for item in feedback)
    negative_reasons = Counter(
        item.reason
        for item in feedback
        if item.rating == "negative" and item.reason
    )
    return {
        "run_count": len(runs),
        "terminal_run_count": len(terminal_runs),
        "completed_run_count": statuses["completed"],
        "failed_run_count": statuses["failed"],
        "cancelled_run_count": statuses["cancelled"],
        "interrupted_run_count": statuses["interrupted"],
        "active_run_count": statuses["running"] + statuses["paused"],
        "operational_success_rate": _percent(statuses["completed"], len(terminal_runs)),
        "average_duration_ms": round(sum(durations) / len(durations)) if durations else None,
        "retry_run_count": sum(run.retry_of_run_id is not None for run in runs),
        "retry_rate": _percent(
            sum(run.retry_of_run_id is not None for run in runs), len(runs)
        ),
        "manual_override_count": sum(
            run.route_tier_preference != "auto" for run in runs
        ),
        "tool_call_count": len(tools),
        "failed_tool_call_count": failed_tools,
        "tool_failure_rate": _percent(failed_tools, len(tools)),
        "tool_call_budget": tool_budget,
        "tool_budget_utilization": _percent(len(tools), tool_budget),
        "rated_run_count": len(feedback),
        "positive_feedback_count": positive_feedback,
        "negative_feedback_count": len(feedback) - positive_feedback,
        "user_satisfaction_rate": _percent(positive_feedback, len(feedback)),
        "negative_reason_counts": dict(negative_reasons),
    }


def build_routing_analytics(
    runs: list[AgentRun],
    goals: list[GoalNode],
    tools: list[ToolExecution],
    feedback: list[AgentRunFeedback] | None = None,
    *,
    active_policy_version: int | None = None,
) -> dict[str, Any]:
    goals_by_run: dict[str, list[GoalNode]] = defaultdict(list)
    tools_by_run: dict[str, list[ToolExecution]] = defaultdict(list)
    for goal in goals:
        goals_by_run[goal.run_id].append(goal)
    for tool in tools:
        tools_by_run[tool.run_id].append(tool)
    feedback_by_run = {item.run_id: item for item in feedback or []}

    grouped_runs: dict[tuple[int, str, str, str], list[AgentRun]] = defaultdict(list)
    for run in runs:
        source = _planning_source(run, goals_by_run[run.id])
        grouped_runs[
            (run.route_policy_version, run.route_tier, run.route_name, source)
        ].append(run)

    groups = [
        {
            "policy_version": policy_version,
            "tier": tier,
            "route": route,
            "planning_source": source,
            **_summarize(group, goals_by_run, tools_by_run, feedback_by_run),
        }
        for (policy_version, tier, route, source), group in grouped_runs.items()
    ]
    groups.sort(key=lambda item: (
        -item["policy_version"],
        -item["run_count"],
        item["tier"],
        item["route"],
    ))
    summary = _summarize(runs, goals_by_run, tools_by_run, feedback_by_run)
    summary["tier_counts"] = {
        tier: sum(run.route_tier == tier for run in runs)
        for tier in ("fast", "standard", "expert")
    }
    summary["planning_source_counts"] = dict(Counter(
        _planning_source(run, goals_by_run[run.id]) for run in runs
    ))
    analytics = {"summary": summary, "groups": groups}
    return {
        **analytics,
        "recommendation_report": build_routing_recommendations(
            analytics,
            policy_version=active_policy_version,
        ),
    }
