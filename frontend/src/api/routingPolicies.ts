import client from './client';
import type {
  RoutingPolicyCreateInput,
  RoutingPolicyEvaluation,
  RoutingPolicyReport,
  RoutingPolicyRollbackInput,
  RoutingPolicySimulation,
  RoutingPolicyVersion,
} from '../types/routingPolicy';


export async function getRoutingPolicies(): Promise<RoutingPolicyReport> {
  const { data } = await client.get<RoutingPolicyReport>('/routing-policies');
  return data;
}

export async function getRoutingPolicyEvaluation(
  limit = 200,
): Promise<RoutingPolicyEvaluation> {
  const { data } = await client.get<RoutingPolicyEvaluation>('/routing-policies/evaluation', {
    params: { limit },
  });
  return data;
}

export async function simulateRoutingPolicy(
  standardMinScore: number,
  expertMinScore: number,
  limit = 200,
): Promise<RoutingPolicySimulation> {
  const { data } = await client.get<RoutingPolicySimulation>('/routing-policies/simulation', {
    params: {
      standard_min_score: standardMinScore,
      expert_min_score: expertMinScore,
      limit,
    },
  });
  return data;
}

export async function createRoutingPolicy(
  input: RoutingPolicyCreateInput,
): Promise<RoutingPolicyVersion> {
  const { data } = await client.post<RoutingPolicyVersion>('/routing-policies', input);
  return data;
}

export async function rollbackRoutingPolicy(
  version: number,
  input: RoutingPolicyRollbackInput,
): Promise<RoutingPolicyVersion> {
  const { data } = await client.post<RoutingPolicyVersion>(
    `/routing-policies/${version}/rollback`,
    input,
  );
  return data;
}
