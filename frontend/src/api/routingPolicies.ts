import client from './client';
import type {
  RoutingPolicyCreateInput,
  RoutingPolicyReport,
  RoutingPolicyRollbackInput,
  RoutingPolicyVersion,
} from '../types/routingPolicy';


export async function getRoutingPolicies(): Promise<RoutingPolicyReport> {
  const { data } = await client.get<RoutingPolicyReport>('/routing-policies');
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
