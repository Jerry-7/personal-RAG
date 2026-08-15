import { getResearchRun, listResearchRuns } from '../api/research';
import { useChatStore } from '../store/chatStore';

export async function loadRunSnapshot(runId: string): Promise<void> {
  const snapshot = await getResearchRun(runId);
  const state = useChatStore.getState();
  if (state.conversationId !== snapshot.conversation_id || state.isStreaming) return;
  state.restoreRunSnapshot(snapshot);
}

export async function restoreConversationRuns(
  conversationId: string,
  preferredRunId?: string,
): Promise<void> {
  const runs = await listResearchRuns(conversationId);
  let state = useChatStore.getState();
  if (state.conversationId !== conversationId || state.isStreaming) return;
  state.setRunHistory(runs);
  const selected = runs.find((run) => run.id === preferredRunId) || runs[0];
  if (!selected) return;
  const snapshot = await getResearchRun(selected.id);
  state = useChatStore.getState();
  if (state.conversationId === conversationId && !state.isStreaming) {
    state.restoreRunSnapshot(snapshot);
  }
}
