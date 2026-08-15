"""Observed policy metrics and read-only historical routing simulations."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from app.agent.routing import AgentTier, RoutingPolicy, classify_route_tier
from app.db.models import AgentRun, AgentRunFeedback, GoalNode, ToolExecution
from app.services.routing_analytics import TERMINAL_STATUSES, summarize_policy_versions
from app.services.routing_policy import DEFAULT_ROUTING_POLICY, serialize_policy


_TIERS: tuple[AgentTier, ...] = ("fast", "standard", "expert")
_TIER_ORDER = {tier: index for index, tier in enumerate(_TIERS)}


def _empty_tier_counts() -> dict[AgentTier, int]:
    return {tier: 0 for tier in _TIERS}


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
    return {
        "current_policy": serialize_policy(current_policy),
        "observed_versions": observed,
        "simulation": simulate_routing_policy(
            runs,
            standard_min_score=standard_min_score,
            expert_min_score=expert_min_score,
            source_policies=source_policies,
        ),
    }
