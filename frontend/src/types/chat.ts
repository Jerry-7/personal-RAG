/**
 * 聊天/消息数据类型定义
 */

/** 引用元数据 */
export interface CitationData {
  index: number;
  document_id: string;
  chunk_id: string;
  snippet: string;
  filename: string;
  page_number?: number;
  start_timestamp?: number;
  end_timestamp?: number;
  source_type: 'text' | 'video' | 'audio';
}

/** 单条消息 */
export interface MessageItem {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  citations: CitationData[];
  token_count?: number;
  created_at: string;
}

/** SSE 流事件类型 */
export type SSEEventType =
  | 'token'
  | 'citation'
  | 'done'
  | 'error'
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'max_iterations';

/** SSE Token 事件 */
export interface SSETokenEvent {
  text: string;
}

/** SSE Citation 事件 */
export interface SSECitationEvent {
  index: number;
}

/** SSE Done 事件 */
export interface SSEDoneEvent {
  citations: CitationData[];
  conversation_id: string;
  message_id: string;
}

/** SSE Tool Call 事件 (Agent 模式) */
export interface SSEToolCallEvent {
  name: string;
  arguments: Record<string, unknown>;
}

/** SSE Tool Result 事件 (Agent 模式) */
export interface SSEToolResultEvent {
  name: string;
  result: string;
}

/** Agent 思考步骤（前端展示用） */
export interface AgentStep {
  type: 'tool_call' | 'tool_result' | 'max_iterations';
  name?: string;
  arguments?: Record<string, unknown>;
  result?: string;
  message?: string;
  timestamp: number;
}
