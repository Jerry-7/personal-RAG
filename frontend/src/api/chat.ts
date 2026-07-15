/**
 * 聊天 API - SSE 流式查询
 *
 * 使用 fetch + ReadableStream 消费 SSE 流，
 * 支持逐 token 渲染和引用标记。
 * Agent 模式附加 tool_call/tool_result 事件。
 */

import type { SSEDoneEvent } from '../types/chat';

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
  onToolCall?: (name: string, args: Record<string, unknown>) => void;
  /** Agent 模式：工具调用结果 */
  onToolResult?: (name: string, result: string) => void;
  /** Agent 模式：达到最大迭代 */
  onMaxIterations?: (message: string) => void;
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
  callbacks: ChatStreamCallbacks
): AbortController {
  const controller = new AbortController();

  fetch('/api/chat/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, conversation_id: conversationId }),
    signal: controller.signal,
  }).then(async (response) => {
    if (!response.ok) {
      callbacks.onError(`HTTP ${response.status}: ${response.statusText}`);
      return;
    }
    if (!response.body) {
      callbacks.onError('响应体为空');
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        let eventType = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            const dataStr = line.slice(6);
            try {
              const data = JSON.parse(dataStr);
              switch (eventType) {
                case 'token':
                  callbacks.onToken(data.text || '');
                  break;
                case 'citation':
                  callbacks.onCitation(data.index);
                  break;
                case 'done':
                  callbacks.onDone(data as SSEDoneEvent);
                  break;
                case 'error':
                  callbacks.onError(data.message || '未知错误');
                  break;
                // ── Agent 模式事件 ──────────────────────────
                case 'tool_call':
                  callbacks.onToolCall?.(data.name, data.arguments);
                  break;
                case 'tool_result':
                  callbacks.onToolResult?.(data.name, data.result);
                  break;
                case 'max_iterations':
                  callbacks.onMaxIterations?.(data.message || '达到最大搜索次数');
                  break;
              }
            } catch {
              // 跳过 JSON 解析失败的行
            }
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== 'AbortError') {
        callbacks.onError(err.message);
      }
    }
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      callbacks.onError(err.message);
    }
  });

  return controller;
}

/** 取消对话生成 */
export async function cancelChat(conversationId: string): Promise<void> {
  await fetch('/api/chat/cancel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation_id: conversationId }),
  });
}
