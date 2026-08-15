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
