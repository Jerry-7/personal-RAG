import { deleteRunFeedback, getRoutingAnalytics, updateRunFeedback } from '../api/research';
import { useChatStore } from '../store/chatStore';
import type { AgentRunFeedback, AgentRunFeedbackReason } from '../types/chat';


async function refreshAnalytics(): Promise<void> {
  const analytics = await getRoutingAnalytics();
  useChatStore.getState().setRoutingAnalytics(analytics);
}

export async function saveRunFeedback(
  runId: string,
  rating: AgentRunFeedback['rating'],
  reason?: AgentRunFeedbackReason,
): Promise<void> {
  const feedback = await updateRunFeedback(runId, rating, reason);
  useChatStore.getState().setRunFeedback(runId, feedback);
  await refreshAnalytics().catch(() => undefined);
}

export async function removeRunFeedback(runId: string): Promise<void> {
  await deleteRunFeedback(runId);
  useChatStore.getState().setRunFeedback(runId, null);
  await refreshAnalytics().catch(() => undefined);
}
