/**
 * 聊天状态管理 (Zustand)
 *
 * 管理对话消息列表、流式生成状态和引用元数据。
 */

import { create } from 'zustand';
import type { CitationData, MessageItem } from '../types/chat';

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

  // Actions
  setConversationId: (id: string | null) => void;
  addUserMessage: (content: string) => void;
  startStreaming: () => void;
  appendToken: (text: string) => void;
  addCitation: (index: number) => void;
  finishStreaming: (citations: CitationData[], messageId: string) => void;
  cancelStreaming: () => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversationId: null,
  messages: [],
  isStreaming: false,
  streamingText: '',
  streamingCitations: [],
  citationCounter: 0,

  setConversationId: (id) => set({ conversationId: id }),

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
    set({ isStreaming: true, streamingText: '', streamingCitations: [], citationCounter: 0 }),

  appendToken: (text) =>
    set((s) => ({ streamingText: s.streamingText + text })),

  addCitation: (index) =>
    set((s) => ({
      streamingText: s.streamingText + `[${index}]`,
    })),

  finishStreaming: (citations, messageId) => {
    const state = get();
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

  clearMessages: () => set({ messages: [], conversationId: null }),
}));
