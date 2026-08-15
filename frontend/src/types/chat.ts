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
  source_type: 'text' | 'video' | 'audio' | 'web' | 'note';
  source_id?: string;
  snapshot_id?: string;
  url?: string;
  title?: string;
  fetched_at?: string;
  content_hash?: string;
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
  | 'max_iterations'
  | 'run_started'
  | 'route_selected'
  | 'goal_created'
  | 'goal_running'
  | 'goal_retrying'
  | 'goal_completed'
  | 'goal_failed'
  | 'goal_cancelled'
  | 'source'
  | 'note_draft';

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
  run_id?: string;
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
  id?: string;
  node_id?: string;
  status?: 'running' | 'completed' | 'failed';
  duration_ms?: number;
}

export interface RouteSelection {
  agent_profile: string;
  model_provider: string;
  model_name: string;
  model_key?: string;
  model_uses_default?: boolean;
  tool_call_budget: number;
  tier: 'fast' | 'standard' | 'expert';
  route: 'direct' | 'tool_agent' | 'supervisor';
  score: number;
  reasons: string[];
  requires_decomposition: boolean;
  max_children: number;
  max_depth: number;
  tier_preference: AgentTierPreference;
}

export type GoalStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface GoalNodeData {
  id: string;
  run_id: string;
  parent_id: string | null;
  title: string;
  kind: string;
  status: GoalStatus;
  agent_profile: string;
  model_provider: string;
  model_name: string;
  tool_call_budget: number;
  sequence: number;
  attempt: number;
  max_attempts: number;
  dependencies: string[];
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface RunEventData {
  event_id: string;
  run_id: string;
  node_id: string | null;
  sequence: number;
  type: string;
  timestamp: string;
  payload: { goal?: GoalNodeData; [key: string]: unknown };
}

export type RunStatus = 'running' | 'paused' | 'completed' | 'failed' | 'cancelled' | 'interrupted';

export interface RunMetrics {
  duration_ms: number | null;
  goal_count: number;
  agent_count: number;
  goals_completed: number;
  goals_failed: number;
  goals_cancelled: number;
  tool_calls_used: number;
  tool_calls_failed: number;
  tool_duration_ms: number;
  tool_call_budget: number;
  web_pages_used: number;
  web_page_budget: number;
}

export interface ResearchRunSummary {
  id: string;
  conversation_id: string;
  retry_of_run_id: string | null;
  retry_count: number;
  mode: ChatMode;
  status: RunStatus;
  model_provider: string;
  model_name: string;
  routing: RouteSelection;
  metrics: RunMetrics;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface PersistedToolExecution {
  id: string;
  node_id: string | null;
  iteration: number;
  name: string;
  arguments: Record<string, unknown>;
  status: 'running' | 'completed' | 'failed';
  duration_ms: number | null;
  error_message: string | null;
  created_at: string | null;
}

export interface ResearchRunDetail extends ResearchRunSummary {
  retryable: boolean;
  retried_by_run_ids: string[];
  goals: GoalNodeData[];
  events: RunEventData[];
  tools: PersistedToolExecution[];
}

export interface ConversationSummary {
  id: string;
  title: string;
  model_provider: string;
  model_name: string;
  created_at: string | null;
  updated_at: string | null;
  message_count: number;
}

export interface ConversationDetail extends Omit<ConversationSummary, 'message_count'> {
  messages: MessageItem[];
}

export type ChatMode = 'auto' | 'local' | 'web';
export type AgentTierPreference = 'auto' | 'fast' | 'standard' | 'expert';
