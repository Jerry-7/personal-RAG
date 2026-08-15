/**
 * 聊天状态管理 (Zustand)
 *
 * 管理对话消息列表、流式生成状态和引用元数据。
 */

import { create } from 'zustand';
import type { AgentStep, CitationData, GoalNodeData, MessageItem, ResearchRunDetail, ResearchRunSummary, RouteSelection, RunEventData } from '../types/chat';

interface ChatState {
  /** 当前对话 ID */
  conversationId: string | null;
  /** 消息列表 */
  messages: MessageItem[];
  /** 是否正在流式生成 */
  isStreaming: boolean;
  /** Whether the active Agent run is cooperatively paused. */
  isPaused: boolean;
  /** 当前流式生成的文本缓冲区 */
  streamingText: string;
  /** 当前流式消息中的引用列表 */
  streamingCitations: CitationData[];
  /** 流式消息引用计数器（用于内联标记） */
  citationCounter: number;
  runId: string | null;
  runHistory: ResearchRunSummary[];
  runSnapshot: ResearchRunDetail | null;
  routeSelection: RouteSelection | null;
  goalNodes: GoalNodeData[];
  runEvents: RunEventData[];
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
  setRunHistory: (runs: ResearchRunSummary[]) => void;
  restoreRunSnapshot: (snapshot: ResearchRunDetail) => void;
  setPaused: (paused: boolean) => void;
  setRouteSelection: (selection: RouteSelection) => void;
  applyRunEvent: (event: RunEventData) => void;
  addToolCall: (id: string, nodeId: string, name: string, args: Record<string, unknown>) => void;
  finishToolCall: (id: string, nodeId: string, name: string, result: string, status: 'completed' | 'failed', durationMs?: number) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversationId: localStorage.getItem('personal-rag.conversation-id'),
  messages: [],
  isStreaming: false,
  isPaused: false,
  streamingText: '',
  streamingCitations: [],
  citationCounter: 0,
  runId: null,
  runHistory: [],
  runSnapshot: null,
  routeSelection: null,
  goalNodes: [],
  runEvents: [],
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
    set({ isStreaming: true, isPaused: false, streamingText: '', streamingCitations: [], citationCounter: 0, agentSteps: [], runId: null, runHistory: [], runSnapshot: null, routeSelection: null, goalNodes: [], runEvents: [] }),

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
      set({ isStreaming: false, isPaused: false, streamingText: '', streamingCitations: [] });
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
      isPaused: false,
      streamingText: '',
      streamingCitations: [],
    });
  },

  cancelStreaming: () =>
    set({ isStreaming: false, isPaused: false, streamingText: '', streamingCitations: [] }),

  clearMessages: () => {
    localStorage.removeItem('personal-rag.conversation-id');
    set({ messages: [], conversationId: null, agentSteps: [], runId: null, runHistory: [], runSnapshot: null, routeSelection: null, goalNodes: [], runEvents: [], isLoadingHistory: false, isPaused: false });
  },
  setLoadingHistory: (loading) => set({ isLoadingHistory: loading }),
  restoreConversation: (id, messages) => {
    localStorage.setItem('personal-rag.conversation-id', id);
    set({
      conversationId: id,
      messages,
      isLoadingHistory: false,
      isStreaming: false,
      isPaused: false,
      streamingText: '',
      streamingCitations: [],
      agentSteps: [],
      runId: null,
      runHistory: [],
      runSnapshot: null,
      routeSelection: null,
      goalNodes: [],
      runEvents: [],
    });
  },
  setRunId: (id) => set({ runId: id }),
  setRunHistory: (runs) => set({ runHistory: runs }),
  restoreRunSnapshot: (snapshot) => set({
    runId: snapshot.id,
    runSnapshot: snapshot,
    routeSelection: snapshot.routing,
    goalNodes: snapshot.goals,
    runEvents: snapshot.events,
    agentSteps: snapshot.tools.map((tool) => ({
      id: tool.id,
      node_id: tool.node_id || undefined,
      type: 'tool_call' as const,
      name: tool.name,
      arguments: tool.arguments,
      result: tool.error_message || undefined,
      status: tool.status,
      duration_ms: tool.duration_ms || undefined,
      timestamp: tool.created_at ? new Date(tool.created_at).getTime() : 0,
    })),
  }),
  setPaused: (paused) => set({ isPaused: paused }),
  setRouteSelection: (selection) => set({ routeSelection: selection }),
  applyRunEvent: (event) => set((state) => {
    const goal = event.payload.goal;
    const goalNodes = goal
      ? [...state.goalNodes.filter((item) => item.id !== goal.id), goal]
          .sort((left, right) => left.sequence - right.sequence)
      : state.goalNodes;
    const runEvents = state.runEvents.some((item) => item.event_id === event.event_id)
      ? state.runEvents
      : [...state.runEvents, event].sort((left, right) => left.sequence - right.sequence);
    return { goalNodes, runEvents };
  }),
  addToolCall: (id, nodeId, name, args) => set((state) => ({
    agentSteps: [...state.agentSteps, { id, node_id: nodeId, type: 'tool_call', name, arguments: args, status: 'running', timestamp: Date.now() }],
  })),
  finishToolCall: (id, nodeId, name, result, status, durationMs) => set((state) => ({
    agentSteps: state.agentSteps.map((step) =>
      (id && step.id === id)
        || (!id && step.node_id === nodeId && step.name === name && step.status === 'running')
        ? { ...step, node_id: nodeId, result, status, duration_ms: durationMs }
        : step
    ),
  })),
}));
