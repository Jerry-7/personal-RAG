import type { ResearchRunDetail, ResearchRunSummary } from '../types/chat';
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
