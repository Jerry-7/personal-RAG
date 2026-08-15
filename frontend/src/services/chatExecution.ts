import {
  cancelChat,
  pauseChat,
  resumeChat,
  streamChatQuery,
  streamChatRetry,
} from '../api/chat';
import type { ChatStreamCallbacks } from '../api/chat';
import { useChatStore } from '../store/chatStore';
import { useNoteStore } from '../store/noteStore';
import { useSidebarStore } from '../store/sidebarStore';
import type { ChatMode } from '../types/chat';
import { restoreConversationRuns } from './runHistory';

let activeController: AbortController | null = null;

function callbacks(): ChatStreamCallbacks {
  return {
    onToken: (text) => useChatStore.getState().appendToken(text),
    onCitation: () => undefined,
    onDone: (data) => {
      activeController = null;
      const state = useChatStore.getState();
      if (!state.conversationId && data.conversation_id) {
        state.setConversationId(data.conversation_id);
      }
      state.finishStreaming(data.citations, data.message_id);
      if (data.conversation_id && data.run_id) {
        void restoreConversationRuns(data.conversation_id, data.run_id).catch(() => undefined);
      }
    },
    onError: (error) => {
      activeController = null;
      const state = useChatStore.getState();
      if (!state.isStreaming) return;
      state.appendToken(`生成失败：${error}`);
      state.finishStreaming([], crypto.randomUUID());
    },
    onRunStarted: (runId, conversationId) => {
      const state = useChatStore.getState();
      state.setRunId(runId);
      state.setPaused(false);
      if (conversationId) state.setConversationId(conversationId);
    },
    onRouteSelected: (selection) => {
      useChatStore.getState().setRouteSelection(selection);
    },
    onGoalEvent: (event) => useChatStore.getState().applyRunEvent(event),
    onToolCall: (id, nodeId, name, args) => {
      useChatStore.getState().addToolCall(id, nodeId, name, args);
    },
    onToolResult: (id, nodeId, name, result, status, durationMs) => {
      useChatStore.getState().finishToolCall(
        id,
        nodeId,
        name,
        result,
        status,
        durationMs
      );
    },
    onNoteDraft: (note) => {
      useNoteStore.getState().upsertNote(note);
      useSidebarStore.getState().openDraft(note);
    },
  };
}

export function startChatQuery(
  question: string,
  conversationId: string | null,
  mode: ChatMode,
): AbortController {
  const state = useChatStore.getState();
  state.addUserMessage(question);
  state.startStreaming();
  activeController = streamChatQuery(
    question,
    conversationId,
    mode,
    callbacks(),
  );
  return activeController;
}

export function retryChatRun(runId: string): AbortController | null {
  const state = useChatStore.getState();
  if (state.isStreaming) return null;
  state.startStreaming();
  activeController = streamChatRetry(runId, callbacks());
  return activeController;
}

export async function stopChatExecution(): Promise<void> {
  const state = useChatStore.getState();
  const conversationId = state.conversationId;
  if (conversationId) {
    try {
      await cancelChat(conversationId);
      return;
    } catch {
      // Fall through to local cleanup when the server cannot accept cancellation.
    }
  }
  state.cancelStreaming();
  activeController?.abort();
  activeController = null;
}

export async function pauseChatExecution(): Promise<void> {
  const state = useChatStore.getState();
  if (!state.isStreaming || state.isPaused || !state.conversationId) return;
  await pauseChat(state.conversationId);
  useChatStore.getState().setPaused(true);
}

export async function resumeChatExecution(): Promise<void> {
  const state = useChatStore.getState();
  if (!state.isStreaming || !state.isPaused || !state.conversationId) return;
  await resumeChat(state.conversationId);
  useChatStore.getState().setPaused(false);
}
