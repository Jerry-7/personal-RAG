import type { ResearchRunDetail, ResearchRunSummary, RoutingAnalytics } from '../types/chat';
import client from './client';

export async function listResearchRuns(conversationId: string): Promise<ResearchRunSummary[]> {
  const { data } = await client.get<{ runs: ResearchRunSummary[] }>('/research-runs', {
    params: { conversation_id: conversationId },
  });
  return data.runs;
}

export async function getResearchRun(runId: string): Promise<ResearchRunDetail> {
  const { data } = await client.get<ResearchRunDetail>(`/research-runs/${runId}`);
  return data;
}

export async function getRoutingAnalytics(limit = 200): Promise<RoutingAnalytics> {
  const { data } = await client.get<RoutingAnalytics>('/research-runs/analytics', {
    params: { limit },
  });
  return data;
}
