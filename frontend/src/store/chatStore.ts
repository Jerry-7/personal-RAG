/**
 * 聊天状态管理 (Zustand)
 *
 * 管理对话消息列表、流式生成状态和引用元数据。
 */

import { create } from 'zustand';
import type { AgentStep, CitationData, MessageItem } from '../types/chat';

interface ChatState {
  /** 当前对话 ID */
  conversationId: string | null;
  /** 消息列表 */
  messages: MessageItem[];
  /** 是否正在流式生成 */
  isStreaming: boolean;
  /** 当前流式生成的文本缓冲区 */
  streamingText: string;
  /** 当前流式消息中的引用列表 */
  streamingCitations: CitationData[];
  /** 流式消息引用计数器（用于内联标记） */
  citationCounter: number;
  runId: string | null;
  agentSteps: AgentStep[];
  isLoadingHistory: boolean;

  // Actions
  setConversationId: (id: string | null) => void;
  addUserMessage: (content: string) => void;
  startStreaming: () => void;
  appendToken: (text: string) => void;
  addCitation: (index: number) => void;
  finishStreaming: (citations: CitationData[], messageId: string) => void;
  cancelStreaming: () => void;
  clearMessages: () => void;
  setLoadingHistory: (loading: boolean) => void;
  restoreConversation: (id: string, messages: MessageItem[]) => void;
  setRunId: (id: string) => void;
  addToolCall: (id: string, name: string, args: Record<string, unknown>) => void;
  finishToolCall: (id: string, name: string, result: string, status: 'completed' | 'failed', durationMs?: number) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversationId: localStorage.getItem('personal-rag.conversation-id'),
  messages: [],
  isStreaming: false,
  streamingText: '',
  streamingCitations: [],
  citationCounter: 0,
  runId: null,
  agentSteps: [],
  isLoadingHistory: false,

  setConversationId: (id) => {
    if (id) localStorage.setItem('personal-rag.conversation-id', id);
    else localStorage.removeItem('personal-rag.conversation-id');
    set({ conversationId: id });
  },

  addUserMessage: (content) => {
    const msg: MessageItem = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      citations: [],
      created_at: new Date().toISOString(),
    };
    set((s) => ({ messages: [...s.messages, msg] }));
  },

  startStreaming: () =>
    set({ isStreaming: true, streamingText: '', streamingCitations: [], citationCounter: 0, agentSteps: [], runId: null }),

  appendToken: (text) =>
    set((s) => ({ streamingText: s.streamingText + text })),

  addCitation: (index) =>
    set((s) => ({
      streamingText: s.streamingText + `[${index}]`,
    })),

  finishStreaming: (citations, messageId) => {
    const state = get();
    if (!state.isStreaming) return;
    const content = state.streamingText.trim();
    if (!content) {
      set({ isStreaming: false, streamingText: '', streamingCitations: [] });
      return;
    }
    const msg: MessageItem = {
      id: messageId || crypto.randomUUID(),
      role: 'assistant',
      content: state.streamingText,
      citations,
      created_at: new Date().toISOString(),
    };
    set({
      messages: [...state.messages, msg],
      isStreaming: false,
      streamingText: '',
      streamingCitations: [],
    });
  },

  cancelStreaming: () =>
    set({ isStreaming: false, streamingText: '', streamingCitations: [] }),

  clearMessages: () => {
    localStorage.removeItem('personal-rag.conversation-id');
    set({ messages: [], conversationId: null, agentSteps: [], runId: null, isLoadingHistory: false });
  },
  setLoadingHistory: (loading) => set({ isLoadingHistory: loading }),
  restoreConversation: (id, messages) => {
    localStorage.setItem('personal-rag.conversation-id', id);
    set({
      conversationId: id,
      messages,
      isLoadingHistory: false,
      isStreaming: false,
      streamingText: '',
      streamingCitations: [],
      agentSteps: [],
      runId: null,
    });
  },
  setRunId: (id) => set({ runId: id }),
  addToolCall: (id, name, args) => set((state) => ({
    agentSteps: [...state.agentSteps, { id, type: 'tool_call', name, arguments: args, status: 'running', timestamp: Date.now() }],
  })),
  finishToolCall: (id, name, result, status, durationMs) => set((state) => ({
    agentSteps: state.agentSteps.map((step) =>
      (id && step.id === id) || (!id && step.name === name && step.status === 'running')
        ? { ...step, result, status, duration_ms: durationMs }
        : step
    ),
  })),
}));
