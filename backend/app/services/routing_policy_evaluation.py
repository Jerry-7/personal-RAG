"""Observed policy metrics and read-only historical routing simulations."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from app.agent.routing import AgentTier, RoutingPolicy, classify_route_tier
from app.db.models import AgentRun, AgentRunFeedback, GoalNode, ToolExecution
from app.services.routing_analytics import TERMINAL_STATUSES, summarize_policy_versions
from app.services.routing_policy import DEFAULT_ROUTING_POLICY, serialize_policy
from app.services.routing_policy_conclusion import serialize_policy_conclusion


_TIERS: tuple[AgentTier, ...] = ("fast", "standard", "expert")
_TIER_ORDER = {tier: index for index, tier in enumerate(_TIERS)}
MIN_EXPERIMENT_TERMINAL_RUNS = 10
MIN_EXPERIMENT_RATED_RUNS = 5


def _empty_tier_counts() -> dict[AgentTier, int]:
    return {tier: 0 for tier in _TIERS}


def _difference(current: float | int | None, baseline: float | int | None):
    if current is None or baseline is None:
        return None
    return round(current - baseline, 1)


def build_policy_experiment(
    current_policy: dict[str, Any],
    observed_versions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Derive a guarded experiment state without mutating routing policy."""
    version = current_policy["version"]
    baseline_version = current_policy.get("based_on_version")
    source = current_policy.get("source")
    metrics_by_version = {
        item["version"]: item["metrics"] for item in observed_versions
    }
    current = metrics_by_version.get(version)
    baseline = metrics_by_version.get(baseline_version)
    terminal_count = int(current["terminal_run_count"]) if current else 0
    rated_count = int(current["rated_run_count"]) if current else 0
    operational_ready = terminal_count >= MIN_EXPERIMENT_TERMINAL_RUNS
    feedback_ready = rated_count >= MIN_EXPERIMENT_RATED_RUNS
    comparison = {
        "available": baseline is not None,
        "operational_success_rate_delta": _difference(
            current["operational_success_rate"] if current else None,
            baseline["operational_success_rate"] if baseline else None,
        ),
        "average_duration_ms_delta": _difference(
            current["average_duration_ms"] if current else None,
            baseline["average_duration_ms"] if baseline else None,
        ),
        "tool_failure_rate_delta": _difference(
            current["tool_failure_rate"] if current else None,
            baseline["tool_failure_rate"] if baseline else None,
        ),
        "tool_budget_utilization_delta": _difference(
            current["tool_budget_utilization"] if current else None,
            baseline["tool_budget_utilization"] if baseline else None,
        ),
        "user_satisfaction_rate_delta": (
            _difference(
                current["user_satisfaction_rate"],
                baseline["user_satisfaction_rate"],
            )
            if current
            and baseline
            and current["rated_run_count"] > 0
            and baseline["rated_run_count"] > 0
            else None
        ),
    }

    status = "collecting"
    recommendation = "collect_runs"
    reasons: list[str] = []
    if baseline_version is None or source in {"default", "rollback"}:
        status = "not_applicable"
        recommendation = "not_applicable"
        reasons.append("no_experiment_baseline")
    elif not operational_ready:
        reasons.append("insufficient_terminal_runs")
    else:
        severe_operational_regression = (
            current["operational_success_rate"] < 70
            or (
                comparison["operational_success_rate_delta"] is not None
                and comparison["operational_success_rate_delta"] <= -15
            )
        )
        if severe_operational_regression:
            status = "operational_alert"
            recommendation = "rollback"
            reasons.append("severe_operational_regression")
        elif not feedback_ready:
            status = "awaiting_feedback"
            recommendation = "collect_feedback"
            reasons.append("insufficient_rated_runs")
        else:
            status = "ready"
            quality_regression = (
                current["user_satisfaction_rate"] < 60
                or (
                    comparison["user_satisfaction_rate_delta"] is not None
                    and comparison["user_satisfaction_rate_delta"] <= -10
                )
            )
            operational_regression = (
                current["operational_success_rate"] < 80
                or (
                    comparison["operational_success_rate_delta"] is not None
                    and comparison["operational_success_rate_delta"] <= -10
                )
            )
            if quality_regression or operational_regression:
                recommendation = "rollback"
                if operational_regression:
                    reasons.append("operational_regression")
                if quality_regression:
                    reasons.append("quality_regression")
            elif (
                current["operational_success_rate"] >= 90
                and current["user_satisfaction_rate"] >= 80
            ):
                recommendation = "keep"
                reasons.append("stable_improvement")
            else:
                recommendation = "review"
                reasons.append("mixed_results")

    return {
        "status": status,
        "current_policy_version": version,
        "baseline_policy_version": baseline_version,
        "readiness": {
            "minimum_terminal_runs": MIN_EXPERIMENT_TERMINAL_RUNS,
            "minimum_rated_runs": MIN_EXPERIMENT_RATED_RUNS,
            "terminal_run_count": terminal_count,
            "rated_run_count": rated_count,
            "operational_ready": operational_ready,
            "feedback_ready": feedback_ready,
        },
        "comparison": comparison,
        "recommendation": recommendation,
        "reason_codes": reasons,
    }


def simulate_routing_policy(
    runs: Iterable[AgentRun],
    *,
    standard_min_score: int,
    expert_min_score: int,
    source_policies: dict[int, RoutingPolicy] | None = None,
) -> dict[str, Any]:
    """Redistribute historical automatic runs under candidate score thresholds."""
    candidate = RoutingPolicy(
        standard_min_score=standard_min_score,
        expert_min_score=expert_min_score,
    )
    all_runs = list(runs)
    terminal_runs = [run for run in all_runs if run.status in TERMINAL_STATUSES]
    manual_runs = [run for run in terminal_runs if run.route_tier_preference != "auto"]
    automatic_runs = [run for run in terminal_runs if run.route_tier_preference == "auto"]
    policies = {0: DEFAULT_ROUTING_POLICY, **(source_policies or {})}
    baseline_mismatches = []
    eligible_runs = []
    for run in automatic_runs:
        source_policy = policies.get(getattr(run, "route_policy_version", 0))
        expected_tier = (
            classify_route_tier(
                run.route_score,
                source_policy,
                mode=run.mode if run.mode in {"auto", "local", "web"} else "auto",
            )
            if source_policy is not None
            else None
        )
        if expected_tier != run.route_tier:
            baseline_mismatches.append(run)
        else:
            eligible_runs.append(run)
    actual_counts = _empty_tier_counts()
    projected_counts = _empty_tier_counts()
    transitions = {source: _empty_tier_counts() for source in _TIERS}
    score_counts: Counter[str] = Counter()
    upgrade_count = 0
    downgrade_count = 0
    for run in eligible_runs:
        actual_tier: AgentTier = (
            run.route_tier if run.route_tier in _TIER_ORDER else "standard"
        )
        projected_tier = classify_route_tier(
            run.route_score,
            candidate,
            mode=run.mode if run.mode in {"auto", "local", "web"} else "auto",
        )
        actual_counts[actual_tier] += 1
        projected_counts[projected_tier] += 1
        transitions[actual_tier][projected_tier] += 1
        score_counts[str(run.route_score)] += 1
        if _TIER_ORDER[projected_tier] > _TIER_ORDER[actual_tier]:
            upgrade_count += 1
        elif _TIER_ORDER[projected_tier] < _TIER_ORDER[actual_tier]:
            downgrade_count += 1

    changed_run_count = sum(
        transitions[source][target]
        for source in _TIERS
        for target in _TIERS
        if source != target
    )
    return {
        "candidate_policy": {
            "version": None,
            "standard_min_score": candidate.standard_min_score,
            "expert_min_score": candidate.expert_min_score,
        },
        "eligibility": {
            "sample_limit": len(all_runs),
            "terminal_run_count": len(terminal_runs),
            "eligible_auto_run_count": len(eligible_runs),
            "excluded_manual_override_count": len(manual_runs),
            "excluded_baseline_mismatch_count": len(baseline_mismatches),
            "excluded_non_terminal_count": len(all_runs) - len(terminal_runs),
        },
        "actual_tier_counts": actual_counts,
        "projected_tier_counts": projected_counts,
        "transitions": transitions,
        "score_counts": dict(sorted(score_counts.items(), key=lambda item: int(item[0]))),
        "changed_run_count": changed_run_count,
        "upgrade_run_count": upgrade_count,
        "downgrade_run_count": downgrade_count,
        "is_counterfactual": True,
        "quality_prediction": None,
    }


def build_routing_policy_evaluation(
    runs: list[AgentRun],
    goals: list[GoalNode],
    tools: list[ToolExecution],
    feedback: list[AgentRunFeedback] | None,
    *,
    current_policy: RoutingPolicy,
    policy_rows: Iterable[Any] = (),
    conclusion_rows: Iterable[Any] = (),
    candidate_standard_min_score: int | None = None,
    candidate_expert_min_score: int | None = None,
) -> dict[str, Any]:
    policy_rows = list(policy_rows)
    policies = {row.version: row for row in policy_rows}
    source_policies = {
        0: DEFAULT_ROUTING_POLICY,
        **{
            row.version: RoutingPolicy(
                version=row.version,
                standard_min_score=row.standard_min_score,
                expert_min_score=row.expert_min_score,
            )
            for row in policy_rows
        },
    }
    observed = []
    for metrics in summarize_policy_versions(runs, goals, tools, feedback):
        version = metrics["policy_version"]
        policy = policies.get(
            version,
            DEFAULT_ROUTING_POLICY if version == 0 else None,
        )
        policy_data = serialize_policy(policy) if policy is not None else {
            "version": version,
            "standard_min_score": None,
            "expert_min_score": None,
            "source": "unavailable",
            "based_on_version": None,
            "note": None,
            "is_active": False,
            "created_at": None,
        }
        observed.append({**policy_data, "metrics": metrics})

    standard_min_score = (
        current_policy.standard_min_score
        if candidate_standard_min_score is None
        else candidate_standard_min_score
    )
    expert_min_score = (
        current_policy.expert_min_score
        if candidate_expert_min_score is None
        else candidate_expert_min_score
    )
    current_policy_record = policies.get(
        current_policy.version,
        DEFAULT_ROUTING_POLICY if current_policy.version == 0 else current_policy,
    )
    current_policy_data = serialize_policy(current_policy_record)
    conclusions = [serialize_policy_conclusion(row) for row in conclusion_rows]
    experiment = build_policy_experiment(current_policy_data, observed)
    experiment["conclusion"] = next(
        (
            item
            for item in conclusions
            if item["policy_version"] == current_policy.version
        ),
        None,
    )
    return {
        "current_policy": current_policy_data,
        "observed_versions": observed,
        "experiment": experiment,
        "conclusions": conclusions,
        "simulation": simulate_routing_policy(
            runs,
            standard_min_score=standard_min_score,
            expert_min_score=expert_min_score,
            source_policies=source_policies,
        ),
    }
