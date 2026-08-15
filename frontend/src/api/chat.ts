/**
 * 聊天 API - SSE 流式查询
 *
 * 使用 fetch + ReadableStream 消费 SSE 流，
 * 支持逐 token 渲染和引用标记。
 * Agent 模式附加 tool_call/tool_result 事件。
 */

import type { CitationData, ChatMode, ConversationDetail, ConversationSummary, RouteSelection, RunEventData, SSEDoneEvent } from '../types/chat';
import type { NoteItem } from '../types/note';
import client from './client';
import { streamSSE } from './sse';

/** Agent 工具调用步骤（前端展示用） */
export interface AgentStep {
  type: 'tool_call' | 'tool_result' | 'max_iterations';
  name?: string;
  arguments?: Record<string, unknown>;
  result?: string;
  message?: string;
}

/** SSE 流事件回调 */
export interface ChatStreamCallbacks {
  onToken: (text: string) => void;
  onCitation: (index: number) => void;
  onDone: (data: SSEDoneEvent) => void;
  onError: (error: string) => void;
  /** Agent 模式：工具调用开始 */
  onToolCall?: (id: string, nodeId: string, name: string, args: Record<string, unknown>) => void;
  /** Agent 模式：工具调用结果 */
  onToolResult?: (id: string, nodeId: string, name: string, result: string, status: 'completed' | 'failed', durationMs?: number) => void;
  /** Agent 模式：达到最大迭代 */
  onMaxIterations?: (message: string) => void;
  onRunStarted?: (runId: string, conversationId: string) => void;
  onRouteSelected?: (selection: RouteSelection) => void;
  onGoalEvent?: (event: RunEventData) => void;
  onSource?: (source: CitationData) => void;
  onNoteDraft?: (note: NoteItem) => void;
}

/**
 * 发起 SSE 流式 RAG 查询
 *
 * @param question 用户问题
 * @param conversationId 可选，已有对话 ID
 * @param callbacks 事件回调
 * @returns AbortController 用于取消请求
 */
export function streamChatQuery(
  question: string,
  conversationId: string | null,
  mode: ChatMode,
  callbacks: ChatStreamCallbacks
): AbortController {
  return streamSSE('/api/chat/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, conversation_id: conversationId, mode }),
    onMessage: ({ event, data: rawData }) => {
      const data = rawData as Record<string, unknown>;
      switch (event) {
                case 'token':
                  callbacks.onToken(String(data.text || ''));
                  break;
                case 'citation':
                  callbacks.onCitation(Number(data.index));
                  break;
                case 'done':
                  callbacks.onDone(data as unknown as SSEDoneEvent);
                  break;
                case 'error':
                  callbacks.onError(String(data.message || '未知错误'));
                  break;
                // ── Agent 模式事件 ──────────────────────────
                case 'tool_call':
                  callbacks.onToolCall?.(
                    String(data.id || ''), String(data.node_id || ''), String(data.name),
                    data.arguments as Record<string, unknown>
                  );
                  break;
                case 'tool_result':
                  callbacks.onToolResult?.(
                    String(data.id || ''), String(data.node_id || ''), String(data.name), String(data.result),
                    data.status === 'failed' ? 'failed' : 'completed', Number(data.duration_ms || 0)
                  );
                  break;
                case 'max_iterations':
                  callbacks.onMaxIterations?.(String(data.message || '达到最大搜索次数'));
                  break;
                case 'run_started':
                  callbacks.onRunStarted?.(String(data.run_id || ''), String(data.conversation_id || ''));
                  break;
                case 'route_selected':
                  callbacks.onRouteSelected?.(data as unknown as RouteSelection);
                  break;
                case 'goal_created':
                case 'goal_running':
                case 'goal_completed':
                case 'goal_failed':
                case 'goal_cancelled':
                  callbacks.onGoalEvent?.(data as unknown as RunEventData);
                  break;
                case 'source':
                  callbacks.onSource?.(data as unknown as CitationData);
                  break;
                case 'note_draft':
                  callbacks.onNoteDraft?.(data as unknown as NoteItem);
                  break;
      }
    },
    onError: (error) => callbacks.onError(error.message),
  });
}

/** 取消对话生成 */
export async function cancelChat(conversationId: string): Promise<void> {
  await fetch('/api/chat/cancel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation_id: conversationId }),
  });
}

export async function listConversations(): Promise<ConversationSummary[]> {
  const { data } = await client.get<{ conversations: ConversationSummary[] }>('/chat/history');
  return data.conversations;
}

export async function getConversation(conversationId: string): Promise<ConversationDetail> {
  const { data } = await client.get<ConversationDetail>(`/chat/conversations/${conversationId}`);
  return data;
}
