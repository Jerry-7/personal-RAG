export interface RoutingPolicyVersion {
  version: number;
  standard_min_score: number;
  expert_min_score: number;
  source: 'default' | 'manual' | 'rollback';
  based_on_version: number | null;
  note: string | null;
  is_active: boolean;
  created_at: string | null;
}

export interface RoutingPolicyReport {
  current: RoutingPolicyVersion;
  versions: RoutingPolicyVersion[];
}

export interface RoutingPolicyCreateInput {
  standard_min_score: number;
  expert_min_score: number;
  expected_active_version: number;
  note?: string;
}

export interface RoutingPolicyRollbackInput {
  expected_active_version: number;
  note?: string;
}

export interface RoutingPolicyObservedMetrics {
  run_count: number;
  terminal_run_count: number;
  operational_success_rate: number;
  average_duration_ms: number | null;
  tool_failure_rate: number;
  tool_budget_utilization: number;
  rated_run_count: number;
  user_satisfaction_rate: number;
}

export interface RoutingPolicyObservedVersion extends RoutingPolicyVersion {
  metrics: RoutingPolicyObservedMetrics & { policy_version: number };
}

export type RoutingTier = 'fast' | 'standard' | 'expert';

export interface RoutingPolicySimulation {
  candidate_policy: {
    version: number | null;
    standard_min_score: number;
    expert_min_score: number;
  };
  eligibility: {
    sample_limit: number;
    terminal_run_count: number;
    eligible_auto_run_count: number;
    excluded_manual_override_count: number;
    excluded_baseline_mismatch_count: number;
    excluded_non_terminal_count: number;
  };
  actual_tier_counts: Record<RoutingTier, number>;
  projected_tier_counts: Record<RoutingTier, number>;
  transitions: Record<RoutingTier, Record<RoutingTier, number>>;
  score_counts: Record<string, number>;
  changed_run_count: number;
  upgrade_run_count: number;
  downgrade_run_count: number;
  is_counterfactual: true;
  quality_prediction: null;
}

export interface RoutingPolicyEvaluation {
  current_policy: RoutingPolicyVersion;
  observed_versions: RoutingPolicyObservedVersion[];
  simulation: RoutingPolicySimulation;
}
