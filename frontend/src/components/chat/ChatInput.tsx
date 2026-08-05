/**
 * 聊天输入框组件
 *
 * 多行文本输入 + 发送按钮。
 * 当没有已索引文档时禁用。
 */

import { useState, useRef, useCallback } from 'react';
import type { KeyboardEvent } from 'react';
import { Send, Square } from 'lucide-react';
import type { ChatMode } from '../../types/chat';
import { useChatStore } from '../../store/chatStore';
import { useDocumentStore } from '../../store/documentStore';
import { cancelChat, streamChatQuery } from '../../api/chat';
import { useSidebarStore } from '../../store/sidebarStore';
import { useNoteStore } from '../../store/noteStore';

export function ChatInput() {
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [mode, setMode] = useState<ChatMode>('auto');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const addUserMessage = useChatStore((s) => s.addUserMessage);
  const startStreaming = useChatStore((s) => s.startStreaming);
  const appendToken = useChatStore((s) => s.appendToken);
  const finishStreaming = useChatStore((s) => s.finishStreaming);
  const setConversationId = useChatStore((s) => s.setConversationId);
  const conversationId = useChatStore((s) => s.conversationId);
  const setRunId = useChatStore((s) => s.setRunId);
  const addToolCall = useChatStore((s) => s.addToolCall);
  const finishToolCall = useChatStore((s) => s.finishToolCall);
  const isLoadingHistory = useChatStore((s) => s.isLoadingHistory);
  const documents = useDocumentStore((s) => s.documents);
  const indexedCount = documents.filter((d) => d.status === 'indexed').length;
  const indexedNoteCount = useNoteStore((s) => s.notes.filter((note) => note.index_status === 'indexed').length);
  const hasLocalKnowledge = indexedCount + indexedNoteCount > 0;

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || isSending || isLoadingHistory) return;

    addUserMessage(text);
    setInput('');
    setIsSending(true);
    startStreaming();

    // 发起 SSE 流式请求
    abortRef.current = streamChatQuery(text, conversationId, mode, {
      onToken: appendToken,
      onCitation: (_index) => {
        // [N] 标记已由后端作为 token 事件发送（含 "[1]" 文本），
        // 前端 appendToken 自动将其追加到 streamingText，无需额外处理
      },
      onDone: (data) => {
        // 首次对话时记录 conversation_id，后续消息才能归属到同一对话
        if (!conversationId && data.conversation_id) {
          setConversationId(data.conversation_id);
        }
        finishStreaming(data.citations, data.message_id);
        setIsSending(false);
      },
      onError: (error) => {
        console.error('Chat error:', error);
        if (!useChatStore.getState().isStreaming) return;
        appendToken(`生成失败：${error}`);
        finishStreaming([], crypto.randomUUID());
        setIsSending(false);
      },
      onRunStarted: (runId, serverConversationId) => {
        setRunId(runId);
        if (serverConversationId) setConversationId(serverConversationId);
      },
      onToolCall: addToolCall,
      onToolResult: finishToolCall,
      onNoteDraft: (note) => {
        useNoteStore.getState().upsertNote(note);
        useSidebarStore.getState().openDraft(note);
      },
    });
  }, [input, isSending, isLoadingHistory, conversationId, mode, addUserMessage, startStreaming, appendToken, finishStreaming, setConversationId, setRunId, addToolCall, finishToolCall]);

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleCancel = () => {
    const currentConversationId = useChatStore.getState().conversationId;
    if (currentConversationId) void cancelChat(currentConversationId);
    abortRef.current?.abort();
    setIsSending(false);
  };

  return (
    <div className="border-t border-gray-200 dark:border-gray-700 p-4">
      <div className="mx-auto mb-2 flex max-w-3xl items-center gap-1" role="group" aria-label="研究模式">
        {(['auto', 'local', 'web'] as ChatMode[]).map((item) => (
          <button key={item} onClick={() => setMode(item)} className={`h-7 min-w-14 px-2 text-xs ${mode === item ? 'bg-gray-800 text-white dark:bg-gray-100 dark:text-gray-900' : 'border border-gray-200 text-gray-500 dark:border-gray-700'} ${item === 'auto' ? 'rounded-l' : item === 'web' ? 'rounded-r' : ''}`}>
            {{ auto: '自动', local: '本地', web: '网页' }[item]}
          </button>
        ))}
      </div>
      <div className="flex items-end gap-2 max-w-3xl mx-auto">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            mode === 'local' && !hasLocalKnowledge
              ? '本地模式需要先上传文档或索引笔记'
              : '输入问题，按 Enter 发送'
          }
          disabled={isLoadingHistory || (mode === 'local' && !hasLocalKnowledge)}
          rows={1}
          className="flex-1 resize-none rounded-xl border border-gray-300 dark:border-gray-600 px-4 py-3 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          style={{ maxHeight: '120px' }}
        />

        {isSending ? (
          <button
            onClick={handleCancel}
            title="停止生成"
            className="p-3 rounded bg-red-600 text-white hover:bg-red-700 transition-colors shrink-0"
          >
            <Square className="h-5 w-5" />
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!input.trim()}
            title="发送"
            className="p-3 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors shrink-0"
          >
            <Send className="w-5 h-5" />
          </button>
        )}
      </div>
    </div>
  );
}
